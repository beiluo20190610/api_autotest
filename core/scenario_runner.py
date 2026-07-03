"""业务场景多接口串联执行器（纯用例层：准备 → 请求 → 断言 → 上下文更新）。"""
from typing import Any, Dict, List

import allure

from core.api_client import ApiClient
from core.assertions import ApiAssertions
from core.logger import logger
from core.scenario_request_preparer import ScenarioRequestPreparer
from core.scenario_utils import extract_by_path
from utils.environment_init import get_test_environment
from utils.mock_data import MockData
from utils.scenario_skip import scenario_skip_reason, should_skip_scenario

# 兼容旧 import
__all__ = ["ScenarioRunner", "extract_by_path"]


class ScenarioRunner:
    """按 scenario_test_cases.csv 顺序执行步骤。"""

    @classmethod
    def skip_reason(cls, scenario_id: str) -> str | None:
        return scenario_skip_reason(scenario_id)

    @classmethod
    def should_skip(cls, scenario_id: str) -> bool:
        return should_skip_scenario(scenario_id)

    def __init__(
        self,
        api_client: ApiClient,
        *,
        scenario_id: str = "",
        base_context: Dict[str, Any] | None = None,
    ):
        self.client = api_client
        self.preparer = ScenarioRequestPreparer(api_client)
        if base_context is not None:
            self.context = base_context
        else:
            self.context = get_test_environment().new_scenario_context(scenario_id)
        self.scenario_id = scenario_id

    def run(self, steps: List[Dict[str, Any]], scenario_name: str = "") -> None:
        if not self.context.get("_preassigned_entity"):
            self.context.pop("entity_id", None)
            self.context.pop("ids", None)
        total = len(steps)
        for step in steps:
            step_no = int(step.get("step_no", 0))
            title = step.get("test_case_name") or step.get("operation_id", "")
            with allure.step(f"[{step_no}/{total}] {title}"):
                self._run_step(step)

    def _run_step(self, step: Dict[str, Any]) -> None:
        prepared = self.preparer.prepare(step, self.context)
        method = step.get("method", "GET").upper()

        with allure.step(f"{method} {prepared.url}"):
            resp = self.client.request(
                method=method,
                url=prepared.url,
                headers=prepared.headers,
                data=prepared.data,
                content_type=prepared.content_type,
            )

        ApiAssertions.assert_status_code(resp, int(step.get("expected_status_code", 200)))

        if step.get("expected_key_assert"):
            for key in (
                k.strip()
                for k in step["expected_key_assert"].split(",")
                if k.strip()
            ):
                ApiAssertions.assert_key_exists(resp, key)

        if step.get("expected_value_assert"):
            for pair in (
                p.strip()
                for p in step["expected_value_assert"].split(",")
                if "=" in p.strip()
            ):
                k, v = pair.split("=", 1)
                try:
                    ApiAssertions.assert_key_equal(resp, k.strip(), v.strip())
                except AssertionError as exc:
                    try:
                        body = resp.json()
                        raise AssertionError(f"{exc}; 响应: {body}") from exc
                    except Exception:
                        raise

        self.preparer.apply_response(step, self.context, resp)
