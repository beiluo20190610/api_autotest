"""场景用例：加载 CSV、初始化阶段预置 DB+Mock 上下文。"""
import os
from typing import Any, Dict, List

from utils.common import get_project_root
from utils.db_helper import CrmebDb, DB_PLACEHOLDER_ALIAS, DB_QUERIES
from utils.form_temp_helper import default_form_temp_content
from utils.mock_data import MockData


def infer_scenario_module(scenario_id: str) -> str:
    """从 SCN-{MODULE}-... 解析模块名（bootstrap 未分配 assignment 时用于清理 seed 实体键）。"""
    if not scenario_id or not scenario_id.startswith("SCN-"):
        return ""
    parts = scenario_id.split("-")
    if len(parts) >= 2:
        return parts[1].strip().lower()
    return ""


class ScenarioDataProvider:
    """仅在 initialize_test_environment 阶段查库，写入 context 快照。"""

    @staticmethod
    def build_initial_context() -> Dict[str, Any]:
        MockData.reset()
        ctx: Dict[str, Any] = dict(MockData.base_context())
        ctx["LOGIN_USER"] = os.getenv("LOGIN_USER", "admin")
        ctx["LOGIN_PASS"] = os.getenv("LOGIN_PASS", "123456")

        for db_key in DB_QUERIES:
            val = CrmebDb.get_optional(db_key, "")
            if val != "":
                ctx[db_key] = val

        for placeholder, db_key in DB_PLACEHOLDER_ALIAS.items():
            val = ctx.get(db_key) or CrmebDb.get_optional(db_key, "")
            if val != "":
                ctx[placeholder] = val

        if "couponIds" not in ctx:
            ctx["couponIds"] = ctx.get("coupon_ids", "")

        ScenarioDataProvider._load_runtime_pools(ctx)
        ScenarioDataProvider._load_form_temp_content(ctx)
        return ctx

    @staticmethod
    def _load_form_temp_content(ctx: Dict[str, Any]) -> None:
        """初始化阶段加载表单模板 content，供 SystemGroupData 等场景只读。"""
        sgid = int(
            ctx.get("system_group_id")
            or ctx.get("latest_system_group_id")
            or ctx.get("auto_system_group_id")
            or 0
        )
        fid = 0
        if sgid > 0:
            try:
                row = CrmebDb.get_row(
                    f"SELECT form_id FROM eb_system_group WHERE id = {sgid} LIMIT 1"
                )
                fid = int(row.get("form_id") or 0)
            except Exception:
                fid = 0
        if fid <= 0:
            fid = int(ctx.get("group_form_id") or ctx.get("form_id") or 0)
        if fid > 0:
            ctx["group_form_id"] = str(fid)
        if not fid:
            ctx["form_temp_content"] = default_form_temp_content()
            return
        try:
            row = CrmebDb.get_row(
                f"SELECT content FROM eb_system_form_temp WHERE id = {fid} LIMIT 1"
            )
            content = row.get("content") if row else ""
            if content and "__vModel__" in str(content):
                ctx["form_temp_content"] = content
                return
        except Exception:
            pass
        ctx["form_temp_content"] = default_form_temp_content()

    @staticmethod
    def _load_runtime_pools(ctx: Dict[str, Any]) -> None:
        """预加载 enrich 阶段原需查库/删库的数据，供用例只读 context。"""
        staff_pool: List[int] = []
        try:
            conn = CrmebDb._connect()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT u.uid FROM eb_user u "
                    "LEFT JOIN eb_system_store_staff s ON u.uid=s.uid "
                    "WHERE s.uid IS NULL ORDER BY u.uid DESC LIMIT 30"
                )
                for row in cur.fetchall() or []:
                    uid = int(next(iter(row.values())) or 0)
                    if uid > 0:
                        staff_pool.append(uid)
            conn.close()
        except Exception:
            pass
        ctx["_staff_uid_pool"] = staff_pool

        occupied: set = set()
        time_by_id: Dict[str, str] = {}
        try:
            conn = CrmebDb._connect()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, start_time, end_time FROM eb_store_seckill_manger WHERE is_del=0"
                )
                for row in cur.fetchall() or []:
                    mid = int(row.get("id") or 0)
                    start = int(row.get("start_time") or 0)
                    end = int(row.get("end_time") or start + 1)
                    for h in range(start, max(start, end)):
                        occupied.add(h)
                    if mid:
                        time_by_id[str(mid)] = f"{start:02d}:00,{end:02d}:00"
            conn.close()
        except Exception:
            pass
        ctx["_seckill_occupied_hours"] = sorted(occupied)
        ctx["_seckill_free_hours"] = [h for h in range(23) if h not in occupied]
        ctx["_seckill_hour_idx"] = 0
        ctx["_seckill_time_by_id"] = time_by_id

        try:
            conn = CrmebDb._connect()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM eb_system_user_level "
                    "WHERE is_show=1 AND is_del=0 ORDER BY id DESC LIMIT 2"
                )
                rows = cur.fetchall() or []
                if len(rows) >= 2:
                    ctx["alt_user_level_id"] = str(next(iter(rows[1].values())))
                elif rows:
                    ctx["alt_user_level_id"] = str(next(iter(rows[0].values())))
                cur.execute(
                    "SELECT MAX(grade) AS g, MAX(experience) AS e FROM eb_system_user_level"
                )
                mx = cur.fetchone() or {}
                ctx["next_user_grade"] = str(int(mx.get("g") or 0) + 100)
                ctx["next_user_experience"] = str(int(mx.get("e") or 0) + 10000)
            conn.close()
        except Exception:
            pass

    @staticmethod
    def build_scenario_context() -> Dict[str, Any]:
        """兼容旧调用；正式流程应使用 TestEnvironment.new_scenario_context()。"""
        return ScenarioDataProvider.build_initial_context()


def load_scenario_cases(csv_path: str = None):
    import pandas as pd

    if csv_path is None:
        csv_path = os.path.join(get_project_root(), "data", "scenario_test_cases.csv")
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df.columns = [str(c).lstrip("\ufeff").strip() for c in df.columns]
    return df.fillna("")


class ScenarioDataHandler:
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
                    "testcase_id": records[0].get("testcase_id", ""),
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
