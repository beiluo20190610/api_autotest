import os
import shutil
from pathlib import Path

import pytest

from core.api_client import ApiClient
from utils.data_handler import DataHandler

ROOT = Path(__file__).resolve().parent

REGISTERED_MARKERS = frozenset(
    {"smoke", "positive", "negative", "boundary", "high", "medium", "low", "skip_env"}
)

_session_token: str = ""


def clear_session_token(client: ApiClient = None):
    """登出或 Token 失效后清理缓存。"""
    global _session_token
    _session_token = ""
    os.environ.pop("COMMON_TOKEN", None)
    if client is not None:
        client.session.headers.pop("Authori-zation", None)


@pytest.fixture(scope="session")
def api_client():
    return ApiClient()


@pytest.fixture(scope="session")
def all_cases_data():
    return DataHandler.load_all_cases()


def build_case_params(case_list):
    """将 CSV tags / test_type / priority 映射为 pytest marker。"""
    params = []
    for case in case_list:
        marks = []
        for source in (case.get("tags", ""), case.get("test_type", ""), case.get("priority", "")):
            for part in str(source).split(","):
                tag = part.strip()
                if tag == "skip_env":
                    marks.append(pytest.mark.skip(reason="当前环境/请求体待补全，Playwright 探针确认暂跳过"))
                elif tag in REGISTERED_MARKERS:
                    marks.append(getattr(pytest.mark, tag))
        params.append(pytest.param(case, id=case["test_case_id"], marks=marks))
    return params


def _ensure_login(client: ApiClient) -> str:
    """每次需要登录时重新获取 Token，避免登出后复用失效 Token。"""
    global _session_token

    account = os.getenv("LOGIN_USER", "admin")
    password = os.getenv("LOGIN_PASS", "123456")
    resp = client.request(
        method="POST",
        url="/api/admin/login",
        data={"account": account, "pwd": password},
        content_type="json",
    )
    body = resp.json()
    token = body.get("data", {}).get("token", "")
    if not token:
        raise RuntimeError(f"登录失败，无法获取 token：{body}")
    _session_token = token
    os.environ["COMMON_TOKEN"] = token
    client.session.headers.update({"Authori-zation": token})
    return token


def exec_pre_condition(pre_str: str, client: ApiClient):
    pre = (pre_str or "").strip()
    if not pre or pre == "无":
        # 未登录用例：清除 Session 中残留的 Token，避免串扰
        clear_session_token(client)
        return
    if "已登录" in pre:
        _ensure_login(client)


def exec_post_condition(post_str: str, client: ApiClient):
    if not post_str or not post_str.strip() or post_str.strip() == "无":
        return
    if "清除Token" in post_str or "登出" in post_str:
        clear_session_token(client)


def resolve_case(case: dict) -> dict:
    """渲染 url / headers / request_data 中的 ${ENV} 与 ${DB:key} 占位符。"""
    from utils.var_render import VarRender

    resolved = dict(case)
    for field in ("url", "headers", "request_data"):
        raw = resolved.get(field) or ("{}" if field != "url" else "")
        resolved[field] = VarRender.render_params(raw)
    return resolved


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
