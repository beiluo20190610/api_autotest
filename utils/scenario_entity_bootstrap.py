"""初始化阶段：按场景批量插入业务数据，写入 scenario_assignments（执行阶段只读）。"""
from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.api_client import ApiClient
from core.logger import logger
from utils.context_data import MODULE_ENTITY_KEY
from utils.db_helper import CrmebDb
from utils.form_temp_helper import default_form_temp_content
from utils.mock_data import MockData
from utils.scenario_data import ScenarioDataHandler

# module -> (表名, 名称列, db_helper key)
_MODULE_TABLE: Dict[str, Tuple[str, str, str]] = {
    "article": ("eb_article", "title", "article_id"),
    "category": ("eb_category", "name", "cate_id"),
    "pagediy": ("eb_page_diy", "name", "pagediy_id"),
    "shippingtemplates": ("eb_shipping_templates", "name", "shipping_template_id"),
    "storebargain": ("eb_store_bargain", "title", "bargain_id"),
    "storecombination": ("eb_store_combination", "title", "combination_id"),
    "storeseckill": ("eb_store_seckill", "title", "seckill_id"),
    "storeseckillmanger": ("eb_store_seckill_manger", "name", "seckill_time_id"),
    "storecoupon": ("eb_store_coupon", "name", "coupon_id"),
    "product": ("eb_store_product", "store_name", "product_id"),
    "storeproductrule": ("eb_store_product_rule", "rule_name", "product_rule_id"),
    "systemadmin": ("eb_system_admin", "account", "admin_id"),
    "systemrole": ("eb_system_role", "role_name", "role_id"),
    "systemstore": ("eb_system_store", "name", "store_id"),
    "systemstorestaff": ("eb_system_store_staff", "staff_name", "latest_staff_id"),
    "systemgroup": ("eb_system_group", "name", "latest_system_group_id"),
    "systemgroupdata": ("eb_system_group_data", "id", "group_data_id"),
    "systemattachment": ("eb_system_attachment", "name", "attachment_id"),
    "systemcity": ("eb_system_city", "name", "city_id"),
    "systemformtemp": ("eb_system_form_temp", "name", "form_id"),
    "systemuserlevel": ("eb_system_user_level", "name", "user_level_id"),
    "usergroup": ("eb_user_group", "group_name", "user_group_id"),
    "usertag": ("eb_user_tag", "name", "user_tag_id"),
    "wechatreply": ("eb_wechat_reply", "keywords", "wechat_reply_id"),
    "activitystyle": ("eb_activity_style", "name", "activity_style_id"),
    "express": ("eb_express", "name", "express_id"),
    "systemmenu": ("eb_system_menu", "name", "menu_id"),
    "user": ("eb_user", "nickname", "user_uid"),
}


def _login(client: ApiClient) -> None:
    resp = client.request(
        method="POST",
        url="/api/admin/login",
        data={
            "account": os.getenv("LOGIN_USER", "admin"),
            "pwd": os.getenv("LOGIN_PASS", "123456"),
        },
        content_type="json",
    )
    token = (resp.json().get("data") or {}).get("token", "")
    if not token:
        raise RuntimeError(f"bootstrap 登录失败: {resp.text[:200]}")
    client.session.headers["Authori-zation"] = token


def _post(
    client: ApiClient,
    url: str,
    data: Dict[str, Any] | None = None,
    *,
    content_type: str = "json",
) -> Dict[str, Any]:
    resp = client.request(
        method="POST",
        url=url,
        headers={"Authori-zation": client.session.headers.get("Authori-zation", "")},
        data=data or {},
        content_type=content_type,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"code": resp.status_code, "text": resp.text[:200]}
    if body.get("code") != 200:
        msg = body.get("message") or body.get("msg") or body.get("text") or ""
        logger.warning(f"bootstrap POST {url} 失败: code={body.get('code')} msg={str(msg)[:120]}")
    return body


def _cover(ctx: Dict[str, Any]) -> str:
    return str(ctx.get("article_cover_image") or "/mock/cover.jpg")


def _purge_autotest_seckill_manger_records() -> None:
    """init 阶段清理自动化秒杀时段，释放小时槽位（避免 batch_ 记录占满 0–22 点）。"""
    try:
        conn = CrmebDb._connect()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM eb_store_seckill_manger "
                "WHERE name LIKE 'batch_storeseckillmanger_%' "
                "OR (name LIKE 'auto_%' AND name NOT LIKE 'seed_%')"
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning(f"purge seckill manger 失败: {exc}")


def _reload_seckill_occupied_hours(ctx: Dict[str, Any]) -> None:
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


def _batch_tag(module: str, index: int) -> str:
    return f"batch_{module}_{index}_{MockData.run_id()[:8]}"


def _id_column(table: str) -> str:
    if table == "eb_system_attachment":
        return "att_id"
    if table == "eb_user":
        return "uid"
    if table == "eb_schedule_job":
        return "job_id"
    return "id"


def _max_id(table: str, id_col: str) -> int:
    try:
        row = CrmebDb.get_row(f"SELECT MAX({id_col}) AS m FROM {table}")
        return int(row.get("m") or 0)
    except Exception:
        return 0


def _ids_after(table: str, id_col: str, after: int, limit: int) -> List[str]:
    conn = CrmebDb._connect()
    ids: List[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {id_col} AS eid FROM {table} WHERE {id_col} > %s "
                f"ORDER BY {id_col} ASC LIMIT %s",
                (after, limit),
            )
            for row in cur.fetchall() or []:
                val = row.get("eid")
                if val is not None:
                    ids.append(str(val))
    finally:
        conn.close()
    return ids


def _collect_batch_ids(
    module: str,
    n: int,
    worker: Callable[[int], None],
) -> List[str]:
    meta = _MODULE_TABLE.get(module)
    if not meta or n <= 0:
        return []
    table, _, _ = meta
    id_col = _id_column(table)
    base = _max_id(table, id_col)
    for i in range(n):
        try:
            worker(i)
        except Exception as exc:
            logger.warning(f"bootstrap {module}[{i}] 异常: {exc}")
    ids = _ids_after(table, id_col, base, n)
    if len(ids) < n:
        logger.warning(f"bootstrap {module} 仅拿到 {len(ids)}/{n} 个 ID")
    return ids


def _batch_loop(
    module: str,
    n: int,
    action: Callable[[int], None],
) -> List[str]:
    return _collect_batch_ids(module, n, action)


def _fallback_ids_from_db(module: str, n: int) -> List[str]:
    """批量插入不足时，从库中取已有记录补齐（仅 init 阶段）。"""
    meta = _MODULE_TABLE.get(module)
    if not meta or n <= 0:
        return []
    table, _, _ = meta
    id_col = _id_column(table)
    conn = CrmebDb._connect()
    ids: List[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {id_col} AS eid FROM {table} ORDER BY {id_col} DESC LIMIT %s",
                (n,),
            )
            for row in cur.fetchall() or []:
                val = row.get("eid")
                if val is not None:
                    ids.append(str(val))
    finally:
        conn.close()
    return list(reversed(ids))


def _merge_id_pool(module: str, created: List[str], need: int) -> List[str]:
    ids = list(created)
    if len(ids) >= need:
        return ids[:need]
    extra = _fallback_ids_from_db(module, need - len(ids))
    for eid in extra:
        if eid and eid not in ids:
            ids.append(eid)
        if len(ids) >= need:
            break
    if len(ids) < need:
        logger.warning(f"bootstrap {module} 创建+回退仍不足 {len(ids)}/{need}")
    return ids


def _batch_articles(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    cid = int(ctx.get("article_cid") or ctx.get("cid") or 0)

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/article/save",
            {
                "cid": cid,
                "title": _batch_tag("article", i),
                "author": "seed",
                "content": "batch article",
                "synopsis": "batch",
                "shareTitle": _batch_tag("article", i),
                "shareSynopsis": "batch",
                "imageInput": _cover(ctx),
                "status": True,
                "hide": False,
                "isHot": False,
                "isBanner": False,
            },
        )

    return _collect_batch_ids("article", n, work)


def _batch_categories(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    table, _, _ = _MODULE_TABLE["category"]
    id_col = _id_column(table)
    base = _max_id(table, id_col)

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/category/save",
            {
                "pid": "0",
                "name": _batch_tag("category", i),
                "type": "1",
                "status": "1",
                "sort": i + 1,
            },
            content_type="form",
        )

    for i in range(n):
        work(i)
    return _ids_after(table, id_col, base, n)


def _batch_products(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    from utils.scenario_product_helper import build_product_payload

    token = client.session.headers.get("Authori-zation", "")
    base_tpl = build_product_payload(client, token, {}, is_save=True, context=ctx)
    if not base_tpl.get("storeName"):
        cate_raw = ctx.get("cateId") or ctx.get("cate_id") or "0"
        cate_list = [int(cate_raw)] if str(cate_raw).isdigit() else []
        temp = int(ctx.get("tempId") or ctx.get("temp_id") or 0)
        cover = _cover(ctx)
        base_tpl = {
            "storeName": "batch_product",
            "keyword": "batch",
            "cateId": cate_list,
            "tempId": temp,
            "unitName": "件",
            "isShow": True,
            "isSub": False,
            "specType": False,
            "content": "batch product",
            "couponIds": ctx.get("couponIds") or ctx.get("coupon_ids") or "",
            "activity": [],
            "sliderImage": cover,
            "image": cover,
            "attr": [{"attrName": "规格", "attrValues": "默认"}],
            "attrValue": [
                {
                    "stock": 100,
                    "price": 10,
                    "cost": 5,
                    "otPrice": 15,
                    "weight": 1,
                    "volume": 1,
                    "brokerage": 0,
                    "brokerageTwo": 0,
                    "image": "",
                    "attrValue": '{"规格":"默认"}',
                }
            ],
        }

    def work(i: int) -> None:
        payload = dict(base_tpl)
        payload["storeName"] = _batch_tag("product", i)
        payload.pop("id", None)
        _post(client, "/api/admin/store/product/save", payload)

    return _batch_loop("product", n, work)


def _group_data_form(ctx: Dict[str, Any]) -> Dict[str, Any]:
    gid = int(
        ctx.get("system_group_id")
        or ctx.get("latest_system_group_id")
        or ctx.get("auto_system_group_id")
        or 0
    )
    fid = int(ctx.get("group_form_id") or ctx.get("form_id") or 0)
    fields: List[Dict[str, Any]] = []
    raw_content = ctx.get("form_temp_content") or default_form_temp_content()
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
    return {"id": fid, "sort": 1, "status": 1, "fields": fields}


def _batch_product_rules(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    rule_tpl = json.dumps([{"value": "默认规格", "detail": ["规格1"]}], ensure_ascii=False)
    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}
    collected: List[str] = []

    for i in range(n):
        tag = _batch_tag("productrule", i)
        body = _post(
            client,
            "/api/admin/store/product/rule/save",
            {"ruleName": tag, "ruleValue": rule_tpl},
        )
        if body.get("code") != 200:
            collected.append("")
            continue
        list_resp = client.request(
            method="GET",
            url=f"/api/admin/store/product/rule/list?keywords={tag}&page=1&limit=5",
            headers=headers,
            data=None,
            content_type="json",
        )
        items = (list_resp.json().get("data") or {}).get("list") or []
        eid = ""
        for item in items:
            if item.get("ruleName") == tag:
                eid = str(item.get("id") or "")
                break
        if not eid and items:
            eid = str(items[0].get("id") or "")
        collected.append(eid)

    ok = sum(1 for x in collected if x)
    if ok < n:
        logger.warning(f"bootstrap productrule 创建成功 {ok}/{n} 个 ID")
    return collected


def _batch_pagediy(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    mer = int(ctx.get("merId") or ctx.get("mer_id") or 0)

    def work(i: int) -> None:
        tag = _batch_tag("pagediy", i)
        _post(
            client,
            "/api/admin/pagediy/save",
            {
                "name": tag,
                "title": tag,
                "value": {},
                "defaultValue": "{}",
                "isDel": 0,
                "merId": mer,
            },
        )

    return _batch_loop("pagediy", n, work)


def _batch_shipping_templates(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/express/shipping/templates/save",
            {
                "name": _batch_tag("shippingtemplates", i),
                "type": 1,
                "appoint": 0,
                "sort": i + 1,
                "shippingTemplatesRegionRequestList": [],
                "shippingTemplatesFreeRequestList": [],
            },
        )

    return _batch_loop("shippingtemplates", n, work)


def _batch_activity_style(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/activitystyle/save",
            {
                "name": _batch_tag("activitystyle", i),
                "starttime": "2026-01-01 00:00:00",
                "endtime": "2026-12-31 23:59:59",
                "style": _cover(ctx),
                "method": 0,
                "type": 0,
                "status": True,
                "products": "",
            },
        )

    return _batch_loop("activitystyle", n, work)


def _batch_roles(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    rules = ctx.get("role_rules") or "1"

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/role/save",
            {"roleName": _batch_tag("systemrole", i), "rules": rules, "status": True},
        )

    return _batch_loop("systemrole", n, work)


def _batch_stores(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/store/save",
            {
                "name": _batch_tag("systemstore", i),
                "introduction": "batch",
                "phone": f"1380013{i:04d}",
                "address": "北京市东城区",
                "detailedAddress": "batch store",
                "dayTime": "09:00-21:00",
                "image": _cover(ctx),
                "latitude": "116.407396,39.904200",
                "validTime": "2030-01-01,2030-12-31",
            },
        )

    return _batch_loop("systemstore", n, work)


def _batch_admins(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    role = ctx.get("roleId") or ctx.get("role_id") or "1"
    pwd = ctx.get("LOGIN_PASS") or "123456"

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/admin/save",
            {
                "account": f"batchadm{i}_{uuid.uuid4().hex[:6]}"[:16],
                "pwd": pwd,
                "realName": f"batch_admin_{i}",
                "phone": f"139{i:08d}"[-11:],
                "roles": role,
                "status": True,
            },
        )

    return _batch_loop("systemadmin", n, work)


def _batch_user_groups(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(client, "/api/admin/user/group/save", {"groupName": _batch_tag("usergroup", i)})

    return _batch_loop("usergroup", n, work)


def _batch_user_tags(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(client, "/api/admin/user/tag/save", {"name": _batch_tag("usertag", i)})

    return _batch_loop("usertag", n, work)


def _batch_wechat_replies(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    kw_pool: List[str] = []

    def work(i: int) -> None:
        kw = f"kr{i}_{uuid.uuid4().hex[:10]}"
        kw_pool.append(kw)
        _post(
            client,
            "/api/admin/wechat/keywords/reply/save",
            {"keywords": kw, "type": "text", "data": "batch reply", "status": True},
        )

    ids = _batch_loop("wechatreply", n, work)
    ctx["_wechat_kw_pool"] = kw_pool
    return ids


def _batch_user_levels(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    from utils.context_data import bind_context, ctx_next_user_level_grade

    bind_context(ctx)
    collected: List[str] = []
    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}

    for i in range(n):
        name = _batch_tag("systemuserlevel", i)
        grade, experience = ctx_next_user_level_grade()
        body = _post(
            client,
            "/api/admin/system/user/level/save",
            {
                "name": name,
                "grade": grade,
                "experience": experience,
                "discount": 100,
                "icon": "/mock/level.png",
                "isShow": True,
            },
        )
        if body.get("code") != 200:
            collected.append("")
            continue
        list_resp = client.request(
            method="GET",
            url="/api/admin/system/user/level/list",
            headers=headers,
            data=None,
            content_type="json",
        )
        data_block = list_resp.json().get("data")
        items = data_block if isinstance(data_block, list) else (data_block or {}).get("list") or []
        eid = ""
        for item in items:
            if item.get("name") == name:
                eid = str(item.get("id") or "")
                break
        if not eid and items:
            eid = str(items[0].get("id") or "")
        collected.append(eid)

    ok = sum(1 for x in collected if x)
    if ok < n:
        logger.warning(f"bootstrap systemuserlevel 创建成功 {ok}/{n} 个 ID")
    return collected


def _batch_express(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/express/save",
            {
                "name": _batch_tag("express", i),
                "code": f"B{uuid.uuid4().hex[:8].upper()}",
                "sort": i + 1,
                "isShow": True,
            },
        )

    return _batch_loop("express", n, work)


def _batch_system_groups(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    fid = int(ctx.get("form_id") or 0)

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/group/save",
            {"name": _batch_tag("systemgroup", i), "info": "batch", "formId": fid},
            content_type="form",
        )

    return _batch_loop("systemgroup", n, work)


def _batch_form_temps(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/form/temp/save",
            {
                "name": _batch_tag("systemformtemp", i),
                "info": "batch form",
                "content": default_form_temp_content(),
            },
        )

    return _batch_loop("systemformtemp", n, work)


def _batch_group_data(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    gid = int(
        ctx.get("system_group_id")
        or ctx.get("latest_system_group_id")
        or ctx.get("auto_system_group_id")
        or 0
    )
    form_payload = _group_data_form(ctx)

    def work(i: int) -> None:
        payload = dict(form_payload)
        payload["sort"] = i + 1
        _post(client, "/api/admin/system/group/data/save", {"gid": gid, "form": payload})

    return _batch_loop("systemgroupdata", n, work)


def _batch_menus(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/menu/add",
            {
                "pid": 0,
                "name": _batch_tag("systemmenu", i),
                "icon": "/mock/auto.png",
                "perms": "",
                "component": "",
                "menuType": "M",
                "sort": i + 1,
                "isShow": 1,
            },
        )

    return _batch_loop("systemmenu", n, work)


def _batch_user_uids(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    """用户模块：从库中取独立 uid 分配给各场景（不新建用户）。"""
    del client
    if n <= 0:
        return []
    conn = CrmebDb._connect()
    uids: List[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT uid FROM eb_user WHERE uid > 0 ORDER BY uid DESC LIMIT %s",
                (n,),
            )
            for row in cur.fetchall() or []:
                val = row.get("uid") or next(iter(row.values()), None)
                if val:
                    uids.append(str(val))
    finally:
        conn.close()
    if len(uids) < n:
        logger.warning(f"bootstrap user 仅拿到 {len(uids)}/{n} 个 uid")
    return uids


def _batch_seckill_manger(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    time_map: Dict[str, str] = dict(ctx.get("_seckill_time_by_id") or {})
    occupied: set = set(ctx.get("_seckill_occupied_hours") or [])
    hours_used: List[int] = []
    ranges_by_idx: List[str] = []

    def work(i: int) -> None:
        free = [h for h in range(23) if h not in occupied]
        h = free[0] if free else (i + 11) % 23
        occupied.add(h)
        hours_used.append(h)
        tr = f"{h:02d}:00,{(h + 1):02d}:00"
        ranges_by_idx.append(tr)
        _post(
            client,
            "/api/admin/store/seckill/manger/save",
            {
                "name": _batch_tag("storeseckillmanger", i),
                "time": tr,
                "img": _cover(ctx),
                "silderImgs": _cover(ctx),
                "status": "1",
                "isDel": False,
            },
        )

    ids = _batch_loop("storeseckillmanger", n, work)
    ctx["_seckill_occupied_hours"] = sorted(occupied)
    for i, mid in enumerate(ids):
        h = hours_used[i] if i < len(hours_used) else (i + 11) % 23
        time_map[str(mid)] = f"{h:02d}:00,{(h + 1):02d}:00"
    ctx["_seckill_time_by_id"] = time_map
    ctx["_seckill_free_hours"] = [h for h in range(23) if h not in occupied] or list(range(23))
    ctx["_seckill_ranges_by_idx"] = ranges_by_idx
    return ids


def _activity_payload(client: ApiClient, ctx: Dict[str, Any], product_id: str, title: str) -> Dict[str, Any]:
    cover = _cover(ctx)
    pid = int(product_id or 0)
    return {
        "productId": pid,
        "image": cover,
        "images": cover,
        "title": title,
        "storeName": title,
        "startTime": "2030-01-01 00:00:00",
        "stopTime": "2030-12-31 23:59:59",
        "unitName": "件",
        "isShow": True,
        "content": "",
        "num": 10,
        "stock": 100,
        "tempId": int(ctx.get("tempId") or ctx.get("temp_id") or 0),
        "attr": [{"attrName": "规格", "attrValues": "默认"}],
        "attrValue": [
            {
                "productId": pid,
                "stock": 100,
                "price": 100,
                "minPrice": 50,
                "cost": 50,
                "otPrice": 120,
                "weight": 1,
                "volume": 1,
                "brokerage": 0,
                "brokerageTwo": 0,
                "image": cover,
                "attrValue": '{"规格":"默认"}',
                "quota": 10,
                "quotaShow": 10,
            }
        ],
    }


def _batch_bargains(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    from utils.scenario_activity_helper import build_bargain_activity_attrs, build_minimal_activity_payload
    from utils.scenario_product_helper import build_product_payload

    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}
    collected: List[str] = []

    for i in range(n):
        one = _batch_products(client, ctx, 1)
        pid = one[0] if one else ctx.get("product_id")
        local_ctx = dict(ctx)
        local_ctx["product_id"] = str(pid or "")
        tag = _batch_tag("storebargain", i)
        payload = build_minimal_activity_payload(
            "StoreBargainController_save",
            {"title": tag, "storeName": tag, "productId": int(pid or 0)},
            context=local_ctx,
        )
        prod = build_product_payload(
            client,
            token,
            {},
            is_save=False,
            source_product_id=int(pid or 0) or None,
            context=local_ctx,
        )
        attrs, attr_values = build_bargain_activity_attrs(
            prod,
            product_id=int(pid or 0) or None,
        )
        payload["attr"] = attrs
        payload["attrValue"] = attr_values
        if not payload.get("tempId"):
            payload["tempId"] = int(prod.get("tempId") or local_ctx.get("temp_id") or 0)
        body = _post(client, "/api/admin/store/bargain/save", payload)
        if body.get("code") != 200:
            collected.append("")
            continue
        list_resp = client.request(
            method="GET",
            url=f"/api/admin/store/bargain/list?keywords={tag}&page=1&limit=5",
            headers=headers,
            data=None,
            content_type="json",
        )
        items = (list_resp.json().get("data") or {}).get("list") or []
        eid = ""
        for item in items:
            if item.get("title") == tag or item.get("storeName") == tag:
                eid = str(item.get("id") or "")
                break
        if not eid and items:
            eid = str(items[0].get("id") or "")
        collected.append(eid)

    ok = sum(1 for x in collected if x)
    if ok < n:
        logger.warning(f"bootstrap storebargain 创建成功 {ok}/{n} 个 ID")
    return collected


def _batch_combinations(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    from utils.scenario_activity_helper import build_bargain_activity_attrs, build_minimal_activity_payload
    from utils.scenario_product_helper import build_product_payload

    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}
    collected: List[str] = []

    for i in range(n):
        one = _batch_products(client, ctx, 1)
        pid = one[0] if one else ctx.get("product_id")
        local_ctx = dict(ctx)
        local_ctx["product_id"] = str(pid or "")
        tag = _batch_tag("storecombination", i)
        payload = build_minimal_activity_payload(
            "StoreCombinationController_save",
            {"title": tag, "storeName": tag, "productId": int(pid or 0)},
            context=local_ctx,
        )
        prod = build_product_payload(
            client,
            token,
            {},
            is_save=False,
            source_product_id=int(pid or 0) or None,
            context=local_ctx,
        )
        attrs, attr_values = build_bargain_activity_attrs(
            prod,
            product_id=int(pid or 0) or None,
        )
        payload["attr"] = attrs
        payload["attrValue"] = attr_values
        if not payload.get("tempId"):
            payload["tempId"] = int(prod.get("tempId") or local_ctx.get("temp_id") or 0)
        body = _post(client, "/api/admin/store/combination/save", payload)
        if body.get("code") != 200:
            collected.append("")
            continue
        list_resp = client.request(
            method="GET",
            url=f"/api/admin/store/combination/list?keywords={tag}&page=1&limit=5",
            headers=headers,
            data=None,
            content_type="json",
        )
        items = (list_resp.json().get("data") or {}).get("list") or []
        eid = ""
        for item in items:
            if item.get("title") == tag or item.get("storeName") == tag:
                eid = str(item.get("id") or "")
                break
        if not eid and items:
            eid = str(items[0].get("id") or "")
        collected.append(eid)

    ok = sum(1 for x in collected if x)
    if ok < n:
        logger.warning(f"bootstrap storecombination 创建成功 {ok}/{n} 个 ID")
    return collected


def _batch_seckills(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    from utils.scenario_activity_helper import build_bargain_activity_attrs, build_minimal_activity_payload
    from utils.scenario_product_helper import build_product_payload

    time_ids = ctx.get("_seckill_time_pool") or [ctx.get("seckill_time_id") or "0"]
    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}
    collected: List[str] = []

    for i in range(n):
        one = _batch_products(client, ctx, 1)
        pid = one[0] if one else ctx.get("product_id")
        tid = int(time_ids[i % len(time_ids)] or 0)
        local_ctx = dict(ctx)
        local_ctx["product_id"] = str(pid or "")
        local_ctx["seckill_time_id"] = tid
        tag = _batch_tag("storeseckill", i)
        payload = build_minimal_activity_payload(
            "StoreSeckillController_save",
            {"title": tag, "storeName": tag, "productId": int(pid or 0), "timeId": tid},
            context=local_ctx,
        )
        prod = build_product_payload(
            client,
            token,
            {},
            is_save=False,
            source_product_id=int(pid or 0) or None,
            context=local_ctx,
        )
        attrs, attr_values = build_bargain_activity_attrs(
            prod,
            product_id=int(pid or 0) or None,
        )
        payload["attr"] = attrs
        payload["attrValue"] = attr_values
        if not payload.get("tempId"):
            payload["tempId"] = int(prod.get("tempId") or local_ctx.get("temp_id") or 0)
        body = _post(client, "/api/admin/store/seckill/save", payload)
        if body.get("code") != 200:
            collected.append("")
            continue
        list_resp = client.request(
            method="GET",
            url=f"/api/admin/store/seckill/list?keywords={tag}&page=1&limit=5",
            headers=headers,
            data=None,
            content_type="json",
        )
        items = (list_resp.json().get("data") or {}).get("list") or []
        eid = ""
        for item in items:
            if item.get("title") == tag or item.get("storeName") == tag:
                eid = str(item.get("id") or "")
                break
        if not eid and items:
            eid = str(items[0].get("id") or "")
        collected.append(eid)

    ok = sum(1 for x in collected if x)
    if ok < n:
        logger.warning(f"bootstrap storeseckill 创建成功 {ok}/{n} 个 ID")
    return collected


def _batch_coupons(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/marketing/coupon/save",
            {
                "name": _batch_tag("storecoupon", i),
                "money": 10,
                "isLimited": 1,
                "total": 100,
                "useType": 1,
                "primaryKey": "",
                "minPrice": 0,
                "isForever": 1,
                "receiveStartTime": "2030-01-01 00:00:00",
                "receiveEndTime": "2030-12-31 23:59:59",
                "isFixedTime": 1,
                "useStartTime": "2030-01-01 00:00:00",
                "useEndTime": "2030-12-31 23:59:59",
                "day": 0,
                "type": 1,
                "sort": i + 1,
                "status": 1,
            },
        )

    return _batch_loop("storecoupon", n, work)


def _batch_staff(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    from utils.context_data import bind_context, ctx_pop_staff_uid

    bind_context(ctx)
    store_ids = ctx.get("_batch_store_pool") or [ctx.get("store_id")]
    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}
    collected: List[str] = []

    for i in range(n):
        uid = ctx_pop_staff_uid()
        store = store_ids[i % len(store_ids)] if store_ids else ctx.get("store_id")
        if not uid or not store:
            collected.append("")
            continue
        name = _batch_tag("systemstorestaff", i)
        body = _post(
            client,
            "/api/admin/system/store/staff/save",
            {
                "uid": int(uid),
                "storeId": int(store),
                "staffName": name,
                "phone": f"137{i:08d}"[-11:],
                "avatar": "",
            },
            content_type="form",
        )
        if body.get("code") != 200:
            collected.append("")
            continue
        list_resp = client.request(
            method="GET",
            url=f"/api/admin/system/store/staff/list?storeId={store}&page=1&limit=20",
            headers=headers,
            data=None,
            content_type="json",
        )
        items = (list_resp.json().get("data") or {}).get("list") or []
        eid = ""
        for item in items:
            if item.get("staffName") == name:
                eid = str(item.get("id") or "")
                break
        if not eid and items:
            eid = str(items[-1].get("id") or "")
        collected.append(eid)

    ok = sum(1 for x in collected if x)
    if ok < n:
        logger.warning(f"bootstrap systemstorestaff 创建成功 {ok}/{n} 个 ID")
    return collected


def _batch_cities(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    parent = int(ctx.get("city_parent_id") or ctx.get("parentId") or 0)

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/city/save",
            {"parentId": parent, "name": _batch_tag("systemcity", i), "level": 2},
        )

    return _batch_loop("systemcity", n, work)


def _batch_attachments(client: ApiClient, ctx: Dict[str, Any], n: int) -> List[str]:
    cover = _cover(ctx)

    def work(i: int) -> None:
        _post(
            client,
            "/api/admin/system/attachment/save",
            {
                "name": _batch_tag("systemattachment", i),
                "attDir": cover,
                "sattDir": cover,
            },
        )

    return _batch_loop("systemattachment", n, work)


def _ensure_staff_candidate_users(min_free: int) -> None:
    """init 阶段：确保有足够未绑定核销员的用户 uid。"""
    import uuid

    conn = CrmebDb._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM eb_user u "
                "LEFT JOIN eb_system_store_staff s ON u.uid=s.uid WHERE s.uid IS NULL"
            )
            row = cur.fetchone() or {}
            free = int(row.get("c") or next(iter(row.values()), 0) or 0)
            need = max(0, min_free - free)
            for i in range(need):
                suffix = uuid.uuid4().hex[:10]
                account = f"auto_staff_{suffix}"
                phone = f"199{suffix[:8]}{i:02d}"[-11:]
                cur.execute(
                    "INSERT INTO eb_user "
                    "(account, pwd, nickname, phone, status, user_type, now_money, "
                    "brokerage_price, integral, experience, level, is_promoter, pay_count, "
                    "spread_count, sex, sign_num, create_time, update_time) "
                    "VALUES (%s, '123456', %s, %s, 1, 'h5', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, NOW(), NOW())",
                    (account, account, phone),
                )
            if need:
                conn.commit()
                logger.info(f"bootstrap 补充核销员候选用户 {need} 个（原有可用 {free}）")
    finally:
        conn.close()


def _expand_staff_uid_pool(min_size: int) -> List[int]:
    pool: List[int] = []
    conn = CrmebDb._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u.uid FROM eb_user u LEFT JOIN eb_system_store_staff s ON u.uid=s.uid "
                "WHERE s.uid IS NULL ORDER BY u.uid DESC LIMIT %s",
                (min_size,),
            )
            for row in cur.fetchall() or []:
                uid = int(next(iter(row.values())) or 0)
                if uid > 0:
                    pool.append(uid)
            if len(pool) < min_size:
                cur.execute(
                    "SELECT uid FROM eb_user WHERE uid > 0 ORDER BY uid DESC LIMIT %s",
                    (min_size,),
                )
                for row in cur.fetchall() or []:
                    uid = int(next(iter(row.values())) or 0)
                    if uid > 0 and uid not in pool:
                        pool.append(uid)
    finally:
        conn.close()
    return pool[:min_size]


_BATCH_CREATORS: Dict[str, Callable[[ApiClient, Dict[str, Any], int], List[str]]] = {
    "article": _batch_articles,
    "category": _batch_categories,
    "product": _batch_products,
    "storeproductrule": _batch_product_rules,
    "pagediy": _batch_pagediy,
    "shippingtemplates": _batch_shipping_templates,
    "activitystyle": _batch_activity_style,
    "systemrole": _batch_roles,
    "systemstore": _batch_stores,
    "systemadmin": _batch_admins,
    "usergroup": _batch_user_groups,
    "usertag": _batch_user_tags,
    "wechatreply": _batch_wechat_replies,
    "systemuserlevel": _batch_user_levels,
    "express": _batch_express,
    "systemgroup": _batch_system_groups,
    "systemformtemp": _batch_form_temps,
    "systemgroupdata": _batch_group_data,
    "systemmenu": _batch_menus,
    "user": _batch_user_uids,
    "storeseckillmanger": _batch_seckill_manger,
    "storebargain": _batch_bargains,
    "storecombination": _batch_combinations,
    "storeseckill": _batch_seckills,
    "storecoupon": _batch_coupons,
    "systemstorestaff": _batch_staff,
    "systemcity": _batch_cities,
    "systemattachment": _batch_attachments,
}


def _primary_module(scenario: Dict[str, Any]) -> str:
    sid = (scenario.get("scenario_id") or "").upper()
    if "STOREPRODUCTRULE" in sid:
        return "storeproductrule"
    for step in scenario.get("steps") or []:
        mod = (step.get("module") or "").strip().lower()
        if mod and mod != "admin":
            return mod
    return "product"


def _needs_preassigned_entity(scenario: Dict[str, Any]) -> bool:
    for step in scenario.get("steps") or []:
        op = step.get("operation_id") or ""
        if "login" in op.lower():
            continue
        if op.endswith("_save"):
            return False
        return True
    return True


def _allocate_one_seckill_range(ctx: Dict[str, Any]) -> str:
    from utils.context_data import bind_context, ctx_next_seckill_time_range

    bind_context(ctx)
    return ctx_next_seckill_time_range()


def _bootstrap_seckill_manger_module(
    client: ApiClient,
    ctx: Dict[str, Any],
    sids: List[str],
    scenario_map: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    """逐场景分配独立时段；仅 INFO 类场景 save + list 回填，save 优先场景只占时段。"""
    from utils.context_data import bind_context, ctx_mark_seckill_hour

    _purge_autotest_seckill_manger_records()
    _reload_seckill_occupied_hours(ctx)
    bind_context(ctx)
    token = client.session.headers.get("Authori-zation", "")
    headers = {"Authori-zation": token}
    pool: List[str] = []
    ranges: List[str] = []
    time_map: Dict[str, str] = dict(ctx.get("_seckill_time_by_id") or {})
    occupied: set = {
        int(x) for x in (ctx.get("_seckill_occupied_hours") or []) if str(x).isdigit()
    }

    def _next_time_range() -> str:
        for h in range(23):
            if h not in occupied and (h + 1) <= 23:
                occupied.add(h)
                tr = f"{h:02d}:00,{(h + 1):02d}:00"
                ctx_mark_seckill_hour(tr)
                return tr
        tr = "22:00,23:00"
        ctx_mark_seckill_hour(tr)
        return tr

    info_idx = 0
    for sid in sids:
        tr = _next_time_range()
        ranges.append(tr)
        if not _needs_preassigned_entity(scenario_map[sid]):
            pool.append("")
            continue
        tag = _batch_tag("storeseckillmanger", info_idx)
        info_idx += 1
        eid = ""
        cur_tr = tr
        for _attempt in range(8):
            body = _post(
                client,
                "/api/admin/store/seckill/manger/save",
                {
                    "name": tag,
                    "time": cur_tr,
                    "img": _cover(ctx),
                    "silderImgs": _cover(ctx),
                    "status": "1",
                    "isDel": False,
                },
            )
            if body.get("code") == 200:
                list_resp = client.request(
                    method="GET",
                    url=f"/api/admin/store/seckill/manger/list?name={tag}&page=1&limit=5",
                    headers=headers,
                    data=None,
                    content_type="json",
                )
                items = (list_resp.json().get("data") or {}).get("list") or []
                for item in items:
                    if item.get("name") == tag:
                        eid = str(item.get("id") or "")
                        break
                if not eid and items:
                    eid = str(items[0].get("id") or "")
                ranges[-1] = cur_tr
                break
            msg = str(body.get("message") or "")
            if "已存在" in msg or "exist" in msg.lower():
                cur_tr = _next_time_range()
                ranges[-1] = cur_tr
                continue
            logger.warning(
                f"bootstrap storeseckillmanger save 失败 sid={sid}: {msg or body.get('code')}"
            )
            break
        pool.append(eid)
        if eid:
            time_map[str(eid)] = ranges[-1]

    ctx["_seckill_occupied_hours"] = sorted(occupied)
    ctx["_seckill_time_by_id"] = time_map
    ctx["_seckill_ranges_by_idx"] = ranges
    inserted = [x for x in pool if x]
    if inserted:
        ctx["_seckill_time_pool"] = inserted
    ok = sum(1 for x in pool if x)
    need = sum(1 for sid in sids if _needs_preassigned_entity(scenario_map[sid]))
    if ok < need:
        logger.warning(f"bootstrap storeseckillmanger 创建成功 {ok}/{need} 个 ID")
    return pool, ranges


def _align_pool_for_info_first(
    sids: List[str],
    scenario_map: Dict[str, Dict[str, Any]],
    inserted_ids: List[str],
) -> List[str]:
    """save 优先场景不占插入 ID，仅 INFO 类场景使用 batch 插入结果。"""
    aligned: List[str] = []
    id_iter = iter(inserted_ids)
    for sid in sids:
        if _needs_preassigned_entity(scenario_map[sid]):
            aligned.append(next(id_iter, ""))
        else:
            aligned.append("")
    return aligned


def _should_skip_scenario(scenario_id: str) -> bool:
    from utils.scenario_skip import should_skip_scenario

    return should_skip_scenario(scenario_id)


def bootstrap_scenario_entities(
    client: ApiClient,
    base_context: Dict[str, Any],
    scenarios: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """按模块批量插入，每条场景绑定独立 entity_id。"""
    scenarios = scenarios or ScenarioDataHandler.get_all_scenarios()
    active = [s for s in scenarios if not _should_skip_scenario(s["scenario_id"])]

    by_module: Dict[str, List[str]] = defaultdict(list)
    scenario_map: Dict[str, Dict[str, Any]] = {s["scenario_id"]: s for s in active}
    for sc in active:
        by_module[_primary_module(sc)].append(sc["scenario_id"])

    staff_need = max(250, len(by_module.get("systemstorestaff", [])) * 3, len(active))
    _ensure_staff_candidate_users(staff_need)
    base_context["_staff_uid_pool"] = _expand_staff_uid_pool(staff_need)

    store_count = max(
        len(by_module.get("systemstore", [])),
        len(by_module.get("systemstorestaff", [])),
        1,
    )
    if store_count:
        base_context["_batch_store_pool"] = _batch_stores(client, base_context, store_count)

    module_pools: Dict[str, List[str]] = {}
    user_level_pool: List[str] = []
    if by_module.get("user"):
        user_level_pool = _merge_id_pool(
            "systemuserlevel",
            _batch_user_levels(client, base_context, len(by_module["user"])),
            len(by_module["user"]),
        )
    if by_module.get("storeseckillmanger"):
        mgr_sids = by_module["storeseckillmanger"]
        pool, _ = _bootstrap_seckill_manger_module(
            client, base_context, mgr_sids, scenario_map
        )
        module_pools["storeseckillmanger"] = pool

    if by_module.get("systemstore") and base_context.get("_batch_store_pool"):
        module_pools["systemstore"] = base_context["_batch_store_pool"][
            : len(by_module["systemstore"])
        ]

    for module, sids in by_module.items():
        if module in module_pools:
            continue
        if module == "systemstorestaff":
            info_count = sum(
                1 for sid in sids if _needs_preassigned_entity(scenario_map[sid])
            )
            inserted: List[str] = []
            if info_count:
                inserted = _batch_staff(client, base_context, info_count)
                if len(inserted) < info_count:
                    inserted = list(inserted) + [""] * (info_count - len(inserted))
            module_pools[module] = _align_pool_for_info_first(sids, scenario_map, inserted)
            continue
        creator = _BATCH_CREATORS.get(module)
        if not creator:
            logger.warning(f"bootstrap 未实现模块 {module}，场景数={len(sids)}")
            module_pools[module] = [str(base_context.get(MODULE_ENTITY_KEY.get(module, ""), ""))] * len(sids)
            continue
        if module in ("storebargain", "storecombination", "storeseckill", "storeproductrule"):
            info_count = sum(
                1 for sid in sids if _needs_preassigned_entity(scenario_map[sid])
            )
            logger.info(
                f"bootstrap 批量插入 {module} x{info_count}（场景总数 {len(sids)}）"
            )
            ids = creator(client, base_context, info_count) if info_count else []
            if len(ids) < info_count:
                ids = list(ids) + [""] * (info_count - len(ids))
            module_pools[module] = _align_pool_for_info_first(sids, scenario_map, ids)
        else:
            logger.info(f"bootstrap 批量插入 {module} x{len(sids)}")
            ids = creator(client, base_context, len(sids))
            ids = _merge_id_pool(module, ids, len(sids))
            module_pools[module] = ids

    assignments: Dict[str, Dict[str, Any]] = {}
    for module, sids in by_module.items():
        entity_key = MODULE_ENTITY_KEY.get(module, "entity_id")
        pool = module_pools.get(module, [])
        for idx, sid in enumerate(sids):
            sc = scenario_map[sid]
            eid = pool[idx] if idx < len(pool) else ""
            item: Dict[str, Any] = {"_scenario_module": module}
            if eid and _needs_preassigned_entity(sc):
                item[entity_key] = eid
                item["entity_id"] = eid
                item["_preassigned_entity"] = True
                if module == "user":
                    item["uid"] = eid
            if module == "user" and idx < len(user_level_pool) and user_level_pool[idx]:
                item["levelId"] = user_level_pool[idx]
                item["user_level_id"] = user_level_pool[idx]
            if module == "wechatreply":
                kw_pool = base_context.get("_wechat_kw_pool") or []
                item["keywords"] = kw_pool[idx] if idx < len(kw_pool) else _batch_tag("wechatreply", idx)
            if module == "storeseckillmanger":
                ranges = base_context.get("_seckill_ranges_by_idx") or []
                if idx < len(ranges):
                    item["_reserved_seckill_time"] = ranges[idx]
                    item["_seckill_slot_idx"] = idx
            if module == "systemstorestaff":
                uid_pool = base_context.get("_staff_uid_pool") or []
                store_pool = base_context.get("_batch_store_pool") or [base_context.get("store_id")]
                if idx < len(uid_pool):
                    item["staff_uid"] = str(uid_pool[idx])
                    item["_staff_uid"] = uid_pool[idx]
                if store_pool:
                    item["store_id"] = str(store_pool[idx % len(store_pool)])
            if not item:
                continue
            assignments[sid] = item

    logger.info(f"bootstrap 完成：{len(assignments)} 条场景已绑定独立数据")
    return assignments


def run_bootstrap(client: ApiClient, base_context: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    _login(client)
    return bootstrap_scenario_entities(client, base_context)
