"""营销活动场景：从已有记录详情或最小模板构造 save/update 请求体。"""
from typing import Any, Dict, List, Optional, Tuple

from core.api_client import ApiClient
from utils.context_data import ctx_get_from
from utils.mock_data import MockData

# operationId -> (info 路径, DB 主键 key)
ACTIVITY_INFO_MAP: Dict[str, tuple[str, str]] = {
    "StoreBargainController_save": ("/api/admin/store/bargain/info", "bargain_id"),
    "StoreBargainController_update": ("/api/admin/store/bargain/info", "bargain_id"),
    "StoreCombinationController_save": ("/api/admin/store/combination/info", "combination_id"),
    "StoreCombinationController_update": ("/api/admin/store/combination/info", "combination_id"),
    "StoreSeckillController_save": ("/api/admin/store/seckill/info", "seckill_id"),
    "StoreSeckillController_update": ("/api/admin/store/seckill/info", "seckill_id"),
}


def _cover(context: Optional[Dict[str, Any]] = None) -> str:
    return ctx_get_from(context or {}, "article_cover_image", "/mock/cover.jpg")


def _product_id(context: Optional[Dict[str, Any]] = None) -> int:
    return int(ctx_get_from(context or {}, "product_id", "0") or "0")


def build_bargain_activity_attrs(
    product_payload: Dict[str, Any],
    *,
    product_id: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """从商品详情构造砍价活动所需的 attr / attrValue（含 quota、minPrice）。"""
    from utils.scenario_product_helper import _sanitize_attr_rows, _sanitize_attr_value_for_save

    pid = product_id or int(product_payload.get("productId") or _product_id() or 0)
    attrs = _sanitize_attr_rows(product_payload.get("attr"))
    attr_values = _sanitize_attr_value_for_save(product_payload.get("attrValue"))
    if not attr_values:
        cover = _cover(None)
        attr_values = [
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
        ]
    else:
        row = dict(attr_values[0])
        price = float(row.get("price") or 100)
        row["minPrice"] = row.get("minPrice") or max(1, price - 50)
        row["quota"] = row.get("quota") or 10
        row["quotaShow"] = row.get("quotaShow") or row["quota"]
        row["productId"] = pid
        attr_values = [row]
    if not attrs:
        attrs = [{"attrName": "规格", "attrValues": "默认"}]
    return attrs, attr_values


def build_minimal_activity_payload(
    operation_id: str,
    overrides: Optional[Dict[str, Any]] = None,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """库中无活动记录时使用的最小合法请求体。"""
    overrides = overrides or {}
    ctx = context or {}
    cover = _cover(ctx)
    pid = _product_id(ctx)
    rid = MockData.run_id()
    payload: Dict[str, Any] = {
        "productId": pid,
        "image": cover,
        "images": cover,
        "title": f"auto_title_{rid}",
        "storeName": f"auto_store_{rid}",
        "startTime": "2030-01-01 00:00:00",
        "stopTime": "2030-12-31 23:59:59",
        "unitName": "件",
        "isShow": True,
        "content": "",
    }

    if "StoreBargain" in operation_id:
        payload.update(
            {
                "num": 10,
                "bargainNum": 5,
                "peopleNum": 2,
                "price": 100,
                "minPrice": 50,
                "stock": 100,
                "quota": 10,
                "quotaShow": 10,
                "status": True,
                "tempId": int(ctx_get_from(ctx, "temp_id", "0") or "0"),
            }
        )
        attrs, attr_values = build_bargain_activity_attrs(payload, product_id=pid)
        payload["attr"] = attrs
        payload["attrValue"] = attr_values
    if "StoreCombination" in operation_id:
        payload.update(
            {
                "people": 2,
                "effectiveTime": 24,
                "onceNum": 1,
                "num": 100,
                "stock": 100,
                "specType": False,
                "tempId": int(ctx_get_from(ctx, "temp_id", "0") or "0"),
            }
        )
        attrs, attr_values = build_bargain_activity_attrs(payload, product_id=pid)
        payload["attr"] = attrs
        payload["attrValue"] = attr_values
    if "StoreSeckill" in operation_id:
        payload.update(
            {
                "timeId": int(ctx_get_from(ctx, "seckill_time_id", "0") or "0"),
                "num": 100,
                "stock": 100,
                "otPrice": 100,
                "price": 80,
                "quota": 10,
                "status": 1,
                "specType": False,
                "tempId": int(ctx_get_from(ctx, "temp_id", "0") or "0"),
            }
        )
        attrs, attr_values = build_bargain_activity_attrs(payload, product_id=pid)
        payload["attr"] = attrs
        payload["attrValue"] = attr_values

    payload.update(overrides)
    if operation_id.endswith("_save"):
        payload.pop("id", None)
    return payload


def build_activity_payload(
    api_client: ApiClient,
    token: str,
    operation_id: str,
    overrides: Optional[Dict[str, Any]] = None,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """拉取已有活动详情作为模板（ID 来自初始化 context）。"""
    mapping = ACTIVITY_INFO_MAP.get(operation_id)
    if not mapping:
        return None
    info_path, db_key = mapping
    ctx = context or {}
    record_id = ctx_get_from(ctx, db_key, "")
    if operation_id.endswith("_update"):
        scene_eid = ctx_get_from(ctx, "entity_id", "") or ctx_get_from(
            ctx, "_scenario_saved_entity_id", ""
        )
        if scene_eid:
            record_id = scene_eid
    if not record_id:
        return None

    resp = api_client.request(
        method="GET",
        url=f"{info_path}?id={record_id}",
        headers={"Authori-zation": token},
        content_type="json",
    )
    body = resp.json()
    if body.get("code") != 200:
        return None

    product = body.get("data") or {}
    if not isinstance(product, dict):
        return None

    payload: Dict[str, Any] = {}
    skip = {"addTime", "createTime", "updateTime", "sales", "stock"}
    for key, value in product.items():
        if key in skip:
            continue
        payload[key] = value

    payload.update(overrides or {})
    if operation_id.endswith("_save"):
        payload.pop("id", None)

    cover = _cover()
    for img_key in ("image", "images", "sliderImage", "slider_image"):
        val = payload.get(img_key)
        if not val:
            payload[img_key] = cover
        elif isinstance(val, list):
            payload[img_key] = ",".join(str(x) for x in val if x) or cover

    from datetime import datetime

    for time_key in ("startTime", "stopTime"):
        val = payload.get(time_key)
        if isinstance(val, (int, float)) or (isinstance(val, str) and str(val).isdigit()):
            ts = int(val)
            if ts > 10_000_000_000:
                ts //= 1000
            payload[time_key] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    if operation_id.endswith("_save"):
        for num_key in ("num", "people", "bargainNum", "onceNum", "effectiveTime"):
            if payload.get(num_key) in (None, "", 0):
                payload[num_key] = 2 if num_key == "people" else (24 if num_key == "effectiveTime" else 1)

    if not payload.get("productId"):
        payload["productId"] = _product_id()

    if payload.get("content") is None:
        payload["content"] = ""

    return payload
