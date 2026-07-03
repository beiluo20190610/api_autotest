import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session", autouse=True)
def test_environment():
    """Session 级：seed + bootstrap + 共享 ApiClient；结束后清理测试数据。"""
    from utils.environment_init import initialize_test_environment

    env = initialize_test_environment(flush_redis=False)
    yield env

    if os.getenv("SKIP_CLEANUP", "").lower() in ("1", "true", "yes"):
        return

    from core.logger import logger
    from utils.test_data_cleanup import cleanup_summary, run_cleanup

    logger.info("pytest session 结束，开始清理自动化测试数据…")
    results = run_cleanup()
    logger.info("测试数据清理完成\n" + cleanup_summary(results))


@pytest.fixture(scope="session")
def api_client(test_environment):
    return test_environment.api_client


def _clean_allure_dirs(alluredir: str) -> None:
    """使用 --alluredir 时先清空旧结果，避免报告混入历史数据。"""
    target = Path(alluredir)
    if not target.is_absolute():
        target = ROOT / target
    if target.exists():
        shutil.rmtree(target)
    report_dir = ROOT / "allure-report"
    if report_dir.exists():
        shutil.rmtree(report_dir)


def pytest_configure(config):
    alluredir = config.getoption("allure_report_dir", default=None)
    if alluredir:
        _clean_allure_dirs(alluredir)
