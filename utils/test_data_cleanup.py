"""自动化测试数据清理：pytest 结束后与 scripts/cleanup_autotest_data.py 共用。"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

from core.logger import logger
from utils.db_helper import CrmebDb

# 场景 save / bootstrap / verify 脚本产生的命名前缀
_AUTO = "LIKE 'auto_%'"
_BATCH = "LIKE 'batch_%'"
_VERIFY = "LIKE 'verify_%'"


def _or_patterns(*patterns: str) -> str:
    return "(" + " OR ".join(f"{col} {p}" for col, p in patterns) + ")"


def _name(*patterns: str) -> str:
    return _or_patterns(*(("name", p) for p in patterns))


def _title(*patterns: str) -> str:
    return _or_patterns(*(("title", p) for p in patterns))


# (描述, DELETE SQL) — 先子表后主表；保留 seed_ 与 admin 主账号
CLEANUP_STATEMENTS: List[Tuple[str, str]] = [
    (
        "商品规格值",
        "DELETE av FROM eb_store_product_attr_value av "
        "INNER JOIN eb_store_product p ON av.product_id = p.id "
        f"WHERE p.store_name {_AUTO} OR p.store_name {_BATCH} "
        "OR p.store_name LIKE 'save_ok_%' OR p.store_name LIKE 'clean_test_%' "
        "OR p.store_name LIKE 'test_%' OR p.store_name LIKE 'uniq_%' "
        "OR p.store_name LIKE 'test_debug_%'",
    ),
    (
        "商品规格",
        "DELETE a FROM eb_store_product_attr a "
        "INNER JOIN eb_store_product p ON a.product_id = p.id "
        f"WHERE p.store_name {_AUTO} OR p.store_name {_BATCH} "
        "OR p.store_name LIKE 'save_ok_%' OR p.store_name LIKE 'clean_test_%' "
        "OR p.store_name LIKE 'test_%' OR p.store_name LIKE 'uniq_%' "
        "OR p.store_name LIKE 'test_debug_%'",
    ),
    (
        "商品描述",
        "DELETE d FROM eb_store_product_description d "
        "INNER JOIN eb_store_product p ON d.product_id = p.id "
        f"WHERE p.store_name {_AUTO} OR p.store_name {_BATCH} "
        "OR p.store_name LIKE 'save_ok_%' OR p.store_name LIKE 'clean_test_%' "
        "OR p.store_name LIKE 'test_%' OR p.store_name LIKE 'uniq_%' "
        "OR p.store_name LIKE 'test_debug_%'",
    ),
    (
        "自动化商品",
        "DELETE FROM eb_store_product WHERE "
        f"store_name {_AUTO} OR store_name {_BATCH} OR store_name = 'batch_product' "
        "OR store_name LIKE 'save_ok_%' OR store_name LIKE 'clean_test_%' "
        "OR store_name LIKE 'test_%' OR store_name LIKE 'uniq_%' "
        "OR store_name LIKE 'test_debug_%'",
    ),
    (
        "秒杀活动",
        f"DELETE FROM eb_store_seckill WHERE {_title(_AUTO, _BATCH)}",
    ),
    (
        "砍价活动",
        "DELETE FROM eb_store_bargain WHERE "
        f"{_title(_AUTO, _BATCH)} OR store_name {_AUTO} OR store_name {_BATCH}",
    ),
    (
        "拼团活动",
        f"DELETE FROM eb_store_combination WHERE {_title(_AUTO, _BATCH)}",
    ),
    (
        "秒杀时段(自动化)",
        "DELETE FROM eb_store_seckill_manger WHERE "
        f"({_name(_AUTO)} OR name {_BATCH}) AND name NOT LIKE 'seed_%'",
    ),
    (
        "秒杀时段(重复时段)",
        "DELETE m1 FROM eb_store_seckill_manger m1 "
        "INNER JOIN eb_store_seckill_manger m2 "
        "ON m1.start_time = m2.start_time AND m1.end_time = m2.end_time AND m1.id < m2.id",
    ),
    (
        "组合数据",
        "DELETE gd FROM eb_system_group_data gd "
        "INNER JOIN eb_system_group g ON gd.gid = g.id "
        f"WHERE g.name {_AUTO} OR g.name {_BATCH}",
    ),
    (
        "数据分组",
        f"DELETE FROM eb_system_group WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "表单模板",
        "DELETE FROM eb_system_form_temp WHERE "
        f"(({_name(_AUTO, _BATCH)}) OR info = 'autotest') AND name NOT LIKE 'seed_%'",
    ),
    (
        "文章",
        f"DELETE FROM eb_article WHERE {_title(_AUTO, _BATCH)} OR title = 't1'",
    ),
    (
        "分类",
        f"DELETE FROM eb_category WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "DIY页面",
        f"DELETE FROM eb_page_diy WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "活动样式",
        f"DELETE FROM eb_activity_style WHERE {_name(_AUTO, _BATCH, _VERIFY)}",
    ),
    (
        "商品规格模板",
        "DELETE FROM eb_store_product_rule WHERE "
        f"rule_name {_AUTO} OR rule_name {_BATCH} OR rule_name LIKE 'batch_productrule_%'",
    ),
    (
        "用户分组",
        "DELETE FROM eb_user_group WHERE "
        "(group_name LIKE 'grp_%' OR group_name LIKE 'batch_usergroup_%') "
        "AND group_name NOT LIKE 'seed_%'",
    ),
    (
        "用户标签",
        "DELETE FROM eb_user_tag WHERE "
        "(name LIKE 'tag_%' OR name LIKE 'batch_usertag_%' OR name LIKE 'verify_%') "
        "AND name NOT LIKE 'seed_%'",
    ),
    (
        "会员等级",
        f"DELETE FROM eb_system_user_level WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "微信回复",
        "DELETE FROM eb_wechat_reply WHERE keywords LIKE 'seed_kw_%' "
        "OR keywords LIKE 'kw_%' OR keywords LIKE 'batch_%'",
    ),
    (
        "门店",
        "DELETE FROM eb_system_store WHERE "
        f"(({_name(_AUTO, _BATCH, _VERIFY)}) OR name LIKE 'verify_store_%') "
        "AND name NOT LIKE 'seed_%'",
    ),
    (
        "店员",
        f"DELETE FROM eb_system_store_staff WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "测试管理员",
        "DELETE FROM eb_system_admin WHERE id > 1 AND ("
        "account LIKE 'auto_account_%' OR account LIKE 'batch_systemadmin_%' "
        "OR account REGEXP '^u[0-9a-fA-F]+$'"
        ")",
    ),
    (
        "测试角色",
        "DELETE FROM eb_system_role WHERE "
        "(role_name LIKE 'role_%' OR role_name LIKE 'batch_systemrole_%') "
        "AND role_name NOT LIKE 'seed_%'",
    ),
    (
        "测试优惠券",
        f"DELETE FROM eb_store_coupon WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "运费模板",
        f"DELETE FROM eb_shipping_templates WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "测试菜单",
        "DELETE FROM eb_system_menu WHERE "
        f"{_name(_AUTO, _BATCH)} OR perms LIKE 'autotest:%'",
    ),
    (
        "快递公司",
        f"DELETE FROM eb_express WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "城市",
        f"DELETE FROM eb_system_city WHERE {_name(_AUTO, _BATCH)}",
    ),
    (
        "附件",
        f"DELETE FROM eb_system_attachment WHERE {_name(_AUTO, _BATCH)}",
    ),
]


def should_run_cleanup() -> bool:
    return os.getenv("SKIP_CLEANUP", "").lower() not in ("1", "true", "yes")


def run_cleanup() -> Dict[str, int]:
    """执行 SQL 清理，返回各模块删除行数（失败项为 -1）。"""
    CrmebDb.clear_cache()
    results: Dict[str, int] = {}
    conn = CrmebDb._connect()
    try:
        with conn.cursor() as cur:
            for label, sql in CLEANUP_STATEMENTS:
                try:
                    affected = cur.execute(sql)
                    conn.commit()
                    results[label] = affected
                    if affected:
                        logger.info(f"清理 {label}: 删除 {affected} 行")
                except Exception as exc:
                    conn.rollback()
                    logger.warning(f"清理 {label} 跳过: {exc}")
                    results[label] = -1
    finally:
        conn.close()

    CrmebDb.clear_cache()
    return results


def cleanup_summary(results: Dict[str, int]) -> str:
    total = sum(v for v in results.values() if v > 0)
    lines = [f"共删除 {total} 行"]
    for label, n in sorted(results.items()):
        if n > 0:
            lines.append(f"  {label}: {n}")
    skipped = [k for k, v in results.items() if v < 0]
    if skipped:
        lines.append(f"跳过 {len(skipped)} 项（见日志）")
    return "\n".join(lines)
