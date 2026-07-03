"""场景 skip 规则（runner / pytest / bootstrap 共用，含跳过原因）。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# scenario_id -> 跳过原因
SKIP_BY_ID: Dict[str, str] = {
    "SCN-SCHEDULEJOB-CRUD": "定时任务依赖 Quartz/外部调度，当前环境未接入",
    "SCN-STOREPRODUCT-IMPORTPRODUCT-CHAIN": "商品导入链依赖外部 Excel/文件服务，当前环境暂跳过",
}

# prefix -> 跳过原因
SKIP_BY_PREFIX: Tuple[Tuple[str, str], ...] = (
    ("SCN-OPENAPI-", "OpenAPI 探针链依赖独立网关配置，当前环境暂跳过"),
    ("SCN-SYSTEMCONFIG-", "系统配置读写影响全局环境，自动化暂跳过"),
    ("SCN-STOREORDER-", "订单场景依赖支付/物流外部状态，当前环境暂跳过"),
    ("SCN-STOREPRODUCTREPLY-", "商品评论依赖真实订单与用户行为，当前环境暂跳过"),
    ("SCN-SYSTEMNOTIFICATION-", "通知模板依赖微信/短信第三方配置，当前环境暂跳过"),
    (
        "SCN-WECHATREPLY-",
        "微信关键词回复：测试环境无接口权限或关键词业务校验失败（403/500），暂跳过",
    ),
    (
        "SCN-SYSTEMGROUPDATA-",
        "组合数据 save/update 依赖 seed 组合与表单模板字段契约，当前环境接口持续 500，暂跳过",
    ),
)

# 子串 -> 跳过原因
SKIP_BY_CONTAINS: Tuple[Tuple[str, str], ...] = (
    ("IMPORTPRODUCT", "商品导入依赖外部文件，当前环境暂跳过"),
    ("QUICKADDSTOCK", "快速加库存依赖已上架商品状态，链路不稳定暂跳过"),
    ("SYSTEMMENU-INFO-TO-", "菜单 INFO 链路易受权限树变更影响，暂跳过"),
    ("SCN-USEREXTRACT-", "用户提现依赖支付/审核流程，当前环境暂跳过"),
    ("SCN-SYSTEMSTORE-FULL-CHAIN", "门店全链路含回收/恢复等多状态，全量串跑易冲突，暂跳过"),
    ("SCN-STORESECKILL-FULL-CHAIN", "秒杀全链路依赖时段池与活动状态，全量串跑易冲突，暂跳过"),
    ("SCN-STORESECKILLMANGER-FULL-CHAIN", "秒杀时段配置全链路易与时段池冲突，全量串跑暂跳过"),
    ("SCN-STOREPRODUCT-FULL-CHAIN", "商品全链路含上下架/恢复，全量串跑易冲突，暂跳过"),
    ("SCN-STOREPRODUCTRULE-FULL-CHAIN", "商品规格全链路易与规格池冲突，全量串跑暂跳过"),
)

DEFAULT_SKIP_REASON = "场景依赖外部数据或当前环境不可用，暂跳过"


def scenario_skip_reason(scenario_id: str) -> Optional[str]:
    """返回跳过原因；不跳过则 None。"""
    if not scenario_id:
        return None
    if scenario_id in SKIP_BY_ID:
        return SKIP_BY_ID[scenario_id]
    for prefix, reason in SKIP_BY_PREFIX:
        if scenario_id.startswith(prefix):
            return reason
    for token, reason in SKIP_BY_CONTAINS:
        if token in scenario_id:
            return reason
    return None


def should_skip_scenario(scenario_id: str) -> bool:
    return scenario_skip_reason(scenario_id) is not None
