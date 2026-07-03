# 本地查看 Allure（必须通过 HTTP 服务，不能直接双击 index.html）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command allure -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 allure 命令，请先安装 Allure CLI" -ForegroundColor Red
    exit 1
}

if (Test-Path "allure-results") {
    Write-Host "启动 Allure 服务: allure serve allure-results" -ForegroundColor Cyan
    Write-Host "浏览器会自动打开；按 Ctrl+C 结束服务" -ForegroundColor Yellow
    allure serve allure-results
} elseif (Test-Path "allure-report\index.html") {
    Write-Host "启动 Allure 服务: allure open allure-report" -ForegroundColor Cyan
    allure open allure-report
} else {
    Write-Host "未找到 allure-results 或 allure-report，请先运行测试生成报告" -ForegroundColor Red
    exit 1
}
