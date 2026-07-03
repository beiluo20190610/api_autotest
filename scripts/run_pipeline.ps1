<#
.SYNOPSIS
  API 场景自动化 Pipeline：环境检查 → 可选后端探针 → pytest → Allure 报告

.EXAMPLE
  .\scripts\run_pipeline.ps1
  .\scripts\run_pipeline.ps1 -Mode smoke
  .\scripts\run_pipeline.ps1 -Mode full -ServeAllure
  .\scripts\run_pipeline.ps1 -Mode full -Filter "SCN-SYSTEMSTORE"
  .\scripts\run_pipeline.ps1 -SkipVerify -SkipDbCheck
#>
[CmdletBinding()]
param(
    [ValidateSet("full", "smoke")]
    [string]$Mode = "full",

    [string]$Filter = "",

    [switch]$SkipDbCheck,
    [switch]$SkipVerify,
    [switch]$SkipCleanup,
    [switch]$ServeAllure,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Stage($msg) {
    Write-Host ""
    Write-Host "========== $msg ==========" -ForegroundColor Cyan
}

function Test-CommandExists($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Exit-IfFailed($step, $code) {
    if ($code -ne 0) {
        Write-Host "[$step] 失败，退出码: $code" -ForegroundColor Red
        exit $code
    }
}

Write-Stage "Pipeline 启动 (Mode=$Mode)"
Write-Host "工作目录: $Root"

# --- 1. 依赖检查 ---
Write-Stage "1/6 依赖检查"
Exit-IfFailed "python" (python --version > $null; $LASTEXITCODE)
Exit-IfFailed "pytest" (pytest --version > $null; $LASTEXITCODE)

if (-not (Test-Path ".env")) {
    Write-Host "警告: 未找到 .env，将使用 config/config.yaml 与环境变量默认值" -ForegroundColor Yellow
}

if ($SkipCleanup) {
    $env:SKIP_CLEANUP = "1"
    Write-Host "已设置 SKIP_CLEANUP=1（pytest 结束后不清理 MySQL 测试数据）"
} else {
    Remove-Item Env:SKIP_CLEANUP -ErrorAction SilentlyContinue
}

# --- 2. 数据库连通性（可选） ---
if (-not $SkipDbCheck) {
    Write-Stage "2/6 数据库连通性"
    python scripts/check_db_connectivity.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "数据库检查失败；若仅测 HTTP 可加 -SkipDbCheck 跳过" -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
} else {
    Write-Stage "2/6 数据库连通性（已跳过）"
}

# --- 3. 后端修复探针（可选） ---
if (-not $SkipVerify) {
    Write-Stage "3/6 后端 P0/P1 探针"
    python scripts/verify_backend_fixes.py
    Exit-IfFailed "verify_backend_fixes" $LASTEXITCODE
} else {
    Write-Stage "3/6 后端探针（已跳过）"
}

# --- 4. 清理旧 Allure 结果 ---
Write-Stage "4/6 清理 Allure 历史"
python scripts/clean_allure.py
Exit-IfFailed "clean_allure" $LASTEXITCODE

# --- 5. 执行 pytest ---
Write-Stage "5/6 执行场景用例"
$marker = if ($Mode -eq "smoke") { "scenario and smoke" } else { "scenario" }
$pytestArgs = @(
    "testcases/test_scenario.py",
    "-m", $marker
)
if ($Quiet) {
    $pytestArgs += "-q"
} else {
    $pytestArgs += @("-v", "-s", "-rA")
}
if ($Filter) {
    $pytestArgs += @("-k", $Filter)
}
$pytestArgs += "--alluredir=./allure-results"

Write-Host "pytest $($pytestArgs -join ' ')"
pytest @pytestArgs
$pytestExit = $LASTEXITCODE

# --- 6. Allure 报告 ---
Write-Stage "6/6 生成 Allure 报告"
if (-not (Test-CommandExists "allure")) {
    Write-Host "未安装 allure 命令行，跳过报告生成。" -ForegroundColor Yellow
    Write-Host "安装后可执行: allure serve allure-results" -ForegroundColor Yellow
    exit $pytestExit
}

if (-not (Test-Path "allure-results")) {
    Write-Host "allure-results 不存在，跳过报告" -ForegroundColor Yellow
    exit $pytestExit
}

allure generate allure-results -o allure-report --clean
Exit-IfFailed "allure generate" $LASTEXITCODE
Write-Host "静态报告: $Root\allure-report\index.html" -ForegroundColor Green

if ($ServeAllure) {
    Write-Host "正在启动 Allure 本地服务（Ctrl+C 退出）..." -ForegroundColor Cyan
    allure serve allure-results
}

Write-Stage "Pipeline 结束"
if ($pytestExit -ne 0) {
    Write-Host "pytest 存在失败用例，退出码: $pytestExit" -ForegroundColor Red
    exit $pytestExit
}

Write-Host "全部通过" -ForegroundColor Green
exit 0
