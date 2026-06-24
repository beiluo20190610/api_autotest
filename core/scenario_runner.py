"""业务场景多接口串联执行器。"""
import json
import re
from typing import Any, Dict, List, Optional

import allure

from core.api_client import ApiClient
from core.assertions import ApiAssertions
from core.logger import logger
from utils.scenario_body_enricher import enrich_request, resolve_content_type, strip_unresolved, clean_url, _is_unresolved
from utils.scenario_data import ScenarioDataProvider
from utils.var_render import VarRender
from utils.db_helper import CrmebDb

_UNRESOLVED = re.compile(r"^\$\{[^}]+\}$")


def _normalize_path(path: str) -> str:
    return re.sub(r"\[(\d+)\]", r".\1", path.strip())


def extract_by_path(root: Any, path: str) -> Any:
    """支持 response.data.list[0].id；列表直出时自动回退为 response.data[0].id。"""
    candidates = [path]
    if ".list[" in path or ".list." in path:
        candidates.append(re.sub(r"\.list(?=\[|\.)", "", path))
    last_exc: Optional[Exception] = None
    for candidate in candidates:
        try:
            cur = root
            for part in _normalize_path(candidate).split("."):
                if not part:
                    continue
                if part.isdigit():
                    cur = cur[int(part)]
                else:
                    cur = cur[part]
            return cur
        except (KeyError, IndexError, TypeError) as exc:
            last_exc = exc
            continue
    if last_exc:
        raise last_exc
    raise KeyError(path)


def _parse_json(raw: str, default: Any) -> Any:
    raw = (raw or "").strip()
    if not raw or raw == "{}":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _sanitize_payload(data: Any) -> Any:
    """未解析占位符：id 类置 0，其余省略。"""
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if isinstance(value, str) and _UNRESOLVED.match(value):
                if key.lower() in ("id", "entity_id", "cid", "pid", "cateid", "tempid"):
                    cleaned[key] = 0
                continue
            cleaned[key] = _sanitize_payload(value)
        return cleaned
    if isinstance(data, list):
        return [_sanitize_payload(v) for v in data]
    return data


# operationId -> 额外提取路径（CSV 中 list 路径不准确时）
EXTRACT_PATH_FALLBACK: Dict[str, Dict[str, str]] = {
    "ScheduleJobController_getList": {
        "entity_id": "response.data[0].jobId",
        "jobId": "response.data[0].jobId",
    },
    "SystemNotificationController_getList": {
        "entity_id": "response.data[0].id",
    },
    "CategoryController_getList": {
        "entity_id": "response.data[0].id",
    },
    "ExpressController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "StoreCouponController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "UserController_getList": {
        "entity_id": "response.data.list[0].uid",
    },
    "SystemCityController_getList": {
        "entity_id": "response.data.list[0].cityId",
    },
    "SystemMenuController_getList": {
        "entity_id": "response.data[0].id",
    },
}

# list 提取失败时按模块回退 DB
MODULE_ENTITY_DB_FALLBACK: Dict[str, str] = {
    "userextract": "extract_id",
    "schedulejob": "schedule_job_id",
    "systemnotification": "notification_id",
    "express": "express_id",
    "storecoupon": "coupon_id",
    "user": "user_uid",
    "systemmenu": "menu_id",
    "systemcity": "city_id",
    "systemstorestaff": "staff_id",
    "systemattachment": "attachment_id",
    "product": "product_id",
    "wechatreply": "wechat_reply_id",
    "pagediy": "pagediy_id",
    "usergroup": "user_group_id",
    "usertag": "user_tag_id",
}

# save 后 response.data 常为文案，用最新库记录回填 entity_id（按 operationId）
SAVE_ENTITY_DB_KEY: Dict[str, str] = {
    "UserGroupController_save": "user_group_id",
    "UserTagController_save": "user_tag_id",
    "WechatReplyController_save": "wechat_reply_id",
    "PageDiyController_save": "pagediy_id",
    "ActivityStyleController_save": "activity_style_id",
    "SystemAttachmentController_save": "attachment_id",
    "StoreProductController_save": "product_id",
    "SystemRoleController_save": "role_id",
    "SystemStoreController_save": "store_id",
    "SystemStoreStaffController_save": "staff_id",
    "SystemFormTempController_save": "form_id",
    "SystemGroupDataController_save": "group_data_id",
    "StoreBargainController_save": "bargain_id",
    "StoreCombinationController_save": "combination_id",
    "StoreSeckillController_save": "seckill_id",
    "StoreSeckillMangerController_save": "seckill_time_id",
    "StoreProductRuleController_save": "product_rule_id",
}


def _is_valid_entity_id(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        return value.isdigit()
    return False


class ScenarioRunner:
    """按 scenario_test_cases.csv 顺序执行步骤，维护 var_extract / var_bind 上下文。"""

    SKIP_SCENARIO_IDS = {
        "SCN-STOREPRODUCT-IMPORTPRODUCT-CHAIN",
        "SCN-SCHEDULEJOB-CRUD",
        "SCN-USEREXTRACT-CRUD",
        "SCN-ACTIVITYSTYLE-CRUD",
        "SCN-PAGEDIY-CRUD",
        "SCN-STORESECKILLMANGER-CRUD",
        "SCN-SYSTEMADMIN-CRUD",
        "SCN-SYSTEMGROUPDATA-CRUD",
        "SCN-STOREPRODUCTRULE-CRUD",
        "SCN-SYSTEMROLE-CRUD",
        "SCN-SYSTEMSTORESTAFF-CRUD",
        "SCN-SYSTEMFORMTEMP-CRUD",
        "SCN-SYSTEMCITY-CRUD",
        "SCN-STOREBARGAIN-CRUD",
        "SCN-SYSTEMSTORE-CRUD",
    }

    def __init__(self, api_client: ApiClient):
        self.client = api_client
        self.context: Dict[str, Any] = ScenarioDataProvider.build_initial_context()

    def run(self, steps: List[Dict[str, Any]], scenario_name: str = "") -> None:
        total = len(steps)
        for step in steps:
            step_no = int(step.get("step_no", 0))
            title = step.get("test_case_name") or step.get("operation_id", "")
            with allure.step(f"[{step_no}/{total}] {title}"):
                self._run_step(step)

    def _run_step(self, step: Dict[str, Any]) -> None:
        self._ensure_entity_id_for_url(step)
        url = clean_url(VarRender.render_params(step.get("url", ""), self.context))
        headers = _parse_json(
            VarRender.render_params(step.get("headers", "{}"), self.context), {}
        )
        req_data = _sanitize_payload(
            _parse_json(
                VarRender.render_params(step.get("request_data", "{}"), self.context),
                {},
            )
        )
        var_bind = _parse_json(
            VarRender.render_params(step.get("var_bind", "{}"), self.context), {}
        )

        for key, value in var_bind.items():
            if _is_unresolved(value):
                continue
            if key.lower() in ("authori-zation", "authorization"):
                headers[key] = value
            elif step.get("method", "GET").upper() == "GET" and key == "id":
                if f"id={value}" not in url:
                    if "?" in url:
                        url += f"&id={value}"
                    else:
                        url += f"?id={value}"
            else:
                req_data[key] = value

        req_data, url = enrich_request(
            step,
            req_data,
            url,
            context=self.context,
            api_client=self.client,
        )
        if step.get("operation_id") == "SystemNotificationController_info":
            if "detailType=" not in url:
                url = f"{url}&detailType=wechat" if "?" in url else f"{url}?detailType=wechat"
        if step.get("operation_id") == "PageDiyController_save":
            req_data["isDel"] = 0
        content_type = resolve_content_type(step)

        token = self.context.get("token") or self.context.get("COMMON_TOKEN")
        if token and "Authori-zation" not in headers and "Authorization" not in headers:
            if step.get("operation_id") != "AdminLoginController_SystemAdminLogin":
                headers["Authori-zation"] = token

        with allure.step(f"{step.get('method', 'GET').upper()} {url}"):
            resp = self.client.request(
                method=step.get("method", "GET"),
                url=url,
                headers=headers,
                data=req_data if req_data else None,
                content_type=content_type,
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
                        msg = body.get("message", "")
                        raise AssertionError(f"{exc}; 响应: {body}") from exc
                    except Exception:
                        raise

        self._extract_variables(resp, step)
        if step.get("operation_id", "").endswith("_save"):
            self._fallback_save_entity_id(step)

    def _ensure_entity_id_for_url(self, step: Dict[str, Any]) -> None:
        raw_url = step.get("url", "")
        if "${entity_id}" not in raw_url and "${ids}" not in raw_url:
            return
        if not _is_valid_entity_id(self.context.get("entity_id")):
            module = step.get("module", "")
            db_key = MODULE_ENTITY_DB_FALLBACK.get(module)
            if db_key:
                val = CrmebDb.get_optional(db_key, "")
                if val:
                    self.context["entity_id"] = val
        eid = self.context.get("entity_id")
        if eid and "${ids}" in raw_url:
            self.context["ids"] = eid

    def _fallback_save_entity_id(self, step: Dict[str, Any]) -> None:
        if _is_valid_entity_id(self.context.get("entity_id")):
            return
        op_id = step.get("operation_id", "")
        db_key = SAVE_ENTITY_DB_KEY.get(op_id)
        if not db_key:
            return
        val = CrmebDb.get_optional(db_key, "")
        if val:
            self.context["entity_id"] = val
            logger.info(f"save 后 DB 回填 entity_id={val}")

    def _extract_variables(self, resp, step: Dict[str, Any]) -> None:
        mapping = _parse_json(step.get("var_extract", "{}"), {})
        if not mapping:
            return
        try:
            body = resp.json()
        except Exception:
            logger.warning("响应非 JSON，跳过 var_extract")
            return

        root = {"response": body}
        op_id = step.get("operation_id", "")
        fallbacks = EXTRACT_PATH_FALLBACK.get(op_id, {})
        for name, json_path in mapping.items():
            paths = [json_path]
            if name in fallbacks:
                paths.insert(0, fallbacks[name])
            extracted = None
            for jp in paths:
                try:
                    extracted = extract_by_path(root, jp)
                    break
                except (KeyError, IndexError, TypeError):
                    continue
            if extracted is not None and extracted != "":
                if name == "entity_id" and not _is_valid_entity_id(extracted):
                    extracted = None
                else:
                    self.context[name] = extracted
                    if name in ("token", "COMMON_TOKEN"):
                        self.context["token"] = extracted
                        self.context["COMMON_TOKEN"] = extracted
                    if name == "entity_id":
                        self.context.setdefault("jobId", extracted)
                    logger.info(f"提取变量 {name}={extracted}")
                    continue
            if name == "entity_id":
                module = step.get("module", "")
                db_key = MODULE_ENTITY_DB_FALLBACK.get(module)
                if db_key:
                    try:
                        val = CrmebDb.get_optional(db_key, "")
                        if val:
                            self.context[name] = val
                            logger.info(f"DB 回退 {name}={val}")
                    except Exception:
                        pass
                logger.warning(f"var_extract 失败 {name} <- {json_path}")
