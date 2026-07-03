"""从 CRMEB MySQL 读取测试所需的真实业务 ID。"""
from typing import Any, Dict, Optional

import pymysql
from pymysql.cursors import DictCursor

from config.config import Config

# key -> SQL（关键测试数据从库读取）
DB_QUERIES: Dict[str, str] = {
    "product_id": (
        "SELECT id FROM eb_store_product WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "product_off_shelf_id": (
        "SELECT id FROM eb_store_product WHERE is_del=0 AND is_show=0 ORDER BY id DESC LIMIT 1"
    ),
    "product_on_shelf_id": (
        "SELECT id FROM eb_store_product WHERE is_del=0 AND is_show=1 ORDER BY id DESC LIMIT 1"
    ),
    "product_delete_id": (
        "SELECT id FROM eb_store_product WHERE is_del=0 AND is_show=0 ORDER BY id DESC LIMIT 1"
    ),
    "order_id": (
        "SELECT id FROM eb_store_order WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "order_no": (
        "SELECT order_id FROM eb_store_order WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "user_uid": (
        "SELECT uid FROM eb_user ORDER BY uid DESC LIMIT 1"
    ),
    "user_delete_uid": (
        "SELECT uid FROM eb_user ORDER BY uid DESC LIMIT 1"
    ),
    # --- 场景串联常用 ---
    "cate_id": (
        "SELECT id FROM eb_category WHERE status=1 ORDER BY id DESC LIMIT 1"
    ),
    "temp_id": (
        "SELECT id FROM eb_system_form_temp ORDER BY id DESC LIMIT 1"
    ),
    "coupon_ids": (
        "SELECT IFNULL(GROUP_CONCAT(id), '') FROM ("
        "SELECT id FROM eb_store_coupon WHERE status=1 ORDER BY id DESC LIMIT 3"
        ") t"
    ),
    "express_id": (
        "SELECT id FROM eb_express ORDER BY id DESC LIMIT 1"
    ),
    "article_cid": (
        "SELECT id FROM eb_category WHERE type=3 AND status=1 ORDER BY id DESC LIMIT 1"
    ),
    "article_id": (
        "SELECT id FROM eb_article ORDER BY id DESC LIMIT 1"
    ),
    "shipping_template_id": (
        "SELECT id FROM eb_shipping_templates ORDER BY id DESC LIMIT 1"
    ),
    "store_id": (
        "SELECT id FROM eb_system_store WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "role_id": (
        "SELECT id FROM eb_system_role ORDER BY id DESC LIMIT 1"
    ),
    "admin_id": (
        "SELECT id FROM eb_system_admin ORDER BY id DESC LIMIT 1"
    ),
    "user_group_id": (
        "SELECT id FROM eb_user_group ORDER BY id DESC LIMIT 1"
    ),
    "user_tag_id": (
        "SELECT id FROM eb_user_tag ORDER BY id DESC LIMIT 1"
    ),
    "bargain_id": (
        "SELECT id FROM eb_store_bargain WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "combination_id": (
        "SELECT id FROM eb_store_combination WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "seckill_id": (
        "SELECT id FROM eb_store_seckill WHERE is_del=0 ORDER BY id DESC LIMIT 1"
    ),
    "product_rule_value": (
        "SELECT rule_value FROM eb_store_product_rule WHERE rule_value IS NOT NULL "
        "AND rule_value <> '' ORDER BY id DESC LIMIT 1"
    ),
    "product_rule_id": (
        "SELECT id FROM eb_store_product_rule ORDER BY id DESC LIMIT 1"
    ),
    "latest_product_rule_id": (
        "SELECT id FROM eb_store_product_rule WHERE rule_name LIKE 'auto_%' "
        "ORDER BY id DESC LIMIT 1"
    ),
    "mer_id": (
        "SELECT IFNULL(MIN(id), 0) FROM eb_system_store WHERE is_del=0"
    ),
    "category_parent_id": (
        "SELECT pid FROM eb_category WHERE type=1 AND status=1 AND pid>0 "
        "ORDER BY id DESC LIMIT 1"
    ),
    "article_cover_image": (
        "SELECT satt_dir FROM eb_system_attachment WHERE satt_dir IS NOT NULL "
        "AND satt_dir <> '' ORDER BY att_id DESC LIMIT 1"
    ),
    "form_id": (
        "SELECT id FROM eb_system_form_temp WHERE name LIKE 'seed_%' "
        "OR content LIKE '%__vModel__%' ORDER BY id DESC LIMIT 1"
    ),
    "form_content": (
        "SELECT content FROM eb_system_form_temp WHERE content IS NOT NULL "
        "AND content <> '' ORDER BY id DESC LIMIT 1"
    ),
    "system_group_id": (
        "SELECT COALESCE("
        "(SELECT g.id FROM eb_system_group g "
        "INNER JOIN eb_system_group_data d ON g.id = d.gid "
        "WHERE g.name LIKE 'seed_%' ORDER BY d.id DESC LIMIT 1), "
        "(SELECT id FROM eb_system_group WHERE name LIKE 'seed_%' ORDER BY id DESC LIMIT 1), "
        "(SELECT gid FROM eb_system_group_data ORDER BY id DESC LIMIT 1), "
        "(SELECT id FROM eb_system_group ORDER BY id DESC LIMIT 1)"
        ")"
    ),
    "latest_system_group_id": (
        "SELECT id FROM eb_system_group ORDER BY id DESC LIMIT 1"
    ),
    "auto_system_group_id": (
        "SELECT id FROM eb_system_group WHERE name LIKE 'auto_%' ORDER BY id DESC LIMIT 1"
    ),
    "schedule_job_id": (
        "SELECT job_id FROM eb_schedule_job ORDER BY job_id DESC LIMIT 1"
    ),
    "attachment_id": (
        "SELECT att_id FROM eb_system_attachment ORDER BY att_id DESC LIMIT 1"
    ),
    "extract_id": (
        "SELECT id FROM eb_user_extract ORDER BY id DESC LIMIT 1"
    ),
    "city_parent_id": (
        "SELECT city_id FROM eb_system_city WHERE parent_id = 0 ORDER BY city_id LIMIT 1"
    ),
    "notification_id": (
        "SELECT id FROM eb_system_notification ORDER BY id DESC LIMIT 1"
    ),
    "role_ids": (
        "SELECT CAST(id AS CHAR) FROM eb_system_role ORDER BY id LIMIT 1"
    ),
    "coupon_id": (
        "SELECT id FROM eb_store_coupon ORDER BY id DESC LIMIT 1"
    ),
    "seckill_time_id": (
        "SELECT id FROM eb_store_seckill_manger ORDER BY id DESC LIMIT 1"
    ),
    "city_id": (
        "SELECT id FROM eb_system_city WHERE parent_id > 0 AND is_show=1 ORDER BY id DESC LIMIT 1"
    ),
    "city_row_parent_id": (
        "SELECT parent_id FROM eb_system_city WHERE id = "
        "(SELECT id FROM eb_system_city WHERE parent_id > 0 AND is_show=1 ORDER BY id DESC LIMIT 1)"
    ),
    "menu_id": (
        "SELECT id FROM eb_system_menu ORDER BY id DESC LIMIT 1"
    ),
    "latest_menu_id": (
        "SELECT id FROM eb_system_menu WHERE name LIKE 'auto_%' ORDER BY id DESC LIMIT 1"
    ),
    "staff_id": (
        "SELECT id FROM eb_system_store_staff ORDER BY id DESC LIMIT 1"
    ),
    "latest_staff_id": (
        "SELECT id FROM eb_system_store_staff ORDER BY id DESC LIMIT 1"
    ),
    "fresh_staff_uid": (
        "SELECT u.uid FROM eb_user u LEFT JOIN eb_system_store_staff s ON u.uid=s.uid "
        "WHERE s.uid IS NULL ORDER BY u.uid DESC LIMIT 1"
    ),
    "role_rules": (
        "SELECT rules FROM eb_system_role WHERE rules IS NOT NULL AND rules <> '' "
        "ORDER BY id LIMIT 1"
    ),
    "staff_uid": (
        "SELECT u.uid FROM eb_user u LEFT JOIN eb_system_store_staff s ON u.uid=s.uid "
        "WHERE s.uid IS NULL ORDER BY u.uid DESC LIMIT 1"
    ),
    "next_user_grade": (
        "SELECT IFNULL(MAX(grade), 0) + 1 FROM eb_system_user_level"
    ),
    "next_user_experience": (
        "SELECT IFNULL(MAX(experience), 0) + 100 FROM eb_system_user_level"
    ),
    "wechat_reply_id": (
        "SELECT id FROM eb_wechat_reply ORDER BY id DESC LIMIT 1"
    ),
    "wechat_reply_keywords": (
        "SELECT keywords FROM eb_wechat_reply WHERE keywords IS NOT NULL "
        "AND keywords <> '' ORDER BY id DESC LIMIT 1"
    ),
    "pagediy_id": (
        "SELECT id FROM eb_page_diy ORDER BY id DESC LIMIT 1"
    ),
    "activity_style_id": (
        "SELECT id FROM eb_activity_style ORDER BY id DESC LIMIT 1"
    ),
    "group_data_id": (
        "SELECT id FROM eb_system_group_data ORDER BY id DESC LIMIT 1"
    ),
    "user_level_id": (
        "SELECT id FROM eb_system_user_level ORDER BY id DESC LIMIT 1"
    ),
    "group_form_id": (
        "SELECT form_id FROM eb_system_group WHERE id = "
        "(SELECT id FROM eb_system_group ORDER BY id DESC LIMIT 1)"
    ),
    "notification_wechat_id": (
        "SELECT id FROM eb_system_notification WHERE is_wechat > 0 ORDER BY id LIMIT 1"
    ),
    "notification_routine_id": (
        "SELECT id FROM eb_system_notification WHERE is_routine > 0 ORDER BY id LIMIT 1"
    ),
    "notification_sms_id": (
        "SELECT id FROM eb_system_notification WHERE is_sms > 0 ORDER BY id LIMIT 1"
    ),
    "wechat_template_temp_id": (
        "SELECT temp_id FROM eb_template_message WHERE status = 1 "
        "AND temp_id IS NOT NULL AND temp_id <> '' ORDER BY id LIMIT 1"
    ),
}

# CSV 占位符 camelCase -> DB key
DB_PLACEHOLDER_ALIAS: Dict[str, str] = {
    "cateId": "cate_id",
    "tempId": "temp_id",
    "couponIds": "coupon_ids",
    "merId": "mer_id",
    "cid": "article_cid",
    "storeId": "store_id",
    "roleId": "role_id",
    "groupId": "user_group_id",
    "tagId": "user_tag_id",
    "labelId": "user_tag_id",
    "uid": "user_uid",
    "jobId": "schedule_job_id",
    "attId": "attachment_id",
    "shippingTemplateId": "shipping_template_id",
    "productId": "product_id",
    "parentId": "city_parent_id",
}


class CrmebDb:
    """会话级缓存，避免同 key 重复查库。"""

    _cache: Dict[str, str] = {}

    @classmethod
    def get(cls, key: str) -> str:
        if key in cls._cache:
            return cls._cache[key]
        sql = DB_QUERIES.get(key)
        if not sql:
            raise KeyError(f"未知 DB 占位符：DB:{key}")
        value = cls._query_scalar(sql)
        if value is None or value == "":
            raise RuntimeError(
                f"CRMEB 库无可用数据，占位符 DB:{key}，SQL：{sql}"
            )
        cls._cache[key] = str(value)
        return cls._cache[key]

    @classmethod
    def get_optional(cls, key: str, default: str = "") -> str:
        try:
            return cls.get(key)
        except Exception:
            return default

    @classmethod
    def resolve_placeholder(cls, name: str) -> Optional[str]:
        """解析 ${cateId} 等 camelCase 占位符。"""
        db_key = DB_PLACEHOLDER_ALIAS.get(name)
        if db_key:
            return cls.get(db_key)
        if name in DB_QUERIES:
            return cls.get(name)
        return None

    @classmethod
    def get_fresh(cls, key: str, default: str = "") -> str:
        """绕过缓存读取最新值（save 后回填 entity_id）。"""
        cls._cache.pop(key, None)
        return cls.get_optional(key, default)

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    def get_wechat_reply_id_by_keywords(cls, keywords: str) -> str:
        if not keywords:
            return ""
        conn = cls._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM eb_wechat_reply WHERE keywords = %s ORDER BY id DESC LIMIT 1",
                    (keywords,),
                )
                row = cur.fetchone()
                if row:
                    val = str(next(iter(row.values())))
                    cls._cache["wechat_reply_id"] = val
                    return val
        finally:
            conn.close()
        return ""

    @classmethod
    def execute(cls, sql: str, params: tuple = ()) -> int:
        conn = cls._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(sql, params)
            conn.commit()
            return affected
        finally:
            conn.close()

    @classmethod
    def flush_redis(cls) -> None:
        """清空测试 Redis DB（已禁用：远程未暴露 6379，自动化不直连 Redis）。"""
        return

    @classmethod
    def _connect(cls):
        cfg = Config()
        return pymysql.connect(
            host=cfg.mysql_host,
            port=cfg.mysql_port,
            user=cfg.mysql_user,
            password=cfg.mysql_password,
            database=cfg.mysql_database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )

    @classmethod
    def get_row(cls, sql: str) -> Dict[str, Any]:
        conn = cls._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchone() or {}
        finally:
            conn.close()

    @classmethod
    def _query_scalar(cls, sql: str) -> Optional[Any]:
        conn = cls._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                if not row:
                    return None
                return next(iter(row.values()))
        finally:
            conn.close()
