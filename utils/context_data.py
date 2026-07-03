"""场景执行上下文：仅在初始化阶段查库，用例执行只读本模块绑定的 context。"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from utils.db_helper import DB_PLACEHOLDER_ALIAS

_ctx: ContextVar[Dict[str, Any]] = ContextVar("scenario_context", default={})

# Session 级可变状态（跨场景共享，避免 deepcopy 后时段/店员 uid 撞车）
_SESSION_SECKILL_HOURS: set[int] = set()
_SESSION_STAFF_UIDS: set[int] = set()
_SESSION_USER_LEVEL_GRADE: int = 0
_SESSION_USER_LEVEL_EXP: int = 0
_SESSION_USER_LEVEL_SEQ: int = 0


def reset_session_runtime_state() -> None:
    """initialize_test_environment 开始时清空。"""
    _SESSION_SECKILL_HOURS.clear()
    _SESSION_STAFF_UIDS.clear()
    global _SESSION_USER_LEVEL_GRADE, _SESSION_USER_LEVEL_EXP, _SESSION_USER_LEVEL_SEQ
    _SESSION_USER_LEVEL_GRADE = 0
    _SESSION_USER_LEVEL_EXP = 0
    _SESSION_USER_LEVEL_SEQ = 0

# module -> 初始化写入 context 的主实体 key（与 db_helper.DB_QUERIES 一致）
MODULE_ENTITY_KEY: Dict[str, str] = {
    "activitystyle": "activity_style_id",
    "article": "article_id",
    "category": "cate_id",
    "express": "express_id",
    "pagediy": "pagediy_id",
    "product": "product_id",
    "storeproductrule": "product_rule_id",
    "schedulejob": "schedule_job_id",
    "shippingtemplates": "shipping_template_id",
    "storebargain": "bargain_id",
    "storecombination": "combination_id",
    "storecoupon": "coupon_id",
    "storeseckill": "seckill_id",
    "storeseckillmanger": "seckill_time_id",
    "systemadmin": "admin_id",
    "systemattachment": "attachment_id",
    "systemcity": "city_id",
    "systemformtemp": "form_id",
    "systemuserlevel": "user_level_id",
    "userextract": "extract_id",
    "systemgroup": "auto_system_group_id",
    "systemgroupdata": "group_data_id",
    "systemmenu": "menu_id",
    "systemnotification": "notification_id",
    "systemrole": "role_id",
    "systemstore": "store_id",
    "systemstorestaff": "latest_staff_id",
    "user": "user_uid",
    "usergroup": "user_group_id",
    "usertag": "user_tag_id",
    "wechatreply": "wechat_reply_id",
}


def bind_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ctx = dict(context or {})
    _ctx.set(ctx)
    return ctx


def get_bound_context() -> Dict[str, Any]:
    return _ctx.get()


def ctx_get(db_key: str, default: str = "") -> str:
    ctx = _ctx.get()
    for alias, key in DB_PLACEHOLDER_ALIAS.items():
        if key == db_key:
            val = ctx.get(alias)
            if val not in (None, ""):
                return str(val)
    val = ctx.get(db_key)
    if val not in (None, ""):
        return str(val)
    return default


def ctx_int(db_key: str, default: int = 0) -> int:
    text = ctx_get(db_key, "")
    return int(text) if str(text).isdigit() else default


def ctx_get_from(context: Dict[str, Any], db_key: str, default: str = "") -> str:
    for alias, key in DB_PLACEHOLDER_ALIAS.items():
        if key == db_key:
            val = context.get(alias)
            if val not in (None, ""):
                return str(val)
    val = context.get(db_key)
    if val not in (None, ""):
        return str(val)
    return default


def ctx_resolve_entity_id(context: Optional[Dict[str, Any]], module: str = "") -> Optional[int]:
    ctx = context or {}
    for key in ("entity_id", "id"):
        val = ctx.get(key)
        if val is not None and str(val).strip().isdigit() and int(val) > 0:
            return int(val)
    if module:
        mod = module.lower()
        db_key = MODULE_ENTITY_KEY.get(mod)
        if db_key:
            eid = ctx_get_from(ctx, db_key, "")
            if eid.isdigit() and int(eid) > 0:
                return int(eid)
    return None


def ctx_pop_staff_uid() -> int:
    ctx = _ctx.get()
    pool: List[Any] = list(ctx.get("_staff_uid_pool") or [])
    while pool:
        uid = int(pool.pop(0))
        ctx["_staff_uid_pool"] = pool
        if uid > 0 and uid not in _SESSION_STAFF_UIDS and not _is_staff_uid(uid):
            _SESSION_STAFF_UIDS.add(uid)
            return uid
    for uid in _query_fresh_staff_uids(limit=50):
        if uid not in _SESSION_STAFF_UIDS:
            _SESSION_STAFF_UIDS.add(uid)
            return uid
    fallback = ctx_int("fresh_staff_uid", 0)
    if fallback > 0 and fallback not in _SESSION_STAFF_UIDS and not _is_staff_uid(fallback):
        _SESSION_STAFF_UIDS.add(fallback)
        return fallback
    return 0


def _is_staff_uid(uid: int) -> bool:
    if uid <= 0:
        return True
    try:
        from utils.db_helper import CrmebDb

        conn = CrmebDb._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM eb_system_store_staff WHERE uid=%s LIMIT 1",
                    (uid,),
                )
                return bool(cur.fetchone())
        finally:
            conn.close()
    except Exception:
        return False


def _query_fresh_staff_uids(*, limit: int = 50) -> List[int]:
    try:
        from utils.db_helper import CrmebDb

        conn = CrmebDb._connect()
        uids: List[int] = []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT u.uid FROM eb_user u LEFT JOIN eb_system_store_staff s ON u.uid=s.uid "
                    "WHERE s.uid IS NULL ORDER BY u.uid DESC LIMIT %s",
                    (limit,),
                )
                for row in cur.fetchall() or []:
                    uid = int(next(iter(row.values())) or 0)
                    if uid > 0:
                        uids.append(uid)
        finally:
            conn.close()
        return uids
    except Exception:
        return []


def ctx_mark_staff_uid(uid: int) -> None:
    if uid > 0:
        _SESSION_STAFF_UIDS.add(int(uid))


def ctx_mark_seckill_hour(time_range: str) -> None:
    try:
        start_h = int(str(time_range).split(",")[0].split(":")[0])
        _SESSION_SECKILL_HOURS.add(start_h)
    except (ValueError, IndexError):
        pass


def ctx_next_seckill_time_range(*, exclude_id: Optional[int] = None) -> str:
    ctx = _ctx.get()
    db_occupied = set(int(x) for x in (ctx.get("_seckill_occupied_hours") or []) if str(x).isdigit())
    occupied = db_occupied | _SESSION_SECKILL_HOURS
    time_map: Dict[str, str] = dict(ctx.get("_seckill_time_by_id") or {})
    if exclude_id and str(exclude_id) in time_map:
        part = time_map[str(exclude_id)].split(",")[0]
        try:
            occupied.add(int(part.split(":")[0]))
        except ValueError:
            pass
    idx = int(ctx.get("_seckill_hour_idx") or 0)
    for h in range(idx, 23):
        if h not in occupied and (h + 1) <= 23:
            ctx["_seckill_hour_idx"] = h + 1
            _SESSION_SECKILL_HOURS.add(h)
            return f"{h:02d}:00,{(h + 1):02d}:00"
    for h in range(23):
        if h not in occupied and (h + 1) <= 23:
            _SESSION_SECKILL_HOURS.add(h)
            return f"{h:02d}:00,{(h + 1):02d}:00"
    return "22:00,23:00"


def ctx_seckill_time_for(entity_id: int) -> str:
    time_map: Dict[str, str] = dict(_ctx.get().get("_seckill_time_by_id") or {})
    return time_map.get(str(entity_id), "08:00,09:00")


def sync_seckill_session_from_context(context: Dict[str, Any]) -> None:
    """init 结束后将 DB/bootstrap 已占用秒杀小时写入 session，避免 save 撞时段。"""
    for h in context.get("_seckill_occupied_hours") or []:
        try:
            hour = int(h)
        except (TypeError, ValueError):
            continue
        _SESSION_SECKILL_HOURS.add(hour)
    for tr in (context.get("_seckill_ranges_by_idx") or []):
        ctx_mark_seckill_hour(str(tr))
    for tr in (context.get("_seckill_time_by_id") or {}).values():
        ctx_mark_seckill_hour(str(tr))


def ctx_next_user_level_grade() -> tuple[int, int]:
    """每条 save 递增 grade/experience，满足「高于上一级、低于下一级」经验约束。"""
    global _SESSION_USER_LEVEL_GRADE, _SESSION_USER_LEVEL_EXP, _SESSION_USER_LEVEL_SEQ
    rows: List[tuple[int, int]] = []
    try:
        from utils.db_helper import CrmebDb

        conn = CrmebDb._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT grade, experience FROM eb_system_user_level "
                    "WHERE is_del=0 ORDER BY grade ASC"
                )
                for row in cur.fetchall() or []:
                    g = int(row.get("grade") or 0)
                    e = int(row.get("experience") or 0)
                    if g > 0:
                        rows.append((g, e))
        finally:
            conn.close()
    except Exception:
        rows = []

    _SESSION_USER_LEVEL_SEQ += 1
    seq = _SESSION_USER_LEVEL_SEQ
    max_grade = rows[-1][0] if rows else 0
    grade = max_grade + seq
    prev_exp = max((e for g, e in rows if g < grade), default=0)
    next_candidates = [e for g, e in rows if g > grade]
    next_exp = min(next_candidates) if next_candidates else None
    experience = prev_exp + 1000 * seq
    if experience <= prev_exp:
        experience = prev_exp + 1000
    if next_exp is not None and experience >= next_exp:
        experience = max(prev_exp + 1, next_exp - 1)
    _SESSION_USER_LEVEL_GRADE = grade
    _SESSION_USER_LEVEL_EXP = experience
    return grade, experience
