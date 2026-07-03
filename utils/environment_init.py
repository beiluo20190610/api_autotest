"""测试环境一次性初始化：seed、批量场景数据、全量上下文快照、共享 ApiClient。"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.api_client import ApiClient
from core.logger import logger
from utils.context_data import MODULE_ENTITY_KEY
from utils.db_helper import CrmebDb, DB_PLACEHOLDER_ALIAS
from utils.mock_data import MockData
from utils.scenario_data import ScenarioDataHandler, ScenarioDataProvider, infer_scenario_module
from utils.scenario_entity_bootstrap import run_bootstrap
from utils.seed_environment import run_seed

_env: Optional["TestEnvironment"] = None


@dataclass
class TestEnvironment:
    """Session 级测试环境。"""

    base_context: Dict[str, Any]
    api_client: ApiClient

    def new_scenario_context(self, scenario_id: str = "") -> Dict[str, Any]:
        """复制初始化快照，并注入该场景专属 entity（不查库）。"""
        ctx = copy.deepcopy(self.base_context)
        MockData.reset()
        rid = MockData.run_id()
        ctx["RUN_ID"] = rid
        ctx["MOCK_NAME"] = f"auto_name_{rid}"
        ctx["MOCK_TITLE"] = f"auto_title_{rid}"
        assignment = (ctx.get("scenario_assignments") or {}).get(scenario_id, {})
        scenario_module = str(
            assignment.get("_scenario_module") or infer_scenario_module(scenario_id)
        ).lower()
        if scenario_module:
            ctx["_scenario_module"] = scenario_module
        if assignment.get("_preassigned_entity"):
            ctx["_preassigned_entity"] = True
        # 保留 init 阶段分配的资源位（秒杀时段/店员 uid），避免每场景重置后撞车
        if assignment.get("_seckill_slot_idx") is not None:
            ctx["_seckill_hour_idx"] = int(assignment["_seckill_slot_idx"])
        else:
            ctx["_seckill_hour_idx"] = 0
        for key, value in assignment.items():
            if value not in (None, ""):
                ctx[key] = value
        staff_uid = assignment.get("staff_uid") or assignment.get("_staff_uid")
        if assignment.get("_preassigned_entity") and staff_uid:
            ctx["uid"] = str(staff_uid)
        if assignment.get("store_id"):
            ctx["storeId"] = str(assignment["store_id"])

        for key in ("token", "COMMON_TOKEN", "_last_rule_name", "_entity_locked", "_scenario_saved_entity_id"):
            ctx.pop(key, None)

        if not assignment.get("_preassigned_entity"):
            ctx.pop("entity_id", None)
            ctx.pop("ids", None)
            ctx.pop("id", None)
            mod = scenario_module
            if mod == "systemstorestaff":
                ctx.pop("staff_uid", None)
                ctx.pop("_staff_uid", None)
                if str(ctx.get("uid", "")) == str(assignment.get("staff_uid", "")):
                    ctx.pop("uid", None)
            entity_key = MODULE_ENTITY_KEY.get(str(mod).lower(), "")
            if entity_key:
                keep_seed_template = mod == "product" and entity_key == "product_id"
                if not keep_seed_template:
                    ctx.pop(entity_key, None)
                    for placeholder, db_key in DB_PLACEHOLDER_ALIAS.items():
                        if db_key == entity_key:
                            ctx.pop(placeholder, None)
            entity_keys = set(MODULE_ENTITY_KEY.values()) | {"entity_id", "ids", "id"}
            for key in list(assignment.keys()):
                if key not in entity_keys:
                    continue
                ctx.pop(key, None)
                for placeholder, db_key in DB_PLACEHOLDER_ALIAS.items():
                    if db_key == key:
                        ctx.pop(placeholder, None)

        mod = scenario_module
        if mod == "systemstorestaff":
            store_val = (
                assignment.get("store_id")
                or ctx.get("store_id")
                or ctx.get("storeId")
            )
            if store_val:
                ctx["store_id"] = str(store_val)
                ctx["storeId"] = str(store_val)

        ctx["scenario_id"] = scenario_id
        return ctx


def initialize_test_environment(
    *,
    flush_redis: bool = False,
    force: bool = False,
) -> TestEnvironment:
    """执行全部初始化（幂等，默认只跑一遍）。"""
    global _env
    if _env is not None and not force:
        return _env

    if os.getenv("SKIP_SEED", "").lower() in ("1", "true", "yes"):
        logger.info("SKIP_SEED=1，跳过 seed")
    else:
        run_seed(flush_redis=flush_redis)

    from utils.seed_environment import repair_invalid_user_group_ids

    repair_invalid_user_group_ids()

    from utils.context_data import reset_session_runtime_state

    reset_session_runtime_state()
    MockData.reset()
    CrmebDb.clear_cache()
    base_context = ScenarioDataProvider.build_initial_context()

    client = ApiClient()
    if os.getenv("SKIP_SEED", "").lower() not in ("1", "true", "yes"):
        logger.info("开始按场景批量插入业务数据…")
        assignments = run_bootstrap(client, base_context)
        base_context["scenario_assignments"] = assignments
        CrmebDb.clear_cache()
        refreshed = ScenarioDataProvider.build_initial_context()
        for key, val in refreshed.items():
            if not str(key).startswith("_") or key in (
                "_staff_uid_pool",
                "_seckill_free_hours",
                "_seckill_time_by_id",
                "_seckill_hour_idx",
                "_batch_store_pool",
                "_seckill_time_pool",
            ):
                base_context[key] = val
        base_context["scenario_assignments"] = assignments

    from utils.context_data import sync_seckill_session_from_context

    sync_seckill_session_from_context(base_context)

    _env = TestEnvironment(base_context=base_context, api_client=client)
    logger.info(
        f"测试环境初始化完成（seed + 批量场景数据 {len(base_context.get('scenario_assignments', {}))} 条 + 共享 ApiClient）"
    )
    return _env


def get_test_environment(*, auto_init: bool = True) -> TestEnvironment:
    if _env is None:
        if not auto_init:
            raise RuntimeError("测试环境未初始化，请先调用 initialize_test_environment()")
        return initialize_test_environment(flush_redis=False)
    return _env


def reset_test_environment() -> None:
    global _env
    _env = None
    CrmebDb.clear_cache()
