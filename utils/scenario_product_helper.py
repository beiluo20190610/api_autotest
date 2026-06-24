"""商品场景：从已有商品详情构造 save/update 请求体。"""
from typing import Any, Dict, Optional

from core.api_client import ApiClient
from utils.db_helper import CrmebDb


def build_product_payload(
    api_client: ApiClient,
    token: str,
    overrides: Optional[Dict[str, Any]] = None,
    *,
    is_save: bool = True,
) -> Dict[str, Any]:
    """拉取库中最新商品详情，作为新增/修改请求模板。"""
    overrides = overrides or {}
    product_id = CrmebDb.get_optional("product_id", "")
    if not product_id:
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
        if key in ("addTime", "createTime", "updateTime"):
            continue
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

    return payload
