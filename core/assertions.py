import allure
from requests import Response


class ApiAssertions:
    """分层断言：状态码、字段存在、字段值。"""

    @staticmethod
    @allure.step("校验响应状态码")
    def assert_status_code(resp: Response, expect_code: int):
        assert resp.status_code == expect_code, (
            f"状态码错误，期望：{expect_code}，实际：{resp.status_code}"
        )

    @staticmethod
    @allure.step("校验关键字段存在")
    def assert_key_exists(resp: Response, expect_key: str):
        res = resp.json()
        assert expect_key in res, f"缺失字段：{expect_key}"

    @staticmethod
    @allure.step("校验字段精准值")
    def assert_key_equal(resp: Response, key: str, expect_val):
        res = resp.json()
        actual = res.get(key)
        expected = _coerce_value(expect_val, actual)
        assert actual == expected, f"{key} 期望：{expected}，实际：{actual}"

    @staticmethod
    @allure.step("校验响应包含文本")
    def assert_resp_contains(resp: Response, text: str):
        assert text in resp.text, f"响应未包含：{text}"


def _coerce_value(expect_val, actual):
    """将 CSV 中的字符串期望值转为与响应一致的类型。"""
    if isinstance(actual, bool):
        return str(expect_val).lower() in ("true", "1", "yes")
    if isinstance(actual, int):
        try:
            return int(expect_val)
        except (TypeError, ValueError):
            return expect_val
    if isinstance(actual, float):
        try:
            return float(expect_val)
        except (TypeError, ValueError):
            return expect_val
    return expect_val
