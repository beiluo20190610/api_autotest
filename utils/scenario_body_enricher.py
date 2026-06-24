"""按 operationId 补全关键请求字段（DB）与提交方式修正。"""
import json
import re
import uuid
from typing import Any, Dict, Optional

from utils.db_helper import CrmebDb
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
        "UserController_update",
        "UserExtractController_update",
        "SystemStoreStaffController_update",
        "UserGroupController_update",
        "UserTagController_update",
        "SystemAttachmentController_update",
        "SystemCityController_update",
        "SystemFormTempController_update",
        "SystemGroupDataController_update",
    }
)

# update 不走 query id（id 在 body 内）
BODY_ID_UPDATE_OPS = frozenset(
    {
        "ExpressController_update",
        "StoreProductController_save",
        "StoreProductController_update",
        "ScheduleJobController_update",
        "SystemNotificationController_update",
        "SystemMenuController_update",
        "WechatReplyController_update",
        "PageDiyController_update",
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
    """去掉仍含未解析占位符的 query 参数。"""
    if "?" not in url:
        return url
    base, qs = url.split("?", 1)
    kept = []
    for part in qs.split("&"):
        if not part or "${" in part:
            continue
        kept.append(part)
    return f"{base}?{'&'.join(kept)}" if kept else base


def _needs_query_id(op_id: str) -> bool:
    if op_id in BODY_ID_UPDATE_OPS or op_id in POST_QUERY_ID_OPS:
        return False
    lower = op_id.lower()
    return lower.endswith("_update") or lower.endswith("_updatename") or lower.endswith("_updatestatus")


def _mock_name() -> str:
    return f"auto_name_{MockData.run_id()}"


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

    # --- 通用：save 去掉 id；update/info 将 id 挪到 query ---
    if is_save:
        data.pop("id", None)

    if op_id in POST_QUERY_ID_OPS or _needs_query_id(op_id):
        entity_id = data.pop("id", None)
        if entity_id is None and context:
            entity_id = context.get("entity_id")
        path = _append_query_id(path, entity_id)

    data = strip_unresolved(data, drop_id_on_save=is_save)

    # --- 分类 / 文章 ---
    if op_id == "CategoryController_save":
        data["pid"] = str(CrmebDb.get_optional("category_parent_id", "0") or "0")
        data["type"] = "1"
        data["status"] = "1"

    if op_id in ("ArticleController_save", "ArticleController_update"):
        if not data.get("cid"):
            data["cid"] = int(CrmebDb.get_optional("article_cid", "0") or "0")
        _set_if_empty(data, "imageInput", CrmebDb.get_optional("article_cover_image", "/mock/cover.jpg"))
        _set_if_empty(data, "author", "autotest_author")
        _set_if_empty(data, "shareTitle", "autotest share")
        _set_if_empty(data, "shareSynopsis", "autotest share synopsis")
        _set_if_empty(data, "synopsis", "autotest synopsis")
        _set_if_empty(data, "content", "autotest content")

    # --- 商品 ---
    if op_id in ("StoreProductController_save", "StoreProductController_update") and api_client and context:
        from utils.scenario_product_helper import build_product_payload

        token = context.get("token") or context.get("COMMON_TOKEN", "")
        overrides = {
            "storeName": data.get("storeName") or f"auto_store_{MockData.run_id()}",
            "cateId": data.get("cateId") or CrmebDb.get_optional("cate_id", ""),
            "tempId": data.get("tempId") or CrmebDb.get_optional("temp_id", ""),
            "couponIds": data.get("couponIds", CrmebDb.get_optional("coupon_ids", "")),
        }
        if op_id.endswith("_update") and context.get("entity_id"):
            overrides["id"] = context["entity_id"]
        tpl = build_product_payload(api_client, token, overrides, is_save=op_id.endswith("_save"))
        if tpl:
            data = tpl
    elif op_id in ("StoreProductController_save", "StoreProductController_update"):
        data.setdefault("cateId", CrmebDb.get_optional("cate_id", ""))
        data.setdefault("tempId", CrmebDb.get_optional("temp_id", ""))
        data.setdefault("couponIds", CrmebDb.get_optional("coupon_ids", ""))

    # --- 运费模板 ---
    if op_id in ("ShippingTemplatesController_save", "ShippingTemplatesController_update"):
        data["appoint"] = 0
        data["type"] = data.get("type") or 1
        data["shippingTemplatesRegionRequestList"] = []
        data["shippingTemplatesFreeRequestList"] = []

    # --- 活动样式 ---
    if op_id in ("ActivityStyleController_save", "ActivityStyleController_update"):
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "starttime", "2026-01-01 00:00:00")
        _set_if_empty(data, "endtime", "2026-12-31 23:59:59")
        _set_if_empty(data, "style", "/mock/activity_style.png")
        data["method"] = data.get("method") if data.get("method") not in (None, "") else 0
        data["type"] = False
        data["status"] = True
        if data.get("products") in ([], None):
            data["products"] = ""

    # --- PageDiy ---
    if op_id == "PageDiyController_save":
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "title", f"auto_title_{MockData.run_id()}")
        data["value"] = data.get("value") if isinstance(data.get("value"), dict) else {}
        _set_if_empty(data, "defaultValue", "{}")
        _set_if_empty(data, "merId", int(CrmebDb.get_optional("mer_id", "0") or "0"))

    if op_id == "PageDiyController_update":
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = CrmebDb.get_optional("pagediy_id", "")
        data.clear()
        if eid:
            data["id"] = int(eid)
        data["name"] = _mock_name()

    # --- 快递 ---
    if op_id == "ExpressController_update":
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = CrmebDb.get_optional("express_id", "")
        if eid:
            data["id"] = int(eid)
        data["isShow"] = data.get("isShow", 1)

    # --- 优惠券详情 ---
    if op_id == "StoreCouponController_info":
        cid = context.get("entity_id") if context else None
        if not cid:
            cid = CrmebDb.get_optional("coupon_id", "")
        if cid:
            path = _append_query_id(path.split("?")[0], cid)

    # --- 商品规格 ---
    if op_id in ("StoreProductRuleController_save", "StoreProductRuleController_update"):
        _set_if_empty(data, "ruleName", _mock_name())
        tpl = CrmebDb.get_optional(
            "product_rule_value",
            json.dumps([{"title": "默认", "detail": ["规格1"]}], ensure_ascii=False),
        )
        _set_if_empty(data, "ruleValue", tpl)

    # --- 营销活动（砍价/拼团/秒杀）---
    if op_id in ACTIVITY_INFO_OPS and api_client and context:
        from utils.scenario_activity_helper import build_activity_payload

        token = context.get("token") or context.get("COMMON_TOKEN", "")
        overrides: Dict[str, Any] = {}
        if op_id.endswith("_save"):
            overrides["title"] = data.get("title") or f"auto_title_{MockData.run_id()}"
            overrides["storeName"] = data.get("storeName") or f"auto_store_{MockData.run_id()}"
        if "StoreSeckill" in op_id:
            overrides["timeId"] = int(
                data.get("timeId") or CrmebDb.get_optional("seckill_time_id", "0") or 0
            )
            overrides["startTime"] = "2030-01-01 00:00:00"
            overrides["stopTime"] = "2030-12-31 23:59:59"
        if "StoreBargain" in op_id:
            overrides["startTime"] = "2030-01-01 00:00:00"
            overrides["stopTime"] = "2030-12-31 23:59:59"
            overrides["num"] = 10
            overrides["bargainNum"] = 5
            overrides["peopleNum"] = 2
            overrides["unitName"] = "件"
            overrides["title"] = f"auto_bargain_{MockData.run_id()}"
            overrides["storeName"] = f"auto_store_{MockData.run_id()}"
        if "StoreCombination" in op_id:
            overrides["startTime"] = "2030-01-01 00:00:00"
            overrides["stopTime"] = "2030-12-31 23:59:59"
        tpl = build_activity_payload(api_client, token, op_id, overrides)
        if tpl:
            data = tpl
            if op_id.endswith("_update") and context.get("entity_id"):
                data["id"] = int(context["entity_id"])

    # --- 秒杀时段 ---
    if op_id in ("StoreSeckillMangerController_save", "StoreSeckillMangerController_update"):
        rid = MockData.run_id()[:4]
        _set_if_empty(data, "name", _mock_name())
        data["time"] = f"0{rid[0]}:00:00,0{rid[1]}:59:59"
        _set_if_empty(data, "img", "/mock/seckill.png")
        _set_if_empty(data, "silderImgs", "/mock/seckill_slider.png")
        data["status"] = "1"
        data["isDel"] = False

    # --- 系统管理员 ---
    if op_id in ("SystemAdminController_save", "SystemAdminController_update"):
        rid = MockData.run_id()
        data["account"] = f"u{rid}"[:18]
        data["realName"] = f"测试员{rid[:6]}"
        data["phone"] = f"138{rid[:8]}"[:11]
        data["roles"] = CrmebDb.get_optional("role_id", "1")
        data["status"] = True
        _set_if_empty(data, "pwd", context.get("LOGIN_PASS", "123456") if context else "123456")

    # --- 用户分组/标签 ---
    if op_id in ("UserGroupController_save", "UserGroupController_update"):
        data["groupName"] = f"grp_{uuid.uuid4().hex}"
        if op_id.endswith("_update"):
            eid = context.get("entity_id") if context else None
            if eid:
                path = _append_query_id(path.split("?")[0], eid)

    if op_id in ("UserTagController_save", "UserTagController_update"):
        data["name"] = f"tag_{uuid.uuid4().hex}"
        if op_id.endswith("_update"):
            eid = context.get("entity_id") if context else None
            if eid:
                path = _append_query_id(path.split("?")[0], eid)

    # --- 系统组合数据 / 表单 ---
    if op_id == "SystemGroupController_save":
        data["formId"] = int(CrmebDb.get_optional("form_id", "0") or "0")
        data.setdefault("name", _mock_name())

    if op_id == "SystemFormTempController_save":
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "info", "autotest form info")
        _set_if_empty(
            data,
            "content",
            CrmebDb.get_optional(
                "form_content",
                json.dumps(
                    [{"name": "field1", "title": "字段1", "type": "input"}],
                    ensure_ascii=False,
                ),
            ),
        )

    if op_id == "SystemFormTempController_update":
        fid = context.get("entity_id") if context else None
        if not fid:
            fid = CrmebDb.get_optional("form_id", "")
        if fid:
            path = _append_query_id(path.split("?")[0], fid)
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "info", "autotest form info")
        _set_if_empty(
            data,
            "content",
            CrmebDb.get_optional(
                "form_content",
                json.dumps(
                    [{"name": "field1", "title": "字段1", "type": "input"}],
                    ensure_ascii=False,
                ),
            ),
        )

    if op_id == "SystemGroupDataController_save":
        gid = CrmebDb.get_optional("system_group_id", "")
        data["gid"] = int(gid) if gid else 0
        fid = int(CrmebDb.get_optional("form_id", "0") or "0")
        data["form"] = {
            "id": fid,
            "sort": 1,
            "status": True,
            "fields": [{"name": "field1", "title": "字段1", "value": "autotest"}],
        }

    if op_id == "SystemGroupDataController_update":
        gid = CrmebDb.get_optional("system_group_id", "")
        data["gid"] = int(gid) if gid else 0
        fid = int(CrmebDb.get_optional("form_id", "0") or "0")
        data["form"] = {
            "id": fid,
            "sort": 1,
            "status": True,
            "fields": [{"name": "field1", "title": "字段1", "value": "autotest"}],
        }
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = CrmebDb.get_optional("group_data_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)

    # --- 城市 ---
    if op_id == "SystemCityController_update":
        cid = context.get("entity_id") if context else None
        if not cid:
            cid = CrmebDb.get_optional("city_id", "")
        if cid:
            path = _append_query_id(path.split("?")[0], cid)
        data.pop("id", None)
        data["parentId"] = int(CrmebDb.get_optional("city_parent_id", "0") or "0")

    # --- 菜单 ---
    if op_id == "SystemMenuController_update":
        mid = context.get("entity_id") if context else None
        if not mid:
            mid = CrmebDb.get_optional("menu_id", "")
        if mid:
            data["id"] = int(mid)
        _set_if_empty(data, "menuType", "C")
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "component", "autotest/index")
        data["sort"] = data.get("sort") if data.get("sort") not in (None, "") else 1
        data["isShow"] = True

    # --- 角色 ---
    if op_id in ("SystemRoleController_save", "SystemRoleController_update"):
        data["roleName"] = f"role_{MockData.run_id()}"
        _set_if_empty(data, "rules", CrmebDb.get_optional("role_rules", "1"))
        data["status"] = True

    # --- 会员等级 ---
    if op_id == "SystemUserLevelController_save":
        _set_if_empty(data, "name", _mock_name())
        data["experience"] = int(CrmebDb.get_optional("next_user_experience", "100") or "100")
        data["grade"] = int(CrmebDb.get_optional("next_user_grade", "99") or "99")
        data["discount"] = int(data.get("discount") or 100)
        _set_if_empty(data, "icon", "/mock/level_icon.png")
        data["isShow"] = True

    # --- 门店 ---
    if op_id in ("SystemStoreController_save", "SystemStoreController_update"):
        data["latitude"] = "39.904200"
        data["longitude"] = "116.407396"
        _set_if_empty(data, "address", "北京市东城区")
        _set_if_empty(data, "detailedAddress", "autotest detailed address")
        _set_if_empty(data, "phone", "13800138000")
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "image", CrmebDb.get_optional("article_cover_image", "/mock/store_logo.png"))
        _set_if_empty(data, "dayTime", "09:00-21:00")
        _set_if_empty(data, "validTime", "2030-01-01,2030-12-31")
        _set_if_empty(data, "introduction", "autotest store")

    # --- 门店店员 ---
    if op_id in ("SystemStoreStaffController_save", "SystemStoreStaffController_update"):
        data.setdefault("storeId", int(CrmebDb.get_optional("store_id", "0") or "0"))
        data.setdefault("uid", int(CrmebDb.get_optional("staff_uid", "0") or "0"))
        if op_id.endswith("_update"):
            sid = context.get("entity_id") if context else None
            if not sid:
                sid = CrmebDb.get_optional("staff_id", "")
            if sid:
                path = _append_query_id(path.split("?")[0], sid)

    # --- 附件 ---
    if op_id in ("SystemAttachmentController_save", "SystemAttachmentController_update"):
        att = CrmebDb.get_optional("attachment_id", "")
        cover = CrmebDb.get_optional("article_cover_image", "/mock/att.png")
        if att:
            data["attId"] = int(att)
        _set_if_empty(data, "name", _mock_name())
        _set_if_empty(data, "attDir", cover)
        _set_if_empty(data, "sattDir", cover)
        if op_id.endswith("_update"):
            eid = context.get("entity_id") if context else att
            if eid:
                path = _append_query_id(path.split("?")[0], eid)

    # --- 通知 ---
    if op_id == "SystemNotificationController_update":
        _set_if_empty(data, "detailType", "wechat")
        _set_if_empty(data, "tempId", CrmebDb.get_optional("temp_id", ""))
        if context and context.get("entity_id"):
            data["id"] = int(context["entity_id"])

    if op_id in ("WechatReplyController_save", "WechatReplyController_update"):
        data.pop("id", None)
        _set_if_empty(data, "keywords", f"kw_{MockData.run_id()}")
        if not data.get("type") or str(data.get("type")).isdigit():
            data["type"] = "text"
        _set_if_empty(data, "data", "autotest reply")
        data["status"] = True
        if op_id.endswith("_update"):
            wid = context.get("entity_id") if context else None
            if not wid:
                wid = CrmebDb.get_optional("wechat_reply_id", "")
            if wid:
                data["id"] = int(wid)

    # --- 用户修改 ---
    if op_id == "UserController_update":
        uid = context.get("entity_id") if context else None
        if not uid:
            uid = CrmebDb.get_optional("user_uid", "")
        if uid:
            data["uid"] = int(uid)
            path = _append_query_id(path.split("?")[0], uid)
        data.setdefault("groupId", int(CrmebDb.get_optional("user_group_id", "0") or "0"))
        data.setdefault("tagId", CrmebDb.get_optional("user_tag_id", ""))

    # --- 提现审核（列表可能为空，用库中记录）---
    if op_id == "UserExtractController_update":
        eid = context.get("entity_id") if context else None
        if not eid:
            eid = CrmebDb.get_optional("extract_id", "")
        if eid:
            path = _append_query_id(path.split("?")[0], eid)
        data.setdefault("extractStatus", 1)
        data.setdefault("failMsg", "")

    # --- 定时任务 ---
    if op_id == "ScheduleJobController_update":
        job_id = context.get("jobId") or (context.get("entity_id") if context else None)
        if not job_id:
            job_id = CrmebDb.get_optional("schedule_job_id", "")
        if job_id:
            row = CrmebDb.get_row(
                "SELECT job_id AS jobId, bean_name AS beanName, method_name AS methodName, "
                f"params, cron_expression AS cronExpression, remark "
                f"FROM eb_schedule_job WHERE job_id={int(job_id)} LIMIT 1"
            )
            if row:
                data.update(row)
            else:
                data["jobId"] = int(job_id)
                _set_if_empty(data, "beanName", "taskExecutor")
                _set_if_empty(data, "methodName", "run")
                _set_if_empty(data, "cronExpression", "0 0 2 * * ?")

    # --- 活动样式 / 营销类 save：去掉占位 id ---
    if is_save and op_id.endswith("Controller_save"):
        data.pop("id", None)

    # --- 空字符串列表字段转 [] ---
    for field in EMPTY_LIST_FIELDS:
        if field in data and data[field] in ("", None):
            data[field] = []

    return data, path
