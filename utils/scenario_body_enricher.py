"""按 operationId 补全关键请求字段（DB）与提交方式修正。"""
import json
import re
import uuid
from typing import Any, Dict, List, Optional

from utils.context_data import (
    bind_context,
    ctx_get,
    ctx_int,
    ctx_next_seckill_time_range,
    ctx_next_user_level_grade,
    ctx_mark_staff_uid,
    ctx_pop_staff_uid,
    ctx_resolve_entity_id,
    ctx_seckill_time_for,
)
from utils.form_temp_helper import default_form_temp_content
from utils.mock_data import MockData

_UNRESOLVED = re.compile(r"\$\{[^}]+\}")

# 无 @RequestBody，需 form-urlencoded
FORM_OPERATION_IDS = frozenset(
    {
        "CategoryController_save",
        "CategoryController_update",
        "SystemGroupController_save",
        "SystemGroupController_update",
        "UserExtractController_update",
        "SystemStoreStaffController_save",
        "SystemStoreStaffController_update",
        "SystemCityController_update",
    }
)

# POST 但 id 走 query（非 body）
POST_QUERY_ID_OPS = frozenset(
    {
        "StoreCouponController_info",
        "StoreCouponController_delete",
        "StoreCouponController_updateStatus",
        "UserController_update",
        "UserExtractController_update",
        "SystemStoreStaffController_update",
        "SystemStoreStaffController_updateStatus",
        "SystemStoreController_updateStatus",
        "UserGroupController_update",
        "UserTagController_update",
        "ArticleController_update",
        "SystemAttachmentController_update",
        "SystemCityController_update",
        "SystemCityController_updateStatus",
        "SystemFormTempController_update",
        "SystemGroupDataController_update",
        "ActivityStyleController_updateStatus",
        "StoreBargainController_updateStatus",
        "StoreSeckillController_updateStatus",
    }
)

# update 不走 query id（id 在 body 内）；/status 路径单独走 query
BODY_ID_UPDATE_OPS = frozenset(
    {
        "ExpressController_update",
        "StoreProductController_save",
        "StoreProductController_update",
        "StoreProductRuleController_update",
        "ScheduleJobController_update",
        "SystemNotificationController_update",
        "SystemMenuController_update",
        "PageDiyController_update",
        "ActivityStyleController_update",
        "SystemRoleController_update",
        "ArticleController_update",
        "StoreBargainController_update",
        "StoreCombinationController_update",
        "StoreSeckillController_update",
    }
)

# status 走 requestBody（非 query）
BODY_STATUS_OPS = frozenset(
    {
        "ActivityStyleController_updateStatus",
    }
)

# 需反序列化为 JSON 数组的字段（仅真正需要 List 的字段）
JSON_ARRAY_FIELDS = frozenset(
    {
        "attrs",
        "attr",
    }
)

# status 参数为 Integer 的接口（GET/POST query）
INTEGER_STATUS_OPS = frozenset(
    {
        "SystemStoreStaffController_updateStatus",
        "ActivityStyleController_updateStatus",
    }
)

EMPTY_LIST_FIELDS = frozenset(
    {
        "shippingTemplatesRegionRequestList",
        "shippingTemplatesFreeRequestList",
        "attrs",
        "attr",
        "attrValue",
    }
)

ACTIVITY_INFO_OPS = frozenset(
    {
        "StoreBargainController_save",
        "StoreBargainController_update",
        "StoreCombinationController_save",
        "StoreCombinationController_update",
        "StoreSeckillController_save",
        "StoreSeckillController_update",
    }
)


def resolve_content_type(step: Dict[str, Any]) -> str:
    op_id = step.get("operation_id", "")
    if op_id in FORM_OPERATION_IDS:
        return "form"
    return step.get("content_type", "json")


def _append_query_id(path: str, entity_id: Any) -> str:
    if entity_id is None or _is_unresolved(entity_id):
        return path
    base = path.split("?")[0]
    if "id=" in path:
        return path
    joiner = "&" if "?" in path else "?"
    return f"{base}{joiner}id={entity_id}"


def _is_unresolved(value: Any) -> bool:
    return isinstance(value, str) and bool(_UNRESOLVED.search(value))


def strip_unresolved(data: Any, *, drop_id_on_save: bool = False) -> Any:
    """移除或归零未解析的 ${...} 占位符。"""
    if isinstance(data, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in data.items():
            if _is_unresolved(value):
                if key.lower() in ("id", "entity_id") and drop_id_on_save:
                    continue
                if key.lower() in ("id", "entity_id", "cid", "pid", "cateid", "tempid", "uid"):
                    cleaned[key] = 0
                continue
            if isinstance(value, str) and value == "" and key in EMPTY_LIST_FIELDS:
                cleaned[key] = []
                continue
            cleaned[key] = strip_unresolved(value, drop_id_on_save=drop_id_on_save)
        return cleaned
    if isinstance(data, list):
        return [strip_unresolved(v, drop_id_on_save=drop_id_on_save) for v in data]
    return data


def clean_url(url: str) -> str:
    """去掉仍含未解析占位符的 query 参数；路径中的 ${entity_id} 也剥离。"""
    if "${" in url and "?" not in url:
        url = url.split("${", 1)[0].rstrip("/")
    if "?" not in url:
        return url
    base, qs = url.split("?", 1)
    kept = []
    for part in qs.split("&"):
        if not part or "${" in part:
            continue
        kept.append(part)
    return f"{base}?{'&'.join(kept)}" if kept else base


# 被 clean_url 剥离的 query 参数默认值
_URL_PARAM_DEFAULTS: Dict[str, Any] = {
    "page": "1",
    "limit": "10",
    "type": "1",
    "keywords": "auto",
}


def _parse_query(url: str) -> Dict[str, str]:
    if "?" not in url:
        return {}
    qs = url.split("?", 1)[1]
    out: Dict[str, str] = {}
    for part in qs.split("&"):
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k] = v
    return out


def _resolve_url_param_value(name: str, raw_value: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
    ctx = context or {}
    if raw_value in ("${entity_id}", "${ids}"):
        eid = ctx.get("entity_id")
        return str(eid) if eid is not None else None
    if raw_value == "${keywords}":
        kw = ctx.get("keywords")
        if kw:
            return str(kw)
        return ctx_get("wechat_reply_keywords", "auto")
    if raw_value.startswith("${") and raw_value.endswith("}"):
        key = raw_value[2:-1]
        if key in ctx and ctx[key] is not None:
            return str(ctx[key])
        if key in _URL_PARAM_DEFAULTS:
            return str(_URL_PARAM_DEFAULTS[key])
        return str(_URL_PARAM_DEFAULTS.get(name, "auto"))
    return None


def restore_url_params(url: str, raw_url: str, context: Optional[Dict[str, Any]] = None) -> str:
    """clean_url 剥离未解析占位符后，按原始 URL 意图补回 query 参数。"""
    ctx = context or {}
    raw_qs = _parse_query(raw_url)
    if not raw_qs:
        return url
    current_qs = _parse_query(url)
    base = url.split("?")[0]
    merged = dict(current_qs)
    for name, raw_value in raw_qs.items():
        if name in merged:
            continue
        if "${" not in raw_value:
            merged[name] = raw_value
            continue
        resolved = _resolve_url_param_value(name, raw_value, ctx)
        if resolved is not None:
            merged[name] = resolved
        elif name in _URL_PARAM_DEFAULTS:
            merged[name] = str(_URL_PARAM_DEFAULTS[name])
        elif name.lower() in ("id", "entity_id", "ids"):
            eid = ctx.get("entity_id")
            if eid is not None:
                merged[name] = str(eid)
    if not merged:
        return base
    query = "&".join(f"{k}={v}" for k, v in merged.items())
    return f"{base}?{query}"


def _needs_query_id(op_id: str, path: str = "") -> bool:
    path_l = (path or "").lower()
    if "/status" in path_l or op_id.endswith("_updateStatus"):
        return True
    if op_id.endswith("_delete") or "/delete" in path_l:
        return True
    if op_id in POST_QUERY_ID_OPS:
        return True
    if op_id in BODY_ID_UPDATE_OPS:
        return False
    if op_id == "WechatReplyController_update" and "/status" not in path_l:
        return False
    lower = op_id.lower()
    return lower.endswith("_update") or lower.endswith("_updatename")


def _resolve_entity_id_from_context(context: Optional[Dict[str, Any]]) -> Any:
    ctx = context or {}
    eid = ctx.get("entity_id") or ctx.get("id")
    if eid is not None and not _is_unresolved(eid):
        return eid
    return None


def _coerce_array_fields(data: Dict[str, Any]) -> None:
    for field in JSON_ARRAY_FIELDS:
        if field not in data:
            continue
        val = data[field]
        if val is None or val == "":
            data[field] = []
        elif isinstance(val, str):
            try:
                parsed = json.loads(val)
                data[field] = parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                if "," in val:
                    data[field] = [v.strip() for v in val.split(",") if v.strip()]
                else:
                    data[field] = [val]


def _handle_query_post_endpoint(
    path: str,
    data: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    module: str = "",
    op_id: str = "",
) -> tuple[str, Dict[str, Any]]:
    """POST /status、/delete 等 @RequestParam 接口：id/status 走 query。"""
    if op_id in BODY_STATUS_OPS:
        return path, data
    if op_id in ("StoreCombinationController_updateStatus", "StoreCouponController_updateStatus"):
        return path, data
    path_l = path.lower()
    if "/status" not in path_l and "/delete" not in path_l:
        return path, data
    eid = _resolve_entity_id_from_context(context)
    if eid is None and module:
        db_key = {
            "storecoupon": "coupon_id",
            "wechatreply": "wechat_reply_id",
            "product": "product_id",
            "article": "article_id",
            "category": "cate_id",
            "pagediy": "pagediy_id",
            "storebargain": "bargain_id",
            "storecombination": "combination_id",
            "storeseckill": "seckill_id",
        }.get(module.lower())
        if db_key:
            eid = ctx_get(db_key, "")
    if eid is None:
        eid = ctx_get("product_id", "")
    base = path.split("?")[0]
    path = _append_query_id(base, eid)
    if "/status" in path_l and "status=" not in path:
        op_id = (context or {}).get("_operation_id", "")
        status_val = "1" if op_id in INTEGER_STATUS_OPS else "true"
        path = f"{path}&status={status_val}" if "?" in path else f"{path}?status={status_val}"
    cleared = dict(data)
    cleared.clear()
    return path, cleared


def bind_var_to_request(
    step: Dict[str, Any],
    key: str,
    value: Any,
    url: str,
    headers: Dict[str, Any],
    req_data: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
    """将 var_bind 字段绑定到 headers / query / body。"""
    op_id = step.get("operation_id", "")
    method = step.get("method", "GET").upper()
    path = url.split("?")[0] if "?" in url else url

    if key.lower() in ("authori-zation", "authorization"):
        headers[key] = value
        return url, headers, req_data

    query_keys = {"id", "ids", "uid", "status"}
    use_query = (
        method == "GET"
        or _needs_query_id(op_id, path)
        or key in query_keys
        and (
            "/status" in path.lower()
            or "/delete" in path.lower()
            or op_id.endswith("_updateStatus")
            or op_id in POST_QUERY_ID_OPS
        )
    )
    if use_query and key.lower() in query_keys:
        if f"{key}=" not in url and f"{key.lower()}=" not in url.lower():
            joiner = "&" if "?" in url else "?"
            url = f"{url}{joiner}{key}={value}"
        return url, headers, req_data

    req_data[key] = value
    return url, headers, req_data


def _resolve_group_form_id(gid: int) -> int:
    if gid <= 0:
        return int(ctx_get("form_id", "0") or "0")
    return int(ctx_get("group_form_id", "0") or ctx_get("form_id", "0") or "0")


def _resolve_group_form_temp_id(gid: int) -> int:
    gfid = int(ctx_get("group_form_id", "0") or "0")
    if gfid > 0:
        return gfid
    return int(ctx_get("form_id", "0") or "0")


def _build_form_check_payload_for_gid(gid: int) -> Dict[str, Any]:
    """使用初始化阶段表单模板，避免运行时查库。"""
    fid = _resolve_group_form_temp_id(gid)
    return _build_form_check_payload(fid)


def _build_form_check_payload(form_temp_id: int) -> Dict[str, Any]:
    """根据表单模板 content 自动生成 fields（补齐全部 __vModel__ 字段）。"""
    fields: List[Dict[str, Any]] = []
    raw_content = ctx_get("form_temp_content", "") or default_form_temp_content()
    try:
        obj = json.loads(raw_content)
        for item in obj.get("fields", []):
            field_def = json.loads(item) if isinstance(item, str) else item
            if not isinstance(field_def, dict):
                continue
            vmodel = field_def.get("__vModel__") or field_def.get("name") or ""
            cfg = field_def.get("__config__") or {}
            label = cfg.get("label") or vmodel or "field"
            if not vmodel:
                continue
            value = "autotest"
            tag = cfg.get("tag") or ""
            if tag in ("el-input-number", "el-slider"):
                value = "1"
            elif tag == "el-switch":
                value = "true"
            fields.append({"name": vmodel, "title": str(label), "value": value})
    except Exception:
        pass
    if not fields:
        fields = [{"name": "field1", "title": "字段1", "value": "autotest"}]
    form_id = int(form_temp_id or _resolve_group_form_temp_id(0) or 0)
    return {"id": form_id, "sort": 1, "status": 1, "fields": fields}


def _pick_fresh_staff_uid() -> int:
    return ctx_pop_staff_uid()


def _unique_seckill_time_range(*, exclude_id: Optional[int] = None) -> str:
    return ctx_next_seckill_time_range(exclude_id=exclude_id)


def _seckill_time_from_db(entity_id: int) -> str:
    return ctx_seckill_time_for(entity_id)


def _mock_name() -> str:
    return f"auto_name_{MockData.run_id()}_{uuid.uuid4().hex[:8]}"


def _safe_int_id(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


def _resolve_pagediy_id(context: Optional[Dict[str, Any]]) -> Optional[int]:
    eid = _safe_int_id(_resolve_entity_id_from_context(context))
    if eid:
        return eid
    return _safe_int_id(ctx_get("pagediy_id", ""))


def _set_if_empty(data: Dict[str, Any], key: str, value: Any) -> None:
    if data.get(key) in (None, "", []):
        data[key] = value


def enrich_request(
    step: Dict[str, Any],
    req_data: Dict[str, Any],
    url: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    api_client: Any = None,
) -> tuple[Dict[str, Any], str]:
    op_id = step.get("operation_id", "")
    is_save = op_id.endswith("_save")
    data = dict(req_data or {})
    path = clean_url(url)
    ctx = bind_context(dict(context or {}))
    ctx["_operation_id"] = op_id

    path, data = _handle_query_post_endpoint(
        path, data, ctx, step.get("module", ""), op_id
    )

    # --- 通用：save 去掉 id；update/info 将 id 挪到 query ---
    if is_save:
        data.pop("id", None)

    if op_id in POST_QUERY_ID_OPS or _needs_query_id(op_id, path):
        entity_id = data.pop("id", None)
        if entity_id is None and context:
            entity_id = _resolve_entity_id_from_context(context)
        if entity_id is None:
            mod = step.get("module", "").lower()
            mod_db = {
                "product": "product_rule_id",
                "systemgroup": "auto_system_group_id",
                "systemstorestaff": "latest_staff_id",
                "storebargain": "bargain_id",
                "storecombination": "combination_id",
                "storeseckill": "seckill_id",
            }.get(mod, "product_id")
            entity_id = ctx_get(mod_db, "")
        path = _append_query_id(path, entity_id)

    data = strip_unresolved(data, drop_id_on_save=is_save)

    if op_id == "StoreCombinationController_updateStatus":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("combination_id", ""))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        base = path.split("?")[0]
        path = _append_query_id(base, eid) if eid else base
        if "?" in path:
            parts = [
                p
                for p in path.split("?", 1)[1].split("&")
                if not p.startswith("status=") and not p.startswith("isShow=")
            ]
            path = path.split("?", 1)[0] + ("?" + "&".join(parts) if parts else "")
        if "isShow=" not in path:
            path = f"{path}&isShow=true" if "?" in path else f"{path}?isShow=true"
        data.clear()
        return data, path

    if op_id == "StoreCouponController_updateStatus":
        cid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not cid:
            cid = _safe_int_id(ctx_get("coupon_id", ""))
        if not cid:
            cid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        base = "/api/admin/marketing/coupon/update/status"
        path = f"{base}?id={cid}&status=0" if cid else f"{base}?status=0"
        data.clear()
        return data, path

    if op_id == "StoreSeckillController_updateStatus":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("seckill_id", ""))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        base = path.split("?")[0]
        path = _append_query_id(base, eid) if eid else base
        if "?" in path:
            parts = [
                p
                for p in path.split("?", 1)[1].split("&")
                if not p.startswith("status=") and not p.startswith("isShow=")
            ]
            path = path.split("?", 1)[0] + ("?" + "&".join(parts) if parts else "")
        if "status=" not in path:
            path = f"{path}&status=true" if "?" in path else f"{path}?status=true"
        data.clear()
        return data, path

    if op_id == "StoreBargainController_updateStatus":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("bargain_id", ""))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        base = path.split("?")[0]
        path = _append_query_id(base, eid) if eid else base
        if "?" in path:
            parts = [
                p
                for p in path.split("?", 1)[1].split("&")
                if not p.startswith("status=") and not p.startswith("isShow=")
            ]
            path = path.split("?", 1)[0] + ("?" + "&".join(parts) if parts else "")
        if "status=" not in path:
            path = f"{path}&status=true" if "?" in path else f"{path}?status=true"
        data.clear()
        return data, path

    if op_id in ("ArticleController_info", "ArticleController_delete"):
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("article_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
        if op_id == "ArticleController_info":
            if eid:
                path = _append_query_id(path.split("?")[0], eid)
        else:
            if eid:
                path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id == "PageDiyController_info":
        eid = _resolve_pagediy_id(context)
        if eid and context is not None:
            context["entity_id"] = eid
            path = f"/api/admin/pagediy/info/{eid}"
        data.clear()
        return data, path

    if op_id in ("PageDiyController_delete", "PageDiyController_setDefault"):
        eid = _resolve_pagediy_id(context)
        if eid and context is not None:
            context["entity_id"] = eid
        if op_id == "PageDiyController_delete" and eid:
            path = _append_query_id("/api/admin/pagediy/delete", eid)
        if op_id == "PageDiyController_setDefault" and eid:
            path = f"/api/admin/pagediy/setdefault/{eid}"
        data.clear()
        return data, path

    if op_id == "SystemMenuController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("latest_menu_id", ""))
        if not eid:
            eid = _safe_int_id(ctx_get("menu_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = f"/api/admin/system/menu/info/{eid}"
        data.clear()
        return data, path

    if op_id in ("SystemUserLevelController_info", "SystemUserLevelController_delete"):
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("user_level_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
        base = path.split("?")[0]
        if op_id == "SystemUserLevelController_info" and eid:
            path = _append_query_id(base, eid)
        elif op_id == "SystemUserLevelController_delete" and eid:
            path = f"/api/admin/system/user/level/delete/{eid}"
        data.clear()
        return data, path

    if op_id == "StoreSeckillMangerController_updateStatus":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("seckill_time_id", ""))
        if eid:
            path = f"/api/admin/store/seckill/manger/update/status/{eid}?status=true"
        data.clear()
        return data, path

    if op_id == "SystemRoleController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("role_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = f"/api/admin/system/role/info/{eid}"
        data.clear()
        return data, path

    if op_id == "SystemAdminController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("admin_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id == "SystemStoreController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("store_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id == "SystemAttachmentController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("attachment_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            context["attId"] = eid
            path = f"/api/admin/system/attachment/info/{eid}"
        data.clear()
        return data, path

    if op_id == "SystemAttachmentController_delete":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("attachment_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            context["ids"] = str(eid)
            path = f"/api/admin/system/attachment/delete/{eid}"
        data.clear()
        return data, path

    if op_id == "SystemStoreStaffController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("staff_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
            try:
                if ctx_get("staff_uid", ""):
                    context["uid"] = ctx_get("staff_uid", "")
                if ctx_get("store_id", ""):
                    context["storeId"] = ctx_get("store_id", "")
            except Exception:
                pass
        data.clear()
        return data, path

    if op_id == "UserController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("user_uid", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            context["uid"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id in ("StoreProductRuleController_info", "StoreProductRuleController_delete"):
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid and not (context or {}).get("_entity_locked"):
            eid = _safe_int_id(ctx_get("latest_product_rule_id", ""))
        if not eid and not (context or {}).get("_entity_locked"):
            eid = _safe_int_id(ctx_get("product_rule_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            context["ids"] = str(eid)
        if op_id == "StoreProductRuleController_info" and eid:
            path = f"/api/admin/store/product/rule/info/{eid}"
        elif op_id == "StoreProductRuleController_delete" and eid:
            path = f"/api/admin/store/product/rule/delete/{eid}"
        data.clear()
        return data, path

    if op_id == "SystemGroupController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("auto_system_group_id", ""))
        if not eid:
            eid = _safe_int_id(ctx_get("latest_system_group_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id == "SystemStoreStaffController_updateStatus":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("latest_staff_id", ""))
        if eid:
            path = f"/api/admin/system/store/staff/update/status?id={eid}&status=1"
        data.clear()
        return data, path

    if op_id == "StoreSeckillMangerController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("seckill_time_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id in (
        "SystemNotificationController_routineSwitch",
        "SystemNotificationController_smsSwitch",
        "SystemNotificationController_wechatSwitch",
    ):
        db_key = {
            "SystemNotificationController_routineSwitch": "notification_routine_id",
            "SystemNotificationController_smsSwitch": "notification_sms_id",
            "SystemNotificationController_wechatSwitch": "notification_wechat_id",
        }[op_id]
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get(db_key, ""))
        if not eid:
            eid = _safe_int_id(ctx_get("notification_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            base = path.split("?")[0].split("${")[0].rstrip("/")
            path = f"{base}/{eid}"
        data.clear()
        return data, path

    if op_id == "SystemNotificationController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("notification_wechat_id", ""))
        if not eid:
            eid = _safe_int_id(ctx_get("notification_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        if "detailType=" not in path:
            path = f"{path}&detailType=wechat" if "?" in path else f"{path}?detailType=wechat"
        data.clear()
        return data, path

    if op_id == "UserGroupController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("user_group_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    if op_id == "UserTagController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("user_tag_id", ""))
        if eid and context is not None:
            context["entity_id"] = eid
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()
        return data, path

    # --- 分类 / 文章 ---
    if op_id == "CategoryController_save":
        data["pid"] = str(ctx_get("category_parent_id", "0") or "0")
        cname = _mock_name()
        data["name"] = cname
        if context is not None:
            context["_last_category_name"] = cname
        data["type"] = "1"
        data["status"] = "1"

    if op_id == "CategoryController_update":
        eid = _resolve_entity_id_from_context(context)
        if not eid:
            eid = ctx_get("cate_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
            data["id"] = int(eid)
        data["pid"] = str(ctx_get("category_parent_id", "0") or "0")
        data["name"] = _mock_name()
        data["type"] = "1"
        data["status"] = "1"

    if op_id == "CategoryController_delete":
        eid = _resolve_entity_id_from_context(context)
        if not eid:
            eid = ctx_get("cate_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()

    if op_id in ("ArticleController_save", "ArticleController_update"):
        article_title = data.get("title") or ctx.get("MOCK_TITLE") or f"auto_title_{MockData.run_id()}"
        data["title"] = article_title
        if op_id.endswith("_save") and context is not None:
            context["_last_article_title"] = article_title
        if not data.get("cid"):
            data["cid"] = int(ctx_get("article_cid", "0") or "0")
        _set_if_empty(data, "imageInput", ctx_get("article_cover_image", "/mock/cover.jpg"))
        _set_if_empty(data, "author", "autotest_author")
        _set_if_empty(data, "shareTitle", "autotest share")
        _set_if_empty(data, "shareSynopsis", "autotest share synopsis")
        _set_if_empty(data, "synopsis", "autotest synopsis")
        _set_if_empty(data, "content", "autotest content")
        if op_id.endswith("_update"):
            eid = _safe_int_id(_resolve_entity_id_from_context(context))
            if not eid:
                eid = _safe_int_id(ctx_get("article_id", ""))
            if eid:
                path = _append_query_id(path.split("?")[0], eid)
            data.pop("id", None)

    if op_id == "ArticleController_info":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("article_id", ""))
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()

    if op_id == "ArticleController_delete":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("article_id", ""))
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()

    # --- 商品 ---
    if op_id == "StoreProductController_update" and api_client and context:
        token = context.get("token") or context.get("COMMON_TOKEN", "")
        eid = context.get("entity_id")
        if token and eid:
            api_client.request(
                method="GET",
                url=f"/api/admin/store/product/offShell/{eid}",
                headers={"Authori-zation": token},
                data=None,
                content_type="json",
            )

    if op_id == "StoreProductController_quickAddStock" and api_client and context:
        token = context.get("token") or context.get("COMMON_TOKEN", "")
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if eid:
            data["id"] = eid
            if not data.get("attrValueList") or data.get("attrValueList") in ("", []):
                resp = api_client.request(
                    method="GET",
                    url=f"/api/admin/store/product/info/{eid}",
                    headers={"Authori-zation": token},
                    data=None,
                    content_type="json",
                )
                try:
                    prod = resp.json().get("data") or {}
                    av = prod.get("attrValue") or []
                    if isinstance(av, list) and av:
                        data["attrValueList"] = [
                            {
                                "id": item.get("id"),
                                "productId": eid,
                                "stock": int(item.get("stock") or 0) + 10,
                                "sales": item.get("sales", 0),
                                "price": item.get("price", 0),
                            }
                            for item in av
                            if isinstance(item, dict)
                        ]
                except Exception:
                    pass
            if not data.get("attrValueList"):
                data["attrValueList"] = [{"productId": eid, "stock": 100, "sales": 0, "price": 0.01}]

    if op_id == "StoreProductController_importProduct":
        data.clear()
        data["url"] = "https://example.com/autotest-product-mock"

    if op_id in ("StoreProductController_save", "StoreProductController_update") and api_client and context:
        from utils.scenario_product_helper import build_product_payload

        token = context.get("token") or context.get("COMMON_TOKEN", "")
        overrides = {
            "storeName": data.get("storeName") or f"auto_store_{MockData.run_id()}",
            "cateId": data.get("cateId") or ctx_get("cate_id", ""),
            "tempId": data.get("tempId") or ctx_get("temp_id", ""),
            "couponIds": data.get("couponIds", ctx_get("coupon_ids", "")),
        }
        if op_id.endswith("_update") and context.get("entity_id"):
            overrides["id"] = context["entity_id"]
        source_id = context.get("entity_id") if op_id.endswith("_update") else None
        tpl = build_product_payload(
            api_client,
            token,
            overrides,
            is_save=op_id.endswith("_save"),
            source_product_id=source_id,
            context=context,
        )
        if tpl:
            data = tpl
            if op_id.endswith("_save") and context is not None:
                context["_last_product_name"] = data.get("storeName") or overrides.get("storeName")
            if data.get("isSub") in (None, ""):
                data["isSub"] = False
            if data.get("isBenefit") in (None, ""):
                data["isBenefit"] = False
            if data.get("isBest") in (None, ""):
                data["isBest"] = False
            if data.get("isNew") in (None, ""):
                data["isNew"] = False
            if data.get("isGood") in (None, ""):
                data["isGood"] = False
            if data.get("isHot") in (None, ""):
                data["isHot"] = False
    elif op_id in ("StoreProductController_save", "StoreProductController_update"):
        from utils.scenario_product_helper import normalize_coupon_ids

        data.setdefault("cateId", ctx_get("cate_id", ""))
        data.setdefault("tempId", ctx_get("temp_id", ""))
        data.setdefault("couponIds", ctx_get("coupon_ids", ""))
        normalize_coupon_ids(data)

    # --- 运费模板 ---
    if op_id in ("ShippingTemplatesController_save", "ShippingTemplatesController_update"):
        if op_id.endswith("_save"):
            tname = _mock_name()
            data["name"] = tname
            if context is not None:
                context["_last_shipping_template_name"] = tname
        data["appoint"] = 0
        data["type"] = data.get("type") or 1
        data["sort"] = int(data.get("sort") or 1)
        data["shippingTemplatesRegionRequestList"] = []
        data["shippingTemplatesFreeRequestList"] = []
        if op_id.endswith("_update"):
            eid = _safe_int_id(_resolve_entity_id_from_context(context))
            if not eid:
                eid = _safe_int_id(ctx_get("shipping_template_id", ""))
            if eid:
                data["id"] = eid

    if op_id in ("ShippingTemplatesController_info", "ShippingTemplatesController_delete"):
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("shipping_template_id", ""))
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        if op_id == "ShippingTemplatesController_delete":
            data.clear()
        elif op_id == "ShippingTemplatesController_info":
            data.clear()

    # --- 活动样式 ---
    if op_id == "ActivityStyleController_getList":
        style_type = (context or {}).get("_last_activity_style_type")
        if style_type in (None, ""):
            style_type = 1
        if "type=" not in path.lower():
            joiner = "&" if "?" in path else "?"
            path = f"{path}{joiner}type={style_type}"

    if op_id in ("ActivityStyleController_save", "ActivityStyleController_update"):
        style_name = data.get("name") or _mock_name()
        data["name"] = style_name
        style_type = data.get("type")
        if style_type in (None, ""):
            style_type = 1
        data["type"] = style_type
        if op_id.endswith("_save") and context is not None:
            context["_last_activity_style_name"] = style_name
            context["_last_activity_style_type"] = style_type
        _set_if_empty(data, "name", style_name)
        _set_if_empty(data, "starttime", "2026-01-01 00:00:00")
        _set_if_empty(data, "endtime", "2026-12-31 23:59:59")
        _set_if_empty(data, "style", "/mock/activity_style.png")
        data["method"] = data.get("method") if data.get("method") not in (None, "") else 0
        data["type"] = data.get("type") if data.get("type") not in (None, "") else 0
        data["status"] = True
        if data.get("products") in ([], None):
            data["products"] = ""
        if op_id.endswith("_update"):
            eid = _resolve_entity_id_from_context(context)
            if not eid:
                eid = ctx_get("activity_style_id", "")
            if eid:
                data["id"] = int(eid)

    if op_id == "ActivityStyleController_updateStatus":
        eid = _resolve_entity_id_from_context(context)
        if not eid:
            eid = ctx_get("activity_style_id", "")
        data.clear()
        if eid:
            data["id"] = int(eid)
        data["status"] = True

    # --- PageDiy ---
    if op_id == "PageDiyController_save":
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "title", f"auto_title_{MockData.run_id()}")
        data["value"] = data.get("value") if isinstance(data.get("value"), dict) else {}
        _set_if_empty(data, "defaultValue", "{}")
        _set_if_empty(data, "merId", int(ctx_get("mer_id", "0") or "0"))

    if op_id == "PageDiyController_update":
        eid = _resolve_pagediy_id(context)
        data.clear()
        if eid:
            data["id"] = eid
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "title", f"auto_title_{MockData.run_id()}")
        data["value"] = data.get("value") if isinstance(data.get("value"), dict) else {}
        data["defaultValue"] = data.get("defaultValue") or "{}"
        data["isDel"] = 0

    # --- 快递 ---
    if op_id == "ExpressController_update":
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = ctx_get("express_id", "")
        if eid:
            data["id"] = int(eid)
        data["isShow"] = data.get("isShow", 1)

    # --- 优惠券 ---
    if op_id in (
        "StoreCouponController_save",
        "StoreCouponController_update",
    ):
        coupon_name = data.get("name") or _mock_name()
        data["name"] = coupon_name
        if op_id.endswith("_save") and context is not None:
            context["_last_coupon_name"] = coupon_name
        _set_if_empty(data, "name", coupon_name)
        data["money"] = float(data.get("money") or 10)
        data["minPrice"] = float(data.get("minPrice") or 0)
        data["total"] = int(data.get("total") or 100)
        data["useType"] = int(data.get("useType") or 1)
        data["isLimited"] = bool(data.get("isLimited", True))
        data["isForever"] = bool(data.get("isForever", True))
        data["isFixedTime"] = bool(data.get("isFixedTime", False))
        data["type"] = int(data.get("type") or 1)
        data["status"] = bool(data.get("status", True))
        data["sort"] = int(data.get("sort") or 1)
        data["day"] = int(data.get("day") or 0)
        if isinstance(data.get("couponIds"), str) and data["couponIds"]:
            data["couponIds"] = [int(x) for x in str(data["couponIds"]).split(",") if x.strip().isdigit()]

    if op_id in (
        "StoreCouponController_info",
        "StoreCouponController_delete",
    ):
        cid = _resolve_entity_id_from_context(context)
        if not cid:
            cid = ctx_get("coupon_id", "")
        if cid:
            path = _append_query_id(path.split("?")[0], cid)
        if op_id in ("StoreCouponController_info", "StoreCouponController_delete"):
            data.clear()

    # --- 商品规格 ---
    if op_id in ("StoreProductRuleController_save", "StoreProductRuleController_update"):
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if op_id.endswith("_save"):
            data.pop("id", None)
            rule_name = f"auto_rule_{uuid.uuid4().hex[:12]}"
            data["ruleName"] = rule_name
            if context is not None:
                context["_last_rule_name"] = rule_name
        if op_id.endswith("_update") and eid and api_client and context:
            token = context.get("token") or context.get("COMMON_TOKEN", "")
            if token:
                resp = api_client.request(
                    method="GET",
                    url=f"/api/admin/store/product/rule/info/{eid}",
                    headers={"Authori-zation": token},
                    data=None,
                    content_type="json",
                )
                try:
                    detail = resp.json().get("data") or {}
                    if detail.get("ruleValue"):
                        data["ruleValue"] = detail["ruleValue"]
                except Exception:
                    pass
            data["id"] = int(eid)
            data["ruleName"] = f"auto_rule_{uuid.uuid4().hex[:12]}"
            path = path.split("?")[0]
        elif op_id.endswith("_update") and eid:
            data["id"] = int(eid)
            data["ruleName"] = f"auto_rule_{uuid.uuid4().hex[:12]}"
            path = path.split("?")[0]
        if not data.get("ruleName"):
            data["ruleName"] = f"auto_rule_{uuid.uuid4().hex[:12]}"
        tpl = data.get("ruleValue")
        if isinstance(tpl, (list, dict)):
            data["ruleValue"] = json.dumps(tpl, ensure_ascii=False)
        elif not tpl:
            data["ruleValue"] = json.dumps(
                [{"value": "默认规格", "detail": ["规格1"]}],
                ensure_ascii=False,
            )

    # --- 营销活动（砍价/拼团/秒杀）---
    if op_id in ACTIVITY_INFO_OPS and api_client and context:
        from utils.scenario_activity_helper import build_activity_payload, build_bargain_activity_attrs
        from utils.scenario_product_helper import build_product_payload

        token = context.get("token") or context.get("COMMON_TOKEN", "")
        if op_id == "StoreSeckillController_update":
            eid = _safe_int_id(_resolve_entity_id_from_context(context))
            if eid and token:
                api_client.request(
                    method="POST",
                    url=f"/api/admin/store/seckill/update/status?id={eid}&status=false",
                    headers={"Authori-zation": token},
                    data={},
                    content_type="json",
                )
        overrides: Dict[str, Any] = {}
        if op_id.endswith("_save"):
            overrides["title"] = data.get("title") or f"auto_title_{MockData.run_id()}"
            overrides["storeName"] = data.get("storeName") or f"auto_store_{MockData.run_id()}"
        if "StoreSeckill" in op_id:
            overrides["timeId"] = int(
                data.get("timeId") or ctx_get("seckill_time_id", "0") or 0
            )
            overrides["productId"] = int(
                data.get("productId") or ctx_get("product_id", "0") or 0
            )
            overrides["startTime"] = "2030-01-01 00:00:00"
            overrides["stopTime"] = "2030-12-31 23:59:59"
            if op_id.endswith("_save"):
                overrides["title"] = f"auto_seckill_{MockData.run_id()}"
                overrides["storeName"] = f"auto_store_{MockData.run_id()}"
        if "StoreBargain" in op_id:
            overrides["startTime"] = "2030-01-01 00:00:00"
            overrides["stopTime"] = "2030-12-31 23:59:59"
            overrides["num"] = 10
            overrides["bargainNum"] = 5
            overrides["peopleNum"] = 2
            overrides["unitName"] = "件"
            overrides["title"] = f"auto_bargain_{MockData.run_id()}"
            overrides["storeName"] = f"auto_store_{MockData.run_id()}"
            overrides["productId"] = int(
                data.get("productId") or ctx_get("product_id", "0") or 0
            )
        if "StoreCombination" in op_id:
            overrides["startTime"] = "2030-01-01 00:00:00"
            overrides["stopTime"] = "2030-12-31 23:59:59"
            overrides["title"] = f"auto_combination_{MockData.run_id()}"
            overrides["storeName"] = f"auto_store_{MockData.run_id()}"
            overrides["productId"] = int(
                data.get("productId") or ctx_get("product_id", "0") or 0
            )
        from utils.scenario_activity_helper import build_minimal_activity_payload

        if op_id.endswith("_save"):
            tpl = build_minimal_activity_payload(op_id, overrides, context=context)
        else:
            tpl = build_activity_payload(api_client, token, op_id, overrides, context=context)
        if not tpl:
            tpl = build_minimal_activity_payload(op_id, overrides, context=context)
        if tpl:
            data = tpl
            if "StoreSeckill" in op_id and data.get("specType") in (None, ""):
                data["specType"] = False
            if "StoreBargain" in op_id and op_id.endswith("_save") and context is not None:
                context["_last_bargain_title"] = data.get("title") or ""
                context["_last_bargain_store_name"] = data.get("storeName") or ""
            if "StoreCombination" in op_id and op_id.endswith("_save") and context is not None:
                context["_last_combination_title"] = data.get("title") or ""
                context["_last_combination_store_name"] = data.get("storeName") or ""
            if "StoreSeckill" in op_id and "Manger" not in op_id and op_id.endswith("_save") and context is not None:
                context["_last_seckill_title"] = data.get("title") or ""
                context["_last_seckill_store_name"] = data.get("storeName") or ""
            if api_client and "StoreBargain" in op_id:
                pid = int(data.get("productId") or ctx_get("product_id", "0") or 0)
                if pid and not data.get("productId"):
                    data["productId"] = pid
                prod = build_product_payload(
                    api_client,
                    token,
                    {},
                    is_save=False,
                    source_product_id=pid or None,
                    context=context,
                )
                attrs, attr_values = build_bargain_activity_attrs(
                    prod,
                    product_id=int(data.get("productId") or prod.get("productId") or 0) or None,
                )
                data["attr"] = attrs
                data["attrValue"] = attr_values
                if not data.get("tempId"):
                    data["tempId"] = int(
                        prod.get("tempId") or ctx_get("temp_id", "0") or 0
                    )
                if data.get("status") in (None, "", 1, "1"):
                    data["status"] = True
                if not data.get("peopleNum") or int(data["peopleNum"]) < 2:
                    data["peopleNum"] = 2
                if data.get("content") is None:
                    data["content"] = ""
            if api_client and "StoreCombination" in op_id:
                pid = int(data.get("productId") or ctx_get("product_id", "0") or 0)
                if pid and not data.get("productId"):
                    data["productId"] = pid
                prod = build_product_payload(
                    api_client,
                    token,
                    {},
                    is_save=False,
                    source_product_id=pid or None,
                    context=context,
                )
                attrs, attr_values = build_bargain_activity_attrs(prod, product_id=pid or None)
                data["attr"] = attrs
                data["attrValue"] = attr_values
                if not data.get("tempId"):
                    data["tempId"] = int(prod.get("tempId") or ctx_get("temp_id", "0") or 0)
                if data.get("content") in (None, ""):
                    data["content"] = "autotest content"
            if api_client and "StoreSeckill" in op_id and "Manger" not in op_id:
                pid = int(data.get("productId") or ctx_get("product_id", "0") or 0)
                if pid and not data.get("productId"):
                    data["productId"] = pid
                prod = build_product_payload(
                    api_client,
                    token,
                    {},
                    is_save=False,
                    source_product_id=pid or None,
                    context=context,
                )
                attrs, attr_values = build_bargain_activity_attrs(prod, product_id=pid or None)
                data["attr"] = attrs
                data["attrValue"] = attr_values
                if not data.get("tempId"):
                    data["tempId"] = int(prod.get("tempId") or ctx_get("temp_id", "0") or 0)
                if not data.get("timeId"):
                    data["timeId"] = int(ctx_get("seckill_time_id", "0") or 0)
                if data.get("content") in (None, ""):
                    data["content"] = ""
            if op_id.endswith("_update"):
                eid = _safe_int_id(_resolve_entity_id_from_context(context))
                if not eid:
                    eid = _safe_int_id(context.get("_scenario_saved_entity_id") if context else None)
                if not eid and "StoreBargain" in op_id:
                    eid = _safe_int_id(ctx_get("bargain_id", ""))
                if not eid and "StoreCombination" in op_id:
                    eid = _safe_int_id(ctx_get("combination_id", ""))
                if not eid and "StoreSeckill" in op_id and "Manger" not in op_id:
                    eid = _safe_int_id(ctx_get("seckill_id", ""))
                if eid:
                    data["id"] = eid
                    if context is not None:
                        context["entity_id"] = eid
                if "StoreBargain" in op_id:
                    cover = data.get("image") or ctx_get("article_cover_image", "/mock/auto.png")
                    if isinstance(data.get("images"), list):
                        data["images"] = cover
                    elif not data.get("images"):
                        data["images"] = cover
                    if data.get("status") in (None, "", 1, "1"):
                        data["status"] = True
                if "StoreCombination" in op_id:
                    cover = data.get("image") or ctx_get("article_cover_image", "/mock/auto.png")
                    if isinstance(data.get("images"), list):
                        data["images"] = cover
                    elif not data.get("images"):
                        data["images"] = cover
                if "StoreSeckill" in op_id and "Manger" not in op_id and data.get("status") in (None, ""):
                    data["status"] = 1

    # --- 秒杀时段 ---
    if op_id in ("StoreSeckillMangerController_save", "StoreSeckillMangerController_update"):
        if op_id.endswith("_save"):
            data["name"] = _mock_name()
        else:
            _set_if_empty(data, "name", _mock_name())
        cover = ctx_get("article_cover_image", "/mock/seckill.png")
        _set_if_empty(data, "img", cover)
        _set_if_empty(data, "silderImgs", cover)
        data["status"] = "1"
        data["isDel"] = False
        data.pop("startTime", None)
        data.pop("stopTime", None)
        if op_id.endswith("_update"):
            eid = _safe_int_id(_resolve_entity_id_from_context(context))
            if not eid:
                eid = _safe_int_id(ctx_get("seckill_time_id", ""))
            if eid:
                path = _append_query_id(path.split("?")[0], eid)
                data["id"] = eid
                reserved = (context or {}).get("_reserved_seckill_time")
                data["time"] = reserved or _seckill_time_from_db(eid)
        else:
            preassigned = bool((context or {}).get("_preassigned_entity"))
            existing = _safe_int_id(_resolve_entity_id_from_context(context))
            if preassigned and existing and op_id.endswith("_save"):
                time_range = _unique_seckill_time_range()
            else:
                reserved = (context or {}).get("_reserved_seckill_time")
                time_range = reserved or _unique_seckill_time_range()
            data["time"] = time_range
            if context is not None:
                context["_last_seckill_time"] = time_range
            if op_id.endswith("_save"):
                data["name"] = _mock_name()
                if context is not None:
                    context["_last_seckill_manger_name"] = data["name"]

    # --- 系统管理员 ---
    if op_id == "SystemAdminController_save":
        account = f"u{uuid.uuid4().hex[:12]}"[:18]
        data["account"] = account
        if context is not None:
            context["_last_admin_account"] = account
        data["realName"] = data.get("realName") or f"测试员{MockData.run_id()[:6]}"
        data["phone"] = data.get("phone") or f"138{uuid.uuid4().int % 100000000:08d}"
        data["roles"] = data.get("roles") or ctx_get("role_id", "1")
        data["status"] = True
        _set_if_empty(data, "pwd", context.get("LOGIN_PASS", "123456") if context else "123456")

    if op_id == "SystemAdminController_update":
        saved_account = (context or {}).get("_last_admin_account")
        if saved_account:
            data["account"] = saved_account
        data["realName"] = data.get("realName") or f"测试员{MockData.run_id()[:6]}"
        data["phone"] = data.get("phone") or f"138{uuid.uuid4().int % 100000000:08d}"
        data["roles"] = data.get("roles") or ctx_get("role_id", "1")
        data["status"] = True
        _set_if_empty(data, "pwd", context.get("LOGIN_PASS", "123456") if context else "123456")
        if context and context.get("entity_id"):
            data["id"] = int(context["entity_id"])

    # --- 用户分组/标签 ---
    if op_id in ("UserGroupController_save", "UserGroupController_update"):
        gname = f"grp_{uuid.uuid4().hex}"
        data["groupName"] = gname
        if op_id.endswith("_update"):
            eid = _resolve_entity_id_from_context(context)
            if not eid:
                eid = ctx_get("user_group_id", "")
            if eid:
                path = _append_query_id(path.split("?")[0], eid)

    if op_id in ("UserGroupController_delete", "UserTagController_delete"):
        eid = _resolve_entity_id_from_context(context)
        mod_key = "user_group_id" if "Group" in op_id else "user_tag_id"
        if not eid:
            eid = ctx_get(mod_key, "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()

    if op_id in ("UserTagController_save", "UserTagController_update"):
        tname = f"tag_{uuid.uuid4().hex}"
        data["name"] = tname
        if op_id.endswith("_update"):
            eid = _resolve_entity_id_from_context(context)
            if not eid:
                eid = ctx_get("user_tag_id", "")
            if eid:
                path = _append_query_id(path.split("?")[0], eid)

    # --- 系统组合数据 / 表单 ---
    if op_id == "SystemGroupController_save":
        data["formId"] = int(ctx_get("form_id", "0") or "0")
        gname = _mock_name()
        data["name"] = gname
        data.setdefault("info", "autotest group")

    if op_id == "SystemGroupController_update":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("system_group_id", ""))
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data["formId"] = int(ctx_get("form_id", "0") or "0")
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "info", "autotest group")

    if op_id == "SystemGroupController_getList":
        path = path.split("?")[0]

    if op_id == "SystemGroupController_delete":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("latest_system_group_id", ""))
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()

    if op_id == "SystemFormTempController_save":
        fname = data.get("name") or _mock_name()
        data["name"] = fname
        if context is not None:
            context["_last_form_temp_name"] = fname
        _set_if_empty(data, "name", fname)
        _set_if_empty(data, "info", "autotest form info")
        if not data.get("content") or "__vModel__" not in str(data.get("content")):
            data["content"] = default_form_temp_content()

    if op_id == "SystemFormTempController_update":
        fid = context.get("entity_id") if context else None
        if not fid:
            fid = ctx_get("form_id", "")
        if fid:
            path = _append_query_id(path.split("?")[0], fid)
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "info", "autotest form info")
        if not data.get("content") or "__vModel__" not in str(data.get("content")):
            data["content"] = default_form_temp_content()

    if op_id == "SystemGroupDataController_save":
        gid = int(
            ctx_get("system_group_id", "0")
            or ctx_get("latest_system_group_id", "0")
            or ctx_get("auto_system_group_id", "0")
            or "0"
        )
        form_payload = _build_form_check_payload_for_gid(gid)
        resolved_gid = form_payload.pop("_resolved_gid", None)
        if resolved_gid:
            gid = int(resolved_gid)
        data["gid"] = gid
        data["form"] = form_payload

    if op_id == "SystemGroupDataController_update":
        gid = int(
            data.get("gid")
            or ctx_get("system_group_id", "0")
            or ctx_get("latest_system_group_id", "0")
            or ctx_get("auto_system_group_id", "0")
            or "0"
        )
        form_payload = _build_form_check_payload_for_gid(gid)
        resolved_gid = form_payload.pop("_resolved_gid", None)
        if resolved_gid:
            gid = int(resolved_gid)
        data["gid"] = gid
        data["form"] = form_payload
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = ctx_get("group_data_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
            try:
                data["form"]["id"] = int(
                    form_payload.get("id") or ctx_get("form_id", "0") or 0
                )
            except (TypeError, ValueError):
                pass

    # --- 城市 ---
    if op_id == "SystemCityController_getList":
        pid = ctx_get("city_parent_id", "0")
        if "parentId=" not in path:
            base = path.split("?")[0]
            joiner = "&" if "?" in path else "?"
            path = f"{base}{joiner}parentId={pid}"

    if op_id == "SystemCityController_update":
        cid = context.get("entity_id") if context else None
        if not cid:
            cid = ctx_get("city_id", "")
        if cid:
            path = _append_query_id(path.split("?")[0], cid)
        data.pop("id", None)
        parent = ctx_get("city_row_parent_id", "") or ctx_get("city_parent_id", "0")
        data["parentId"] = int(parent or 0)
        _set_if_empty(data, "name", _mock_name())

    if op_id == "SystemCityController_updateStatus":
        cid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not cid:
            cid = _safe_int_id(ctx_get("city_id", ""))
        if cid:
            path = f"/api/admin/system/city/update/status?id={cid}&status=true"
        data.clear()

    # --- 菜单 ---
    if op_id == "SystemMenuController_getList":
        base = path.split("?")[0]
        path = base

    if op_id == "SystemMenuController_add":
        data.pop("id", None)
        _set_if_empty(data, "menuType", "C")
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "icon", "/mock/menu.png")
        _set_if_empty(data, "component", "autotest/index")
        _set_if_empty(data, "perms", "autotest:demo:list")
        data["pid"] = 0
        data["sort"] = data.get("sort") if data.get("sort") not in (None, "") else 1
        data["isShow"] = True

    if op_id == "SystemMenuController_update":
        mid = context.get("entity_id") if context else None
        if not mid:
            mid = ctx_get("menu_id", "")
        if mid:
            data["id"] = int(mid)
        _set_if_empty(data, "menuType", "C")
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "component", "autotest/index")
        data["sort"] = data.get("sort") if data.get("sort") not in (None, "") else 1
        data["isShow"] = True

    # --- 角色 ---
    if op_id in ("SystemRoleController_save", "SystemRoleController_update"):
        role_name = f"role_{uuid.uuid4().hex[:12]}"
        data["roleName"] = role_name
        if op_id.endswith("_save") and context is not None:
            context["_last_role_name"] = role_name
        rules = data.get("rules")
        if isinstance(rules, list):
            data["rules"] = ",".join(str(x) for x in rules)
        _set_if_empty(data, "rules", ctx_get("role_rules", "1"))
        data["status"] = True
        if op_id.endswith("_update"):
            eid = _resolve_entity_id_from_context(context)
            if not eid:
                eid = ctx_get("role_id")
            if eid:
                data["id"] = int(eid)

    # --- 商品评论 ---
    if op_id in (
        "StoreProductReplyController_save",
        "StoreProductReplyController_comment",
    ):
        _set_if_empty(data, "comment", "autotest comment")
        _set_if_empty(data, "productId", int(ctx_get("product_id", "0") or "0"))
        _set_if_empty(data, "avatar", "/mock/avatar.png")
        _set_if_empty(data, "nickname", f"user_{MockData.run_id()}")
        if op_id.endswith("_comment") and context and context.get("entity_id"):
            data["id"] = int(context["entity_id"])

    # --- 会员等级 ---
    if op_id == "SystemUserLevelController_save":
        level_name = _mock_name()
        data["name"] = level_name
        grade, experience = ctx_next_user_level_grade()
        data["grade"] = grade
        data["experience"] = experience
        data.pop("id", None)
        data["discount"] = int(data.get("discount") or 100)
        _set_if_empty(data, "icon", "/mock/level_icon.png")
        data["isShow"] = True
        if context is not None:
            context["_last_user_level_name"] = level_name

    if op_id == "SystemUserLevelController_update":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = _safe_int_id(ctx_get("user_level_id", ""))
        if eid:
            path = f"/api/admin/system/user/level/update/{eid}"
            data["id"] = eid
        if api_client and context and eid:
            token = context.get("token") or context.get("COMMON_TOKEN", "")
            if token:
                list_resp = api_client.request(
                    method="GET",
                    url="/api/admin/system/user/level/list",
                    headers={"Authori-zation": token},
                    data=None,
                    content_type="json",
                )
                try:
                    data_block = list_resp.json().get("data")
                    items = (
                        data_block
                        if isinstance(data_block, list)
                        else (data_block or {}).get("list") or []
                    )
                    detail = next(
                        (item for item in items if int(item.get("id") or 0) == int(eid)),
                        {},
                    )
                    if detail.get("grade") is not None:
                        data["grade"] = int(detail["grade"])
                    if detail.get("experience") is not None:
                        data["experience"] = int(detail["experience"])
                except Exception:
                    pass
        data["name"] = _mock_name()
        if "grade" not in data or "experience" not in data:
            grade, experience = ctx_next_user_level_grade()
            data.setdefault("grade", grade)
            data.setdefault("experience", experience)
        else:
            data["grade"] = int(data["grade"])
            data["experience"] = int(data["experience"])
        data["discount"] = int(data.get("discount") or 100)
        _set_if_empty(data, "icon", "/mock/level_icon.png")
        data["isShow"] = True

    # --- 门店 ---
    if op_id == "SystemStoreController_getList":
        if "status=" not in path:
            path = f"{path}&status=1" if "?" in path else f"{path}?status=1"
        store_name = (context or {}).get("_last_store_name")
        if store_name and "keywords=" not in path:
            path = f"{path}&keywords={store_name}" if "?" in path else f"{path}?keywords={store_name}"

    if op_id in ("SystemStoreController_save", "SystemStoreController_update"):
        lng = str(data.get("longitude") or "116.407396")
        lat = str(data.get("latitude") or "39.904200")
        if "," not in lat:
            data["latitude"] = f"{lng},{lat}"
        data.pop("longitude", None)
        _set_if_empty(data, "address", "北京市东城区")
        _set_if_empty(data, "detailedAddress", "autotest detailed address")
        _set_if_empty(data, "phone", "13800138000")
        store_name = data.get("name") or _mock_name()
        data["name"] = store_name
        if op_id.endswith("_save") and context is not None:
            context["_last_store_name"] = store_name
        _set_if_empty(data, "image", ctx_get("article_cover_image", "/mock/store_logo.png"))
        _set_if_empty(data, "dayTime", "09:00-21:00")
        _set_if_empty(data, "validTime", "2030-01-01,2030-12-31")
        _set_if_empty(data, "introduction", "autotest store")
        if op_id.endswith("_save"):
            data["isShow"] = True
            data["isDel"] = False

    # --- 门店店员 ---
    if op_id in ("SystemStoreStaffController_save", "SystemStoreStaffController_update"):
        sid = _safe_int_id(_resolve_entity_id_from_context(context))
        store_id = int(
            (context or {}).get("store_id")
            or (context or {}).get("storeId")
            or ctx_get("store_id", "0")
            or 0
        )
        if sid and op_id.endswith("_update"):
            info_uid = _safe_int_id(ctx_get("staff_uid", "")) or _safe_int_id(
                (context or {}).get("_staff_uid")
            )
            if info_uid:
                data.setdefault("uid", info_uid)
            data.setdefault("storeId", store_id)
            data.setdefault("phone", f"138{uuid.uuid4().int % 100000000:08d}")
        data.setdefault("storeId", store_id)
        if op_id.endswith("_save"):
            uid = _pick_fresh_staff_uid()
            data["uid"] = uid
            if context is not None:
                context["uid"] = str(uid)
        elif not data.get("uid"):
            uid = _pick_fresh_staff_uid()
            data["uid"] = uid
            if context is not None:
                context["uid"] = str(uid)
        staff_name = data.get("staffName") or _mock_name()
        data["staffName"] = staff_name
        if context is not None and op_id.endswith("_save"):
            context["_last_staff_name"] = staff_name
        if not data.get("phone"):
            phone = f"138{uuid.uuid4().int % 100000000:08d}"
            data["phone"] = phone
            if context is not None and op_id.endswith("_save"):
                context["_last_staff_phone"] = phone
        if op_id.endswith("_update"):
            sid = context.get("entity_id") if context else None
            if not sid:
                sid = ctx_get("latest_staff_id", "")
            if sid:
                path = _append_query_id(path.split("?")[0], sid)

    # --- 附件 ---
    if op_id in ("SystemAttachmentController_save", "SystemAttachmentController_update"):
        cover = ctx_get("article_cover_image", "/mock/att.png")
        att_name = data.get("name") or _mock_name()
        data["name"] = att_name
        if op_id.endswith("_save"):
            data.pop("attId", None)
        _set_if_empty(data, "attType", "png")
        _set_if_empty(data, "attDir", cover)
        _set_if_empty(data, "sattDir", cover)
        if op_id.endswith("_update"):
            eid = context.get("entity_id") if context else None
            if not eid:
                eid = ctx_get("attachment_id", "")
            if eid:
                path = _append_query_id(path.split("?")[0], eid)

    # --- 通知 ---
    if op_id == "SystemNotificationController_update":
        eid = _safe_int_id(context.get("entity_id") if context else None)
        if not eid:
            eid = _safe_int_id(ctx_get("notification_wechat_id", ""))
        if eid:
            data["id"] = eid
        _set_if_empty(data, "detailType", "wechat")
        _set_if_empty(data, "tempId", ctx_get("wechat_template_temp_id", ""))
        if not data.get("tempId"):
            _set_if_empty(data, "tempId", ctx_get("temp_id", ""))
        data.setdefault("status", 1)

    if op_id in ("WechatReplyController_save", "WechatReplyController_update"):
        data.pop("id", None)
        kw = f"kw_{uuid.uuid4().hex[:12]}"
        data["keywords"] = kw
        if context is not None:
            context["keywords"] = kw
        if not data.get("type") or str(data.get("type")).isdigit():
            data["type"] = "text"
        _set_if_empty(data, "data", "autotest reply")
        data["status"] = True
        if op_id.endswith("_update") and "/status" not in path.lower():
            wid = _resolve_entity_id_from_context(context)
            if not wid:
                wid = ctx_get("wechat_reply_id", "")
            if wid:
                data["id"] = int(wid)

    if op_id == "WechatReplyController_update" and "/status" in path.lower():
        wid = _resolve_entity_id_from_context(context)
        if not wid and context:
            kw = context.get("keywords")
            if kw:
                wid = ctx_get("wechat_reply_id", "")
        if not wid:
            wid = ctx_get("wechat_reply_id", "")
        path = _append_query_id(path.split("?")[0], wid)
        if "status=" not in path:
            path = f"{path}&status=true" if "?" in path else f"{path}?status=true"
        data.clear()

    if op_id.endswith("_updateStatus") and op_id not in (
        "StoreCombinationController_updateStatus",
        "StoreBargainController_updateStatus",
        "StoreSeckillController_updateStatus",
        "StoreCouponController_updateStatus",
        "StoreSeckillMangerController_updateStatus",
    ):
        eid = _resolve_entity_id_from_context(context)
        if not eid:
            eid = ctx_get("product_id", "")
        path = _append_query_id(path.split("?")[0], eid)
        if "status=" not in path:
            status_val = "1" if op_id in INTEGER_STATUS_OPS else "true"
            path = f"{path}&status={status_val}" if "?" in path else f"{path}?status={status_val}"
        data.clear()

    if op_id == "WechatReplyController_info":
        kw = (context or {}).get("keywords")
        if not kw:
            kw = ctx_get("wechat_reply_keywords", "auto")
        path = "/api/admin/wechat/keywords/reply/info"
        path = f"{path}?keywords={kw}"

    if op_id == "WechatReplyController_delete":
        eid = _resolve_entity_id_from_context(context)
        if not eid and context:
            kw = context.get("keywords")
            if kw:
                eid = ctx_get("wechat_reply_id", "")
        if not eid:
            eid = ctx_get("wechat_reply_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.clear()

    # --- 用户修改 ---
    if op_id == "UserController_update":
        uid = context.get("entity_id") if context else None
        if not uid:
            uid = ctx_get("user_uid", "")
        if uid:
            data["uid"] = int(uid)
            path = _append_query_id(path.split("?")[0], uid)
        gid = _safe_int_id(data.get("groupId"))
        if gid is None and context:
            gid = _safe_int_id(context.get("groupId"))
        if gid is None:
            gid = _safe_int_id(ctx_get("user_group_id", "0"))
        data["groupId"] = gid if gid is not None else 0
        tag_raw = str(data.get("tagId", "") or (context or {}).get("tagId", "")).strip()
        if tag_raw and not all(p.strip().isdigit() for p in tag_raw.split(",") if p.strip()):
            tag_raw = str(ctx_get("user_tag_id", "") or "")
        data["tagId"] = tag_raw

    if op_id == "UserController_founds":
        uid = context.get("uid") if context else None
        if not uid:
            uid = context.get("entity_id") if context else None
        if not uid:
            uid = ctx_get("user_uid", "")
        if uid:
            base = path.split("?")[0]
            path = (
                f"{base}?uid={uid}&integralType=1&integralValue=1"
                f"&moneyType=1&moneyValue=0.01"
            )
        data.clear()

    if op_id == "UserController_updateUserLevel":
        uid = context.get("uid") if context else None
        if not uid:
            uid = context.get("entity_id") if context else None
        if not uid:
            uid = ctx_get("user_uid", "")
        if uid:
            data["uid"] = int(uid)
        current_level = (
            (context or {}).get("level")
            or (context or {}).get("levelId")
            or ctx_get("user_level_id", "")
        )
        level_id = (context or {}).get("levelId") or ctx_get("user_level_id", "") or ctx_get(
            "alt_user_level_id", ""
        )
        level_items: list = []
        if api_client and context:
            token = context.get("token") or context.get("COMMON_TOKEN")
            if token:
                try:
                    list_resp = api_client.request(
                        method="GET",
                        url="/api/admin/system/user/level/list",
                        headers={"Authori-zation": token},
                        data=None,
                        content_type="json",
                    )
                    data_block = list_resp.json().get("data")
                    level_items = (
                        data_block
                        if isinstance(data_block, list)
                        else (data_block or {}).get("list") or []
                    )
                except Exception:
                    level_items = []
        if level_items:
            picked = None
            alt = None
            for item in level_items:
                iid = item.get("id")
                if iid is None:
                    continue
                if str(iid) == str(current_level):
                    continue
                if alt is None:
                    alt = iid
                if level_id and str(iid) != str(level_id):
                    picked = iid
                    break
            level_id = picked or alt or level_id
        if level_id:
            data["levelId"] = int(level_id)
            if context is not None:
                context["levelId"] = data["levelId"]
        data.setdefault("isSub", 1)

    if op_id == "UserExtractController_getList":
        base = path.split("?")[0]
        if "?" in path:
            kept = []
            for part in path.split("?", 1)[1].split("&"):
                if part and not part.startswith("keywords="):
                    kept.append(part)
            path = f"{base}?{'&'.join(kept)}" if kept else base
        else:
            path = base

    # --- 提现审核（列表可能为空，用库中记录）---
    if op_id == "UserExtractController_update":
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = ctx_get("extract_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        _set_if_empty(data, "realName", _mock_name())
        _set_if_empty(data, "extractType", "bank")
        _set_if_empty(data, "bankName", "中国银行")
        _set_if_empty(data, "bankCode", "6217000000000000")
        data.setdefault("extractPrice", 1000)
        data.setdefault("extractStatus", 1)
        data.setdefault("failMsg", "")

    if op_id == "SystemConfigController_saveFrom":
        eid = _safe_int_id(_resolve_entity_id_from_context(context))
        if not eid:
            eid = int(ctx_get("form_id", "0") or "0") or None
        data.clear()
        if eid:
            data["id"] = eid
        data["sort"] = 1
        data["status"] = True
        data["fields"] = [{"name": "field1", "title": "字段1", "value": "autotest"}]

    # --- 定时任务 ---
    if op_id == "ScheduleJobController_update":
        job_id = context.get("jobId") or (context.get("entity_id") if context else None)
        if not job_id:
            job_id = ctx_get("schedule_job_id", "")
        if job_id:
            data["jobId"] = int(job_id)
            _set_if_empty(data, "beanName", "taskExecutor")
            _set_if_empty(data, "methodName", "run")
            _set_if_empty(data, "cronExpression", "0 0 2 * * ?")
            _set_if_empty(data, "params", "")
            _set_if_empty(data, "remark", "autotest job")

    # --- 活动样式 / 营销类 save：去掉占位 id ---
    if is_save and op_id.endswith("Controller_save"):
        data.pop("id", None)

    # --- 空字符串列表字段转 [] ---
    for field in EMPTY_LIST_FIELDS:
        if field in data and data[field] in ("", None):
            data[field] = []

    _coerce_array_fields(data)

    return data, path
