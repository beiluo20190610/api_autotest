"""测试环境种子数据：补齐分类/模板/DIY/运费等前置。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from core.api_client import ApiClient
from core.logger import logger
from utils.db_helper import CrmebDb
from utils.form_temp_helper import default_form_temp_content
from utils.mock_data import MockData


def _login(client: ApiClient) -> str:
    resp = client.request(
        method="POST",
        url="/api/admin/login",
        data={"account": os.getenv("LOGIN_USER", "admin"), "pwd": os.getenv("LOGIN_PASS", "123456")},
        content_type="json",
    )
    body = resp.json()
    token = body.get("data", {}).get("token", "")
    if not token:
        raise RuntimeError(f"种子数据登录失败: {body}")
    client.session.headers["Authori-zation"] = token
    return token


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
        return resp.json()
    except Exception:
        return {"code": resp.status_code, "text": resp.text[:200]}


def _ensure_category(client: ApiClient) -> None:
    if CrmebDb.get_optional("cate_id", ""):
        return
    body = _post(
        client,
        "/api/admin/category/save",
        {"pid": "0", "name": f"auto_cate_{MockData.run_id()}", "type": "1", "status": "1", "sort": 1},
    )
    logger.info(f"seed category: {body.get('code')}")


def _ensure_article_category(client: ApiClient) -> None:
    if CrmebDb.get_optional("article_cid", ""):
        return
    body = _post(
        client,
        "/api/admin/category/save",
        {"pid": "0", "name": f"auto_art_cate_{MockData.run_id()}", "type": "3", "status": "1", "sort": 1},
    )
    logger.info(f"seed article category: {body.get('code')}")


def _ensure_shipping_template(client: ApiClient) -> None:
    if CrmebDb.get_optional("shipping_template_id", ""):
        return
    body = _post(
        client,
        "/api/admin/express/shipping/templates/save",
        {
            "name": f"auto_ship_{MockData.run_id()}",
            "type": 1,
            "appoint": 0,
            "sort": 1,
            "shippingTemplatesRegionRequestList": [],
            "shippingTemplatesFreeRequestList": [],
        },
    )
    logger.info(f"seed shipping template: {body.get('code')}")


def _ensure_form_temp(client: ApiClient) -> None:
    row = CrmebDb.get_row(
        "SELECT id FROM eb_system_form_temp WHERE name = 'seed_baseline_form' LIMIT 1"
    )
    if row.get("id"):
        return
    body = _post(
        client,
        "/api/admin/system/form/temp/save",
        {
            "name": "seed_baseline_form",
            "info": "autotest baseline",
            "content": default_form_temp_content(),
        },
    )
    logger.info(f"seed form temp: {body.get('code')}")


def _ensure_pagediy(client: ApiClient) -> None:
    if CrmebDb.get_optional("pagediy_id", ""):
        return
    body = _post(
        client,
        "/api/admin/pagediy/save",
        {
            "name": f"auto_diy_{MockData.run_id()}",
            "title": f"auto_title_{MockData.run_id()}",
            "value": {},
            "defaultValue": "{}",
            "isDel": 0,
            "merId": int(CrmebDb.get_optional("mer_id", "0") or "0"),
        },
    )
    logger.info(f"seed pagediy: {body.get('code')}")


def _ensure_wechat_reply(client: ApiClient) -> None:
    if CrmebDb.get_optional("wechat_reply_id", ""):
        return
    kw = f"seed_kw_{MockData.run_id()}"
    body = _post(
        client,
        "/api/admin/wechat/keywords/reply/save",
        {"keywords": kw, "type": "text", "data": "seed reply", "status": True},
    )
    logger.info(f"seed wechat reply: {body.get('code')}")


def _ensure_system_group(client: ApiClient) -> None:
    row = CrmebDb.get_row(
        "SELECT id FROM eb_system_group WHERE name LIKE 'seed_%' ORDER BY id DESC LIMIT 1"
    )
    if row.get("id"):
        return
    fid = int(CrmebDb.get_optional("form_id", "0") or "0")
    body = _post(
        client,
        "/api/admin/system/group/save",
        {"name": "seed_baseline_group", "info": "autotest baseline", "formId": fid},
        content_type="form",
    )
    logger.info(f"seed system group: {body.get('code')}")


def _ensure_store(client: ApiClient) -> None:
    if CrmebDb.get_optional("store_id", ""):
        return
    body = _post(
        client,
        "/api/admin/system/store/save",
        {
            "name": "seed_baseline_store",
            "introduction": "baseline",
            "phone": "13800138000",
            "address": "北京市东城区",
            "detailedAddress": "seed baseline store",
            "dayTime": "09:00-21:00",
            "image": "/mock/store.png",
            "latitude": "116.407396,39.904200",
            "validTime": "2030-01-01,2030-12-31",
        },
    )
    logger.info(f"seed store: {body.get('code')}")


def _ensure_role(client: ApiClient) -> None:
    if CrmebDb.get_optional("role_id", ""):
        return
    rules = CrmebDb.get_optional("role_rules", "1")
    body = _post(
        client,
        "/api/admin/system/role/save",
        {"roleName": "seed_baseline_role", "rules": rules, "status": True},
    )
    logger.info(f"seed role: {body.get('code')}")


def _ensure_user_group(client: ApiClient) -> None:
    if CrmebDb.get_optional("user_group_id", ""):
        return
    body = _post(
        client,
        "/api/admin/user/group/save",
        {"groupName": "seed_baseline_group"},
    )
    logger.info(f"seed user group: {body.get('code')}")


def _ensure_user_tag(client: ApiClient) -> None:
    if CrmebDb.get_optional("user_tag_id", ""):
        return
    body = _post(
        client,
        "/api/admin/user/tag/save",
        {"name": "seed_baseline_tag"},
    )
    logger.info(f"seed user tag: {body.get('code')}")


def _ensure_seckill_manger(client: ApiClient) -> None:
    if CrmebDb.get_optional("seckill_time_id", ""):
        return
    body = _post(
        client,
        "/api/admin/store/seckill/manger/save",
        {
            "name": "seed_baseline_seckill",
            "time": "08:00,09:00",
            "img": "/mock/seckill.png",
            "silderImgs": "/mock/seckill.png",
            "status": "1",
            "isDel": False,
        },
    )
    logger.info(f"seed seckill manger: {body.get('code')}")


def _ensure_staff(client: ApiClient) -> None:
    if CrmebDb.get_optional("staff_id", ""):
        return
    uid = CrmebDb.get_optional("staff_uid", "")
    store_id = CrmebDb.get_optional("store_id", "")
    if not uid or not store_id:
        return
    body = _post(
        client,
        "/api/admin/system/store/staff/save",
        {
            "uid": int(uid),
            "storeId": int(store_id),
            "staffName": "seed_baseline_staff",
            "phone": "13800138001",
            "avatar": "",
        },
    )
    logger.info(f"seed staff: {body.get('code')}")


def _ensure_express(client: ApiClient) -> None:
    if CrmebDb.get_optional("express_id", ""):
        return
    body = _post(
        client,
        "/api/admin/express/save",
        {
            "name": f"seed_express_{MockData.run_id()}",
            "code": f"SE{MockData.run_id()[:6]}",
            "sort": 1,
            "isShow": True,
        },
    )
    logger.info(f"seed express: {body.get('code')}")


def _ensure_article(client: ApiClient) -> None:
    if CrmebDb.get_optional("article_id", ""):
        return
    cid = CrmebDb.get_optional("article_cid", "")
    body = _post(
        client,
        "/api/admin/article/save",
        {
            "cid": int(cid or "0"),
            "title": f"seed_article_{MockData.run_id()}",
            "author": "seed",
            "content": "seed baseline article",
            "synopsis": "seed",
            "shareTitle": "seed",
            "shareSynopsis": "seed",
            "visit": 0,
            "sort": 0,
            "url": "",
            "mediaId": "",
            "status": True,
            "hide": False,
            "isHot": False,
            "isBanner": False,
            "imageInput": CrmebDb.get_optional("article_cover_image", "/mock/cover.jpg"),
        },
    )
    logger.info(f"seed article: {body.get('code')}")


def _ensure_product_baseline(client: ApiClient) -> None:
    if CrmebDb.get_optional("product_id", ""):
        return
    cate = CrmebDb.get_optional("cate_id", "")
    temp = CrmebDb.get_optional("temp_id", "")
    body = _post(
        client,
        "/api/admin/store/product/save",
        {
            "storeName": f"seed_product_{MockData.run_id()}",
            "keyword": "seed",
            "cateId": cate,
            "tempId": temp,
            "unitName": "件",
            "sort": 0,
            "isShow": True,
            "isBenefit": False,
            "isNew": False,
            "isGood": False,
            "isHot": False,
            "isBest": False,
            "isSub": False,
            "specType": False,
            "content": "seed product",
            "giveIntegral": 0,
            "ficti": 0,
            "couponIds": CrmebDb.get_optional("coupon_ids", ""),
            "activity": [],
            "sliderImage": CrmebDb.get_optional("article_cover_image", "/mock/cover.jpg"),
            "image": CrmebDb.get_optional("article_cover_image", "/mock/cover.jpg"),
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
        },
    )
    logger.info(f"seed product: {body.get('code')}")


def _ensure_user_level(client: ApiClient) -> None:
    if CrmebDb.get_optional("user_level_id", ""):
        return
    grade = int(CrmebDb.get_optional("next_user_grade", "1") or "1")
    exp = int(CrmebDb.get_optional("next_user_experience", "100") or "100")
    body = _post(
        client,
        "/api/admin/system/user/level/save",
        {
            "name": f"seed_level_{MockData.run_id()}",
            "grade": grade,
            "experience": exp,
            "discount": 100,
            "icon": "/mock/level.png",
            "isShow": True,
        },
    )
    logger.info(f"seed user level: {body.get('code')}")


def repair_invalid_user_group_ids() -> int:
    """修复 eb_user 中 Swagger 占位符等脏数据（会导致用户列表/修改接口 500）。"""
    conn = CrmebDb._connect()
    fixed = 0
    column_defaults = {
        "group_id": "0",
        "tag_id": "",
    }
    try:
        with conn.cursor() as cur:
            for column, default in column_defaults.items():
                cur.execute(
                    f"SELECT uid, {column} AS val FROM eb_user "
                    f"WHERE {column} IS NOT NULL AND {column} <> '' "
                    f"AND CAST({column} AS CHAR) REGEXP '[^0-9,]'"
                )
                for row in cur.fetchall() or []:
                    uid = row.get("uid")
                    bad = row.get("val")
                    if uid is None:
                        continue
                    cur.execute(
                        f"UPDATE eb_user SET {column} = %s WHERE uid = %s",
                        (default, uid),
                    )
                    fixed += 1
                    logger.warning(
                        f"repair user {column}: uid={uid} {bad!r} -> {default!r}"
                    )
            if fixed:
                conn.commit()
    finally:
        conn.close()
    if fixed:
        CrmebDb.clear_cache()
    return fixed


def run_seed(*, flush_redis: bool = False) -> None:
    """执行环境种子初始化（幂等）。"""
    if os.getenv("SKIP_SEED", "").lower() in ("1", "true", "yes"):
        logger.info("SKIP_SEED=1，跳过环境种子")
        return

    MockData.reset()
    CrmebDb.clear_cache()

    if flush_redis:
        try:
            CrmebDb.flush_redis()
            logger.info("Redis flushdb 完成")
        except Exception as exc:
            logger.warning(f"Redis flush 跳过: {exc}")

    client = ApiClient()
    _login(client)
    _ensure_category(client)
    _ensure_article_category(client)
    _ensure_shipping_template(client)
    _ensure_form_temp(client)
    _ensure_system_group(client)
    _ensure_store(client)
    _ensure_role(client)
    _ensure_user_group(client)
    _ensure_user_tag(client)
    _ensure_seckill_manger(client)
    _ensure_staff(client)
    _ensure_pagediy(client)
    _ensure_wechat_reply(client)
    _ensure_express(client)
    _ensure_article(client)
    _ensure_product_baseline(client)
    _ensure_user_level(client)
    CrmebDb.clear_cache()
    logger.info("环境种子数据初始化完成")
