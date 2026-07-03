"""商品场景：从已有商品详情构造 save/update 请求体。"""
from typing import Any, Dict, List, Optional

from core.api_client import ApiClient
from utils.context_data import ctx_get_from

# 响应中可能是数组/对象，但请求体要求 String 的字段
_STRING_FIELDS = frozenset(
    {
        "sliderImage",
        "image",
        "recommendImage",
        "flatPattern",
        "videoLink",
    }
)

# 详情接口返回但 save 不需要的字段
_DROP_FIELDS = frozenset(
    {
        "addTime",
        "createTime",
        "updateTime",
        "attrValues",
        "description",
        "content",
        "soureLink",
        "codePath",
        "giveIntegral",
        "ficti",
        "isSub",
        "activity",
        "couponName",
        "presaleTime",
    }
)


def _to_string(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return ",".join(str(x) for x in val if x not in (None, ""))
    return str(val)


def normalize_coupon_ids(payload: Dict[str, Any]) -> None:
    """StoreProduct save/update 要求 couponIds 为 List<Integer> 或省略。"""
    coupon_ids = payload.get("couponIds")
    if isinstance(coupon_ids, str) and coupon_ids.strip():
        payload["couponIds"] = [
            int(x.strip()) for x in coupon_ids.split(",") if x.strip().isdigit()
        ]
    elif coupon_ids == "" or coupon_ids is None:
        payload.pop("couponIds", None)
    elif isinstance(coupon_ids, list):
        payload["couponIds"] = [int(x) for x in coupon_ids if str(x).isdigit()]


def _sanitize_attr_rows(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "attrName": item.get("attrName") or "默认",
                "attrValues": item.get("attrValues") or "默认",
            }
        )
    return cleaned


def _sanitize_attr_value_for_save(items: Any) -> List[Dict[str, Any]]:
    keep = (
        "stock",
        "price",
        "image",
        "cost",
        "otPrice",
        "weight",
        "volume",
        "brokerage",
        "brokerageTwo",
        "barCode",
        "suk",
        "attrValue",
    )
    cleaned: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row = {k: item[k] for k in keep if k in item and item[k] is not None}
        if "attrValue" in row and not isinstance(row["attrValue"], str):
            row["attrValue"] = _to_string(row["attrValue"])
        row["productId"] = 0
        if "stock" not in row:
            row["stock"] = 100
        if "price" not in row:
            row["price"] = 10
        if "cost" not in row:
            row["cost"] = 5
        if "otPrice" not in row:
            row["otPrice"] = 15
        if "weight" not in row:
            row["weight"] = 1
        if "volume" not in row:
            row["volume"] = 1
        if "brokerage" not in row:
            row["brokerage"] = 0
        if "brokerageTwo" not in row:
            row["brokerageTwo"] = 0
        if "image" not in row:
            row["image"] = ""
        cleaned.append(row)
    return cleaned


def _finalize_product_save_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """新增商品：去掉详情只读字段，补齐 save 必填项。"""
    for key in (
        "sales",
        "type",
        "quota",
        "quotaShow",
        "minPrice",
        "isShow",
        "isDel",
        "browse",
        "codePath",
        "id",
    ):
        payload.pop(key, None)
    payload["attr"] = _sanitize_attr_rows(payload.get("attr"))
    payload["attrValue"] = _sanitize_attr_value_for_save(payload.get("attrValue"))
    if payload.get("activity") in (None, ""):
        payload["activity"] = []
    if payload.get("merId") in (None, ""):
        payload["merId"] = 0
    if not payload.get("content"):
        payload["content"] = "autotest product content"
    if payload.get("specType") in (None, ""):
        payload["specType"] = False
    if payload.get("isSub") in (None, ""):
        payload["isSub"] = False
    return payload


def _finalize_product_update_payload(payload: Dict[str, Any], product_id: int) -> Dict[str, Any]:
    """修改商品：基于详情补齐必填项并保留 id。"""
    payload["id"] = product_id
    for key in ("sales", "browse", "codePath", "isDel"):
        payload.pop(key, None)
    payload["attr"] = _sanitize_attr_rows(payload.get("attr"))
    attr_values = _sanitize_attr_value(payload.get("attrValue")) or []
    cleaned_av: List[Dict[str, Any]] = []
    for item in attr_values:
        row = dict(item)
        row["productId"] = product_id
        row.pop("id", None)
        cleaned_av.append(row)
    payload["attrValue"] = cleaned_av
    if payload.get("activity") in (None, ""):
        payload["activity"] = []
    if payload.get("merId") in (None, ""):
        payload["merId"] = 0
    if not payload.get("content"):
        payload["content"] = "autotest product content"
    if payload.get("specType") in (None, ""):
        payload["specType"] = False
    if payload.get("isSub") in (None, ""):
        payload["isSub"] = False
    return payload


def build_product_payload(
    api_client: ApiClient,
    token: str,
    overrides: Optional[Dict[str, Any]] = None,
    *,
    is_save: bool = True,
    source_product_id: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """拉取已有商品详情作为模板（ID 来自初始化 context）。"""
    overrides = overrides or {}
    product_id = str(
        source_product_id
        or overrides.get("id")
        or ctx_get_from(context or {}, "product_id", "")
    )
    if not product_id:
        normalize_coupon_ids(overrides)
        return overrides

    resp = api_client.request(
        method="GET",
        url=f"/api/admin/store/product/info/{product_id}",
        headers={"Authori-zation": token},
        content_type="json",
    )
    body = resp.json()
    if body.get("code") != 200:
        return overrides

    product = body.get("data") or {}
    if not isinstance(product, dict):
        return overrides

    payload: Dict[str, Any] = {}
    for key, value in product.items():
        if key in _DROP_FIELDS:
            continue
        if key in _STRING_FIELDS:
            payload[key] = _to_string(value)
        else:
            payload[key] = value

    payload.update(overrides)
    if is_save:
        payload.pop("id", None)

    coupon_ids = payload.get("couponIds")
    if isinstance(coupon_ids, str) and coupon_ids.strip():
        payload["couponIds"] = [
            int(x.strip()) for x in coupon_ids.split(",") if x.strip().isdigit()
        ]
    elif coupon_ids == "" or coupon_ids is None:
        payload.pop("couponIds", None)
    elif isinstance(coupon_ids, list):
        payload["couponIds"] = [int(x) for x in coupon_ids if str(x).isdigit()]

    for key in _STRING_FIELDS:
        if key in payload:
            payload[key] = _to_string(payload[key])

    attr_value = _sanitize_attr_value(product.get("attrValue"))
    if attr_value:
        payload["attrValue"] = attr_value

    for flag in (
        "isSub",
        "isBenefit",
        "isBest",
        "isNew",
        "isGood",
        "isHot",
        "isPostage",
        "isVip",
    ):
        if payload.get(flag) in (None, ""):
            payload[flag] = False

    if is_save:
        payload = _finalize_product_save_payload(payload)
    else:
        update_id = overrides.get("id") or source_product_id
        if update_id:
            payload = _finalize_product_update_payload(payload, int(update_id))

    return payload


def _sanitize_attr_value(items: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(items, list):
        return None
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if "attrValue" in row and not isinstance(row["attrValue"], str):
            row["attrValue"] = _to_string(row.get("attrValue", ""))
        cleaned.append(row)
    return cleaned or None
