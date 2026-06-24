"""营销活动场景：从已有记录详情构造 save/update 请求体。"""
from typing import Any, Dict, Optional

from core.api_client import ApiClient
from utils.db_helper import CrmebDb

# operationId -> (info 路径, DB 主键 key)
ACTIVITY_INFO_MAP: Dict[str, tuple[str, str]] = {
    "StoreBargainController_save": ("/api/admin/store/bargain/info", "bargain_id"),
    "StoreBargainController_update": ("/api/admin/store/bargain/info", "bargain_id"),
    "StoreCombinationController_save": ("/api/admin/store/combination/info", "combination_id"),
    "StoreCombinationController_update": ("/api/admin/store/combination/info", "combination_id"),
    "StoreSeckillController_save": ("/api/admin/store/seckill/info", "seckill_id"),
    "StoreSeckillController_update": ("/api/admin/store/seckill/info", "seckill_id"),
}


def build_activity_payload(
    api_client: ApiClient,
    token: str,
    operation_id: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """拉取库中最新活动详情作为模板。"""
    mapping = ACTIVITY_INFO_MAP.get(operation_id)
    if not mapping:
        return None
    info_path, db_key = mapping
    record_id = CrmebDb.get_optional(db_key, "")
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

    cover = CrmebDb.get_optional("article_cover_image", "/mock/cover.jpg")
    for img_key in ("image", "images", "sliderImage", "slider_image"):
        if not payload.get(img_key):
            payload[img_key] = cover

    from datetime import datetime

    for time_key in ("startTime", "stopTime"):
        val = payload.get(time_key)
        if isinstance(val, (int, float)) or (isinstance(val, str) and str(val).isdigit()):
            ts = int(val)
            if ts > 10_000_000_000:
                ts //= 1000
            payload[time_key] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    if operation_id.endswith("_save"):
        for num_key in ("num", "people", "bargainNum", "onceNum"):
            if not payload.get(num_key):
                payload[num_key] = 1

    return payload
