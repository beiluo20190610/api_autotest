"""场景用例：加载 CSV、预置 DB+Mock 上下文。"""
import os
from typing import Any, Dict, List

from utils.common import get_project_root
from utils.data_handler import DataHandler
from utils.db_helper import CrmebDb, DB_PLACEHOLDER_ALIAS
from utils.mock_data import MockData


class ScenarioDataProvider:
    """场景执行前预置：关键 ID 从 DB，动态字段走 Mock。"""

    @staticmethod
    def build_initial_context() -> Dict[str, Any]:
        MockData.reset()
        ctx: Dict[str, Any] = dict(MockData.base_context())
        ctx["LOGIN_USER"] = os.getenv("LOGIN_USER", "admin")
        ctx["LOGIN_PASS"] = os.getenv("LOGIN_PASS", "123456")

        for placeholder, db_key in DB_PLACEHOLDER_ALIAS.items():
            try:
                ctx[placeholder] = CrmebDb.get(db_key)
            except (KeyError, RuntimeError):
                pass

        # couponIds 允许为空字符串
        if "couponIds" not in ctx:
            ctx["couponIds"] = CrmebDb.get_optional("coupon_ids", "")

        return ctx


def load_scenario_cases(csv_path: str = None):
    import pandas as pd

    if csv_path is None:
        csv_path = os.path.join(get_project_root(), "data", "scenario_test_cases.csv")
    df = pd.read_csv(csv_path, dtype=str)
    return df.fillna("")


class ScenarioDataHandler(DataHandler):
    @staticmethod
    def get_all_scenarios(csv_path: str = None) -> List[Dict[str, Any]]:
        df = load_scenario_cases(csv_path)
        scenarios: List[Dict[str, Any]] = []
        for scenario_id, group in df.groupby("scenario_id", sort=True):
            steps = group.copy()
            steps["_step_no"] = steps["step_no"].astype(int)
            steps = steps.sort_values("_step_no")
            records = steps.drop(columns=["_step_no"]).to_dict("records")
            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_name": records[0].get("scenario_name", scenario_id),
                    "step_count": len(records),
                    "priority": records[0].get("priority", "medium"),
                    "tags": records[0].get("tags", ""),
                    "steps": records,
                }
            )
        return scenarios

    @staticmethod
    def get_scenario_by_id(scenario_id: str) -> Dict[str, Any]:
        for item in ScenarioDataHandler.get_all_scenarios():
            if item["scenario_id"] == scenario_id:
                return item
        raise KeyError(f"未找到场景：{scenario_id}")
