"""部署后快速验证 P0/P1 后端修复是否生效。"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api_client import ApiClient


def main() -> int:
    client = ApiClient()
    account = os.getenv("LOGIN_USER", "admin")
    password = os.getenv("LOGIN_PASS", "123456")
    login_resp = client.request(
        "POST",
        "/api/admin/login",
        data={"account": account, "pwd": password},
        content_type="json",
    )
    token = (login_resp.json().get("data") or {}).get("token", "")
    if not token:
        print("FAIL login", login_resp.text[:200])
        return 1
    headers = {"Authori-zation": token}
    failed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        print(("PASS" if ok else "FAIL"), name, detail)
        if not ok:
            failed += 1

    store_name = f"verify_store_{uuid.uuid4().hex[:8]}"
    store_resp = client.request(
        "POST",
        "/api/admin/system/store/save",
        headers=headers,
        content_type="json",
        data={
            "name": store_name,
            "introduction": "verify",
            "phone": "13800138000",
            "address": "北京市东城区",
            "detailedAddress": "detail",
            "dayTime": "09:00-21:00",
            "image": "/mock/x.png",
            "latitude": "116.407396,39.904200",
            "validTime": "2030-01-01,2030-12-31",
        },
    )
    store_body = store_resp.json()
    store_id = store_body.get("data")
    check(
        "store.save returns id",
        store_body.get("code") == 200 and isinstance(store_id, int) and store_id > 0,
        str(store_id),
    )
    if isinstance(store_id, int):
        list_resp = client.request(
            "GET",
            f"/api/admin/system/store/list?keywords={store_name}&status=1&page=1&limit=5",
            headers=headers,
            content_type="json",
        )
        items = (list_resp.json().get("data") or {}).get("list") or []
        check(
            "store list keywords+status=1",
            any(i.get("name") == store_name for i in items),
            f"items={len(items)}",
        )

    acct = f"u{uuid.uuid4().hex[:10]}"[:16]
    admin_resp = client.request(
        "POST",
        "/api/admin/system/admin/save",
        headers=headers,
        content_type="json",
        data={
            "account": acct,
            "pwd": password,
            "realName": "verify",
            "phone": "13800138002",
            "roles": "1",
            "status": True,
        },
    )
    admin_body = admin_resp.json()
    admin_id = admin_body.get("data")
    check(
        "admin.save returns id",
        admin_body.get("code") == 200 and isinstance(admin_id, int) and admin_id > 0,
        str(admin_id),
    )

    tag_name = f"tag_{uuid.uuid4().hex[:8]}"
    tag_resp = client.request(
        "POST",
        "/api/admin/user/tag/save",
        headers=headers,
        content_type="json",
        data={"name": tag_name},
    )
    tag_body = tag_resp.json()
    tag_id = tag_body.get("data")
    check(
        "tag.save returns id",
        tag_body.get("code") == 200 and isinstance(tag_id, int) and tag_id > 0,
        str(tag_id),
    )
    if isinstance(tag_id, int):
        tag_list = client.request(
            "GET",
            f"/api/admin/user/tag/list?keywords={tag_name}&page=1&limit=5",
            headers=headers,
            content_type="json",
        )
        tag_items = (tag_list.json().get("data") or {}).get("list") or []
        first_name = tag_items[0].get("name") if tag_items else None
        check(
            "tag list keywords on first page",
            bool(tag_items) and first_name == tag_name,
            f"first={first_name}",
        )

    style_list = client.request(
        "GET",
        "/api/admin/activitystyle/list?page=1&limit=1",
        headers=headers,
        content_type="json",
    )
    style_body = style_list.json()
    check(
        "activitystyle list without type",
        style_body.get("code") == 200,
        style_body.get("message", ""),
    )

    print("---")
    print(f"failed={failed}")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
