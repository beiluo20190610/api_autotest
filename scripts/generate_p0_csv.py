"""根据 specs/admin-api.plan.md 生成 P0 冒烟 CSV 用例。"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HEADER = [
    "test_case_id", "test_case_name", "module", "api_name", "method", "url",
    "content_type", "headers", "request_data", "preconditions", "postconditions",
    "expected_status_code", "expected_key_assert", "expected_value_assert",
    "test_type", "priority", "tags", "description",
]

TOKEN_HDR = '{"Authori-zation":"${COMMON_TOKEN}"}'
EMPTY_HDR = "{}"


def row(
    case_id, name, module, api_name, method, url,
    content_type="json", headers=EMPTY_HDR, request_data="{}",
    pre="无", post="无", status=200, keys="code,data", values="code=200",
    test_type="positive", priority="high", tags="smoke", desc="",
):
    return {
        "test_case_id": case_id,
        "test_case_name": name,
        "module": module,
        "api_name": api_name,
        "method": method,
        "url": url,
        "content_type": content_type,
        "headers": headers,
        "request_data": request_data,
        "preconditions": pre,
        "postconditions": post,
        "expected_status_code": str(status),
        "expected_key_assert": keys,
        "expected_value_assert": values,
        "test_type": test_type,
        "priority": priority,
        "tags": tags,
        "description": desc or name,
    }


def gen_admin():
    cases = []
    cases.append(row(
        "API-ADMIN-001", "正确账号密码登录成功", "admin", "AdminUserLogin", "POST",
        "/api/admin/login",
        request_data='{"account":"${LOGIN_USER}","pwd":"${LOGIN_PASS}"}',
        tags="smoke,admin,login",
    ))
    cases.append(row(
        "API-ADMIN-002", "登录账号为空失败", "admin", "AdminUserLogin", "POST",
        "/api/admin/login",
        request_data='{"account":"","pwd":"123456"}',
        keys="code,message", values="code=500",
        test_type="negative", priority="medium", tags="admin,login",
    ))
    cases.append(row(
        "API-ADMIN-003", "登录密码5位边界失败", "admin", "AdminUserLogin", "POST",
        "/api/admin/login",
        request_data='{"account":"admin","pwd":"12345"}',
        keys="code,message", values="code=500",
        test_type="boundary", priority="low", tags="admin,login,boundary",
    ))
    cases.append(row(
        "API-ADMIN-004", "错误密码登录失败", "admin", "AdminUserLogin", "POST",
        "/api/admin/login",
        request_data='{"account":"${LOGIN_USER}","pwd":"wrong_pass_123"}',
        keys="code", values="code=500",
        test_type="negative", priority="medium", tags="admin,login",
    ))
    cases.append(row(
        "API-ADMIN-005", "携带Token登出成功", "admin", "AdminUserLogout", "GET",
        "/api/admin/logout", headers=TOKEN_HDR, pre="已登录", post="清除Token",
        tags="smoke,admin",
    ))
    cases.append(row(
        "API-ADMIN-006", "未登录登出返回401", "admin", "AdminUserLogout", "GET",
        "/api/admin/logout",
        keys="code", values="code=401",
        test_type="negative", priority="medium", tags="admin",
    ))
    cases.append(row(
        "API-ADMIN-007", "Token获取管理员信息成功", "admin", "GetAdminUserByToken", "GET",
        "/api/admin/getAdminInfoByToken", headers=TOKEN_HDR, pre="已登录",
        tags="smoke,admin",
    ))
    cases.append(row(
        "API-ADMIN-008", "无Token获取管理员信息失败", "admin", "GetAdminUserByToken", "GET",
        "/api/admin/getAdminInfoByToken",
        keys="code", values="code=401",
        test_type="negative", priority="medium", tags="admin",
    ))
    cases.append(row(
        "API-ADMIN-009", "获取登录页图片成功", "admin", "获取登录页图片", "GET",
        "/api/admin/getLoginPic", tags="smoke,admin",
    ))
    cases.append(row(
        "API-ADMIN-010", "无Token获取登录页图片", "admin", "获取登录页图片", "GET",
        "/api/admin/getLoginPic", tags="admin",
        test_type="positive", priority="medium",
    ))
    return cases


def gen_list_module(module, prefix, apis, auth=True):
    """apis: [(api_name, method, pos_url, neg_url, skip_positive)]"""
    cases = []
    seq = 1
    for item in apis:
        api_name, method, pos_url = item[0], item[1], item[2]
        neg_url = item[3] if len(item) > 3 and item[3] is not None else pos_url
        skip_positive = item[4] if len(item) > 4 else False
        cid = f"API-{prefix}-{seq:03d}"
        pos_tags = f"{module},skip_env" if skip_positive else f"smoke,{module}"
        cases.append(row(
            cid, f"{api_name}正向查询成功", module, api_name, method, pos_url,
            headers=TOKEN_HDR if auth else EMPTY_HDR,
            pre="已登录" if auth else "无",
            tags=pos_tags,
        ))
        seq += 1
        cid = f"API-{prefix}-{seq:03d}"
        cases.append(row(
            cid, f"{api_name}未登录访问失败", module, api_name, method, neg_url,
            keys="code", values="code=401",
            test_type="negative", priority="medium", tags=module,
        ))
        seq += 1
        if method == "GET" and "list" in pos_url:
            list_path = pos_url.split("?", 1)[0]
            boundary_url = pos_url.replace("limit=10", "limit=1").replace("limit=20", "limit=1")
            if boundary_url == pos_url:
                boundary_url = list_path + "?page=1&limit=1"
            cid = f"API-{prefix}-{seq:03d}"
            cases.append(row(
                cid, f"{api_name}分页参数边界", module, api_name, method,
                boundary_url,
                headers=TOKEN_HDR,
                pre="已登录",
                test_type="boundary", priority="low",
                tags=f"{module},boundary",
            ))
            seq += 1
    return cases


# Playwright 探针确认：商品列表必须带 type；删除/上下架等 ID 用 ${DB:...}
PRODUCT_APIS = [
    ("商品分页列表", "GET", "/api/admin/store/product/list?page=1&limit=10&type=1"),
    ("商品TabHeader", "GET", "/api/admin/store/product/tabs/headers"),
    ("商品详情", "GET", "/api/admin/store/product/info/${DB:product_id}", "/api/admin/store/product/info/999999"),
    ("商品上架", "GET", "/api/admin/store/product/putOnShell/${DB:product_off_shelf_id}", "/api/admin/store/product/putOnShell/999999"),
    ("商品下架", "GET", "/api/admin/store/product/offShell/${DB:product_on_shelf_id}", "/api/admin/store/product/offShell/999999"),
    ("商品删除", "GET", "/api/admin/store/product/delete/${DB:product_delete_id}", "/api/admin/store/product/delete/999999"),
    ("商品规则列表", "GET", "/api/admin/store/product/rule/list"),
    ("商品评论列表", "GET", "/api/admin/store/product/reply/list?page=1&limit=10"),
    ("商品更新", "POST", "/api/admin/store/product/update", None, True),
    ("商品保存", "POST", "/api/admin/store/product/save", None, True),
    ("商品导入", "POST", "/api/admin/store/product/importProduct", None, True),
]

ORDER_APIS = [
    ("订单分页列表", "GET", "/api/admin/store/order/list?page=1&limit=10&type=1"),
    ("订单详情", "GET", "/api/admin/store/order/info?orderNo=${DB:order_no}", "/api/admin/store/order/info?orderNo=invalid_order_no"),
    ("订单删除", "GET", "/api/admin/store/order/delete?orderNo=${DB:order_no}", "/api/admin/store/order/delete?orderNo=invalid_order_no", True),
    ("订单发货", "POST", "/api/admin/store/order/send", None, True),
    ("订单备注", "POST", "/api/admin/store/order/mark?orderNo=${DB:order_no}&mark=autotest"),
    ("订单物流信息", "GET", "/api/admin/store/order/getLogisticsInfo?orderNo=${DB:order_no}", "/api/admin/store/order/getLogisticsInfo?orderNo=invalid_order_no", True),
    ("订单退款", "POST", "/api/admin/store/order/refund", None, True),
    ("订单拒绝退款", "POST", "/api/admin/store/order/refund/refuse", None, True),
    ("订单状态列表", "GET", "/api/admin/store/order/status/list"),
]

MEMBER_APIS = [
    ("会员分页列表", "GET", "/api/admin/user/list?page=1&limit=10"),
    ("会员详情", "GET", "/api/admin/user/info?id=${DB:user_uid}", "/api/admin/user/info?id=999999"),
    ("会员Top详情", "GET", "/api/admin/user/topdetail?userId=${DB:user_uid}", "/api/admin/user/topdetail?userId=999999"),
    ("会员条件查询", "GET", "/api/admin/user/infobycondition?userId=${DB:user_uid}&type=1&page=1&limit=10", None, True),
    ("会员更新", "POST", "/api/admin/user/update", None, True),
    ("会员删除", "GET", "/api/admin/user/delete?id=${DB:user_delete_uid}", "/api/admin/user/delete?id=999999", True),
    ("会员积分操作", "GET", "/api/admin/user/operate/founds?uid=${DB:user_uid}&integralType=1&integralValue=1", None, True),
    ("会员分组", "POST", "/api/admin/user/group", None, True),
    ("会员标签", "POST", "/api/admin/user/tag", None, True),
]

# Playwright Dashboard 探针：home/order|sales|views|user 在本环境 404，改用实际路径
STATS_APIS = [
    ("首页统计指标", "GET", "/api/admin/statistics/home/index"),
    ("首页经营数据", "GET", "/api/admin/statistics/home/operating/data"),
    ("用户渠道统计", "GET", "/api/admin/statistics/user/channel"),
    ("用户概览统计", "GET", "/api/admin/statistics/user/overview?dateLimit=lately7"),
    ("30天订单趋势", "GET", "/api/admin/statistics/home/chart/order"),
    ("周订单趋势", "GET", "/api/admin/statistics/home/chart/order/week"),
    ("月订单趋势", "GET", "/api/admin/statistics/home/chart/order/month"),
    ("年订单趋势", "GET", "/api/admin/statistics/home/chart/order/year"),
    ("用户图表", "GET", "/api/admin/statistics/home/chart/user"),
    ("用户购买图表", "GET", "/api/admin/statistics/home/chart/user/buy"),
]


def main():
    cases = []
    cases.extend(gen_admin())
    cases.extend(gen_list_module("product", "PRODUCT", PRODUCT_APIS))
    cases.extend(gen_list_module("order", "ORDER", ORDER_APIS))
    cases.extend(gen_list_module("member", "MEMBER", MEMBER_APIS))
    cases.extend(gen_list_module("statistics", "STATS", STATS_APIS))

    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "test_cases.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(cases)
    print(f"generated {len(cases)} cases -> {out}")


if __name__ == "__main__":
    main()
