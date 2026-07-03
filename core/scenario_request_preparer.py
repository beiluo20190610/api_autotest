"""场景步骤请求准备：渲染、body/url 补全、响应变量提取（不查库）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.api_client import ApiClient
from core.logger import logger
from core.scenario_utils import extract_by_path, parse_json as _parse_json, sanitize_payload as _sanitize_payload
from utils.context_data import MODULE_ENTITY_KEY, ctx_get_from
from utils.scenario_body_enricher import (
    bind_var_to_request,
    clean_url,
    enrich_request,
    resolve_content_type,
    restore_url_params,
    _is_unresolved,
)
from utils.var_render import VarRender

EXTRACT_PATH_FALLBACK: Dict[str, Dict[str, str]] = {
    "ScheduleJobController_getList": {
        "entity_id": "response.data[0].jobId",
        "jobId": "response.data[0].jobId",
    },
    "SystemNotificationController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "SystemGroupDataController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "SystemMenuController_getList": {
        "entity_id": "response.data[0].id",
    },
    "SystemGroupController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "StoreProductRuleController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "CategoryController_getList": {
        "entity_id": "response.data.list[0].id",
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
        "entity_id": "response.data[0].id",
    },
    "WechatReplyController_getList": {
        "entity_id": "response.data.list[0].id",
    },
    "WechatReplyController_info": {
        "entity_id": "response.data.id",
    },
    "PageDiyController_save": {
        "entity_id": "response.data.id",
    },
    # P1 后端 save 直接返回 data=主键 id，不再 list 回填
    "UserGroupController_save": {"entity_id": "response.data"},
    "UserTagController_save": {"entity_id": "response.data"},
    "SystemAdminController_save": {"entity_id": "response.data", "id": "response.data"},
    "SystemStoreController_save": {"entity_id": "response.data"},
    "SystemAttachmentController_save": {"entity_id": "response.data"},
    "SystemGroupController_save": {"entity_id": "response.data"},
}

# 后端已修复 save 返回主键；不再执行 list 回填
SAVE_DIRECT_ID_OPS = frozenset(
    {
        "UserGroupController_save",
        "UserTagController_save",
        "SystemAdminController_save",
        "SystemStoreController_save",
        "SystemAttachmentController_save",
        "SystemGroupController_save",
    }
)

OP_ENTITY_CONTEXT_KEY: Dict[str, str] = {
    "StoreProductRuleController": "product_rule_id",
    "StoreCouponController": "coupon_id",
    "ActivityStyleController": "activity_style_id",
    "ArticleController": "article_id",
    "UserController": "user_uid",
    "UserGroupController": "user_group_id",
    "UserTagController": "user_tag_id",
    "SystemAdminController": "admin_id",
    "SystemStoreController": "store_id",
    "SystemAttachmentController": "attachment_id",
    "SystemFormTempController": "form_id",
    "SystemMenuController": "latest_menu_id",
    "SystemUserLevelController": "user_level_id",
}


def is_valid_entity_id(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        return value.isdigit()
    return False


@dataclass
class PreparedStepRequest:
    url: str
    headers: Dict[str, Any]
    data: Optional[Dict[str, Any]]
    content_type: str


class ScenarioRequestPreparer:
    """将 CSV 步骤 + 上下文转换为可发送的 HTTP 请求（只读 context，不查库）。"""

    def __init__(self, api_client: ApiClient):
        self.client = api_client

    def prepare(self, step: Dict[str, Any], context: Dict[str, Any]) -> PreparedStepRequest:
        self._ensure_entity_id_for_step(step, context)

        raw_url = step.get("url", "")
        url = clean_url(VarRender.render_params(raw_url, context))
        url = restore_url_params(url, raw_url, context)
        headers = _parse_json(
            VarRender.render_params(step.get("headers", "{}"), context), {}
        )
        req_data = _sanitize_payload(
            _parse_json(
                VarRender.render_params(step.get("request_data", "{}"), context),
                {},
            )
        )
        var_bind = _parse_json(
            VarRender.render_params(step.get("var_bind", "{}"), context), {}
        )

        for key, value in var_bind.items():
            if _is_unresolved(value):
                if key == "id" and is_valid_entity_id(context.get("entity_id")):
                    value = context["entity_id"]
                elif key == "ids" and is_valid_entity_id(context.get("entity_id")):
                    value = context.get("ids") or context["entity_id"]
                else:
                    continue
            url, headers, req_data = bind_var_to_request(
                step, key, value, url, headers, req_data, context
            )

        req_data, url = enrich_request(
            step,
            req_data,
            url,
            context=context,
            api_client=self.client,
        )

        op_id = step.get("operation_id", "")
        if op_id == "SystemNotificationController_info":
            if "detailType=" not in url:
                url = f"{url}&detailType=wechat" if "?" in url else f"{url}?detailType=wechat"
        if op_id == "PageDiyController_save":
            req_data["isDel"] = 0

        content_type = resolve_content_type(step)
        token = context.get("token") or context.get("COMMON_TOKEN")
        if token and "Authori-zation" not in headers and "Authorization" not in headers:
            if op_id != "AdminLoginController_SystemAdminLogin":
                headers["Authori-zation"] = token

        return PreparedStepRequest(
            url=url,
            headers=headers,
            data=req_data if req_data else None,
            content_type=content_type,
        )

    def apply_response(self, step: Dict[str, Any], context: Dict[str, Any], resp) -> None:
        op_id = step.get("operation_id", "")
        # 新版后端 save 直接返回 data=id；旧版仍走 list 回填
        self._apply_save_id_from_response(step, context, resp)
        self._backfill_entity_after_save(step, context, resp)
        self._extract_variables(resp, step, context)
        if op_id.endswith("_save"):
            try:
                save_body = resp.json()
            except Exception:
                save_body = {}
            if save_body.get("code") == 200 and is_valid_entity_id(context.get("entity_id")):
                context["_entity_locked"] = True
                context["_scenario_saved_entity_id"] = context["entity_id"]
        if op_id == "StoreSeckillMangerController_save":
            try:
                body = resp.json()
            except Exception:
                return
            if body.get("code") != 200:
                return
            time_range = context.get("_last_seckill_time")
            eid = context.get("entity_id")
            if time_range:
                from utils.context_data import ctx_mark_seckill_hour

                ctx_mark_seckill_hour(str(time_range))
            if is_valid_entity_id(eid) and time_range:
                time_map = dict(context.get("_seckill_time_by_id") or {})
                time_map[str(eid)] = str(time_range)
                context["_seckill_time_by_id"] = time_map

    def _apply_save_id_from_response(
        self, step: Dict[str, Any], context: Dict[str, Any], resp
    ) -> None:
        """save 成功且 response.data 为数字 id 时直接写入 entity_id（部署 P1 修复后）。"""
        op_id = step.get("operation_id", "")
        if not op_id.endswith("_save"):
            return
        try:
            body = resp.json()
        except Exception:
            return
        if body.get("code") != 200:
            return
        data = body.get("data")
        if not is_valid_entity_id(data):
            return
        context["entity_id"] = data
        context["_entity_locked"] = True
        context["_scenario_saved_entity_id"] = data
        for prefix, ctx_key in OP_ENTITY_CONTEXT_KEY.items():
            if op_id.startswith(prefix):
                context[ctx_key] = data
                break
        module = str(step.get("module", "")).lower()
        mod_key = MODULE_ENTITY_KEY.get(module)
        if mod_key:
            context[mod_key] = data
        if op_id == "SystemAttachmentController_save":
            context["attId"] = data
            context["ids"] = str(data)
        logger.info(f"save 响应 data 即主键 entity_id={data} (op={op_id})")

    def _backfill_id_from_last_pages(
        self,
        *,
        list_path: str,
        headers: Dict[str, Any],
        match_field: str,
        match_value: str,
        context: Dict[str, Any],
        entity_key: str = "",
        limit: int = 50,
        tail_pages: int = 8,
    ) -> bool:
        """无搜索条件的 list：从末页向前匹配（新记录 id 最大，通常在最后一页）。"""
        first_resp = self.client.request(
            method="GET",
            url=f"{list_path}?page=1&limit={limit}",
            headers=headers,
            data=None,
            content_type="json",
        )
        payload = first_resp.json().get("data") or {}
        total_page = int(payload.get("totalPage") or 1)
        start_page = max(1, total_page - tail_pages + 1)
        for page in range(total_page, start_page - 1, -1):
            if page == 1 and total_page == 1:
                items = payload.get("list") or []
            else:
                list_resp = self.client.request(
                    method="GET",
                    url=f"{list_path}?page={page}&limit={limit}",
                    headers=headers,
                    data=None,
                    content_type="json",
                )
                items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get(match_field) == match_value:
                    eid = item.get("id")
                    context["entity_id"] = eid
                    if entity_key:
                        context[entity_key] = eid
                    context["_entity_locked"] = True
                    return True
        return False

    def _backfill_entity_after_save(
        self, step: Dict[str, Any], context: Dict[str, Any], resp
    ) -> None:
        if not step.get("operation_id", "").endswith("_save"):
            return
        try:
            body = resp.json()
        except Exception:
            body = {}
        if body.get("code") != 200:
            return
        if context.get("_entity_locked") and is_valid_entity_id(context.get("entity_id")):
            return
        token = context.get("token") or context.get("COMMON_TOKEN", "")
        if not token:
            return
        op_id = step.get("operation_id", "")
        if op_id in SAVE_DIRECT_ID_OPS:
            return
        headers = {"Authori-zation": token}

        if op_id == "StoreSeckillMangerController_save":
            name = context.get("_last_seckill_manger_name", "")
            if not name:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/store/seckill/manger/list?name={name}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get("name") == name:
                    context["entity_id"] = item.get("id")
                    context["seckill_time_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "CategoryController_save":
            name = context.get("_last_category_name", "")
            if not name:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/category/list?status=-1&type=1&name={name}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            data = list_resp.json().get("data")
            items = data if isinstance(data, list) else (data or {}).get("list") or []
            if items:
                context["entity_id"] = items[0].get("id")
                context["_entity_locked"] = True
            return

        if op_id == "ShippingTemplatesController_save":
            name = context.get("_last_shipping_template_name", "")
            if not name:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/express/shipping/templates/list?keywords={name}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            if items:
                context["entity_id"] = items[0].get("id")
                context["_entity_locked"] = True
            return

        if op_id == "StoreProductRuleController_save":
            rule_name = context.get("_last_rule_name", "")
            if not rule_name:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/store/product/rule/list?keywords={rule_name}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get("ruleName") == rule_name:
                    context["entity_id"] = item.get("id")
                    context["product_rule_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "ActivityStyleController_save":
            style_name = context.get("_last_activity_style_name", "")
            if not style_name:
                return
            style_type = context.get("_last_activity_style_type", 1)
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/activitystyle/list?name={style_name}&type={style_type}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get("name") == style_name:
                    context["entity_id"] = item.get("id")
                    context["activity_style_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "ArticleController_save":
            article_title = context.get("_last_article_title", "")
            if not article_title:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/article/list?keywords={article_title}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get("title") == article_title:
                    context["entity_id"] = item.get("id")
                    context["article_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "StoreCouponController_save":
            coupon_name = context.get("_last_coupon_name", "")
            if not coupon_name:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/marketing/coupon/list?name={coupon_name}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get("name") == coupon_name:
                    context["entity_id"] = item.get("id")
                    context["coupon_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "StoreProductController_save":
            name = context.get("_last_product_name", "")
            if not name:
                return
            for list_type in (2, 1):
                list_resp = self.client.request(
                    method="GET",
                    url=f"/api/admin/store/product/list?type={list_type}&keywords={name}&page=1&limit=5",
                    headers=headers,
                    data=None,
                    content_type="json",
                )
                items = (list_resp.json().get("data") or {}).get("list") or []
                for item in items:
                    if item.get("storeName") == name:
                        context["entity_id"] = item.get("id")
                        context["_entity_locked"] = True
                        return
            return

        if op_id == "SystemRoleController_save":
            role_name = context.get("_last_role_name", "")
            if not role_name:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/system/role/list?keywords={role_name}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            if items:
                context["entity_id"] = items[0].get("id")
                context["_entity_locked"] = True
            return

        if op_id == "SystemFormTempController_save":
            fname = context.get("_last_form_temp_name", "")
            if not fname:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/system/form/temp/list?keywords={fname}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if item.get("name") == fname:
                    context["entity_id"] = item.get("id")
                    context["form_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "StoreBargainController_save":
            title = context.get("_last_bargain_title", "")
            store_name = context.get("_last_bargain_store_name", "")
            keyword = title or store_name
            if not keyword:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/store/bargain/list?keywords={keyword}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if title and item.get("title") == title:
                    context["entity_id"] = item.get("id")
                    context["bargain_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
                if store_name and item.get("storeName") == store_name:
                    context["entity_id"] = item.get("id")
                    context["bargain_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "StoreCombinationController_save":
            title = context.get("_last_combination_title", "")
            store_name = context.get("_last_combination_store_name", "")
            keyword = title or store_name
            if not keyword:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/store/combination/list?keywords={keyword}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if title and item.get("title") == title:
                    context["entity_id"] = item.get("id")
                    context["combination_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
                if store_name and item.get("storeName") == store_name:
                    context["entity_id"] = item.get("id")
                    context["combination_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "StoreSeckillController_save":
            title = context.get("_last_seckill_title", "")
            store_name = context.get("_last_seckill_store_name", "")
            keyword = title or store_name
            if not keyword:
                return
            list_resp = self.client.request(
                method="GET",
                url=f"/api/admin/store/seckill/list?keywords={keyword}&page=1&limit=5",
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if title and item.get("title") == title:
                    context["entity_id"] = item.get("id")
                    context["seckill_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
                if store_name and item.get("storeName") == store_name:
                    context["entity_id"] = item.get("id")
                    context["seckill_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            return

        if op_id == "SystemStoreStaffController_save":
            store_id = context.get("store_id") or context.get("storeId") or ""
            staff_name = context.get("_last_staff_name", "")
            if not staff_name and not store_id:
                return
            list_url = f"/api/admin/system/store/staff/list?storeId={store_id}&page=1&limit=20"
            list_resp = self.client.request(
                method="GET",
                url=list_url,
                headers=headers,
                data=None,
                content_type="json",
            )
            items = (list_resp.json().get("data") or {}).get("list") or []
            for item in items:
                if staff_name and item.get("staffName") == staff_name:
                    context["entity_id"] = item.get("id")
                    context["latest_staff_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            if items:
                context["entity_id"] = items[-1].get("id")
                context["latest_staff_id"] = items[-1].get("id")
                context["_entity_locked"] = True
            return

        if op_id == "SystemUserLevelController_save":
            level_name = context.get("_last_user_level_name", "")
            if not level_name:
                return
            list_resp = self.client.request(
                method="GET",
                url="/api/admin/system/user/level/list",
                headers=headers,
                data=None,
                content_type="json",
            )
            data_block = list_resp.json().get("data")
            items = data_block if isinstance(data_block, list) else (data_block or {}).get("list") or []
            for item in items:
                if item.get("name") == level_name:
                    context["entity_id"] = item.get("id")
                    context["user_level_id"] = item.get("id")
                    context["_entity_locked"] = True
                    return
            if items:
                context["entity_id"] = items[0].get("id")
                context["user_level_id"] = items[0].get("id")
                context["_entity_locked"] = True

    def _step_needs_entity_id(self, step: Dict[str, Any]) -> bool:
        op_id = step.get("operation_id", "")
        if op_id.endswith("_save"):
            return False
        raw_url = step.get("url", "")
        if "${entity_id}" in raw_url or "${ids}" in raw_url:
            return True
        var_bind = step.get("var_bind", "")
        if "${entity_id}" in var_bind or "${ids}" in var_bind:
            return True
        if "${entity_id}" in step.get("request_data", ""):
            return True
        if op_id.endswith(("_info", "_delete", "_update", "_recovery")):
            return True
        if "/status" in step.get("url", "").lower() or op_id.endswith("_updateStatus"):
            return True
        if any(
            op_id.endswith(suffix)
            for suffix in (
                "_updateStatus",
                "_completeLyDelete",
                "_putOn",
                "_offShell",
                "_putOnShell",
            )
        ):
            return True
        return False

    def _resolve_entity_id(self, step: Dict[str, Any], context: Dict[str, Any]) -> None:
        op_id = step.get("operation_id", "")
        if is_valid_entity_id(context.get("entity_id")):
            return
        saved = context.get("_scenario_saved_entity_id")
        if is_valid_entity_id(saved):
            context["entity_id"] = saved
            logger.info(f"恢复场景 save 主键 entity_id={saved} (op={op_id})")
            return
        if context.get("_entity_locked") and is_valid_entity_id(context.get("entity_id")):
            return
        if op_id.endswith("_save"):
            return
        if not context.get("_preassigned_entity"):
            return
        for prefix, ctx_key in OP_ENTITY_CONTEXT_KEY.items():
            if op_id.startswith(prefix):
                val = ctx_get_from(context, ctx_key, "")
                if is_valid_entity_id(val):
                    context["entity_id"] = val
                    logger.info(f"上下文 entity_id={val} (op={op_id})")
                    return
        module = step.get("module", "").lower()
        ctx_key = MODULE_ENTITY_KEY.get(module)
        if ctx_key:
            val = ctx_get_from(context, ctx_key, "")
            if is_valid_entity_id(val):
                context["entity_id"] = val
                logger.info(f"上下文 entity_id={val} (module={module})")
                return
        logger.warning(
            f"无法从初始化上下文解析 entity_id (scenario={step.get('scenario_id')}, op={op_id})"
        )

    def _ensure_entity_id_for_step(
        self, step: Dict[str, Any], context: Dict[str, Any]
    ) -> None:
        if not self._step_needs_entity_id(step):
            return
        self._resolve_entity_id(step, context)
        eid = context.get("entity_id")
        if eid and "${ids}" in step.get("url", ""):
            context["ids"] = eid

    def _extract_variables(
        self, resp, step: Dict[str, Any], context: Dict[str, Any]
    ) -> None:
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
            if op_id.endswith("_save") and name in ("entity_id", "id"):
                paths.append("response.data")
            extracted = None
            for jp in paths:
                try:
                    extracted = extract_by_path(root, jp)
                    break
                except (KeyError, IndexError, TypeError):
                    continue
            if extracted is not None and extracted != "":
                if name == "entity_id" and not is_valid_entity_id(extracted):
                    continue
                if name == "entity_id" and (
                    is_valid_entity_id(context.get("entity_id"))
                    or (
                        op_id.endswith("_getList")
                        and is_valid_entity_id(context.get("_scenario_saved_entity_id"))
                    )
                ):
                    if not is_valid_entity_id(context.get("entity_id")):
                        saved = context.get("_scenario_saved_entity_id")
                        if is_valid_entity_id(saved):
                            context["entity_id"] = saved
                    continue
                context[name] = extracted
                if name in ("token", "COMMON_TOKEN"):
                    context["token"] = extracted
                    context["COMMON_TOKEN"] = extracted
                if name == "entity_id":
                    context.setdefault("jobId", extracted)
                logger.info(f"提取变量 {name}={extracted}")
                continue
            if name == "entity_id":
                if op_id.endswith("_save"):
                    logger.warning(f"var_extract 失败 {name} <- {json_path}（save 依赖 list 回填）")
                    continue
                if is_valid_entity_id(context.get("entity_id")):
                    continue
                for prefix, ctx_key in OP_ENTITY_CONTEXT_KEY.items():
                    if op_id.startswith(prefix):
                        val = ctx_get_from(context, ctx_key, "")
                        if is_valid_entity_id(val):
                            context[name] = val
                            logger.info(f"上下文回退 {name}={val} (op={op_id})")
                            continue
                        break
                scenario_mod = str(context.get("_scenario_module") or "").lower()
                ctx_key = MODULE_ENTITY_KEY.get(scenario_mod) or MODULE_ENTITY_KEY.get(
                    step.get("module", "").lower()
                )
                if ctx_key:
                    val = ctx_get_from(context, ctx_key, "")
                    if is_valid_entity_id(val):
                        context[name] = val
                        logger.info(f"上下文回退 {name}={val} (module={scenario_mod or step.get('module')})")
                        continue
                if op_id.endswith("_getList"):
                    logger.warning(
                        f"列表为空或路径无效，无法提取 entity_id <- {json_path}"
                    )
                else:
                    logger.warning(f"var_extract 失败 {name} <- {json_path}")
                continue
            logger.warning(f"var_extract 失败 {name} <- {json_path}")
