# 冒烟测试 + Allure 报告（执行前自动清理旧结果）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "==> 清理旧 Allure 结果..." -ForegroundColor Cyan
python scripts/clean_allure.py

Write-Host "==> 执行冒烟用例..." -ForegroundColor Cyan
pytest testcases/test_scenario.py -m "scenario and smoke" --alluredir=./allure-results
if ($LASTEXITCODE -ne 0) {
    Write-Host "pytest 存在失败用例，退出码: $LASTEXITCODE" -ForegroundColor Yellow
}

Write-Host "==> 启动 Allure 报告..." -ForegroundColor Cyan
allure serve allure-results
