import json

import allure
import pytest

from conftest import build_case_params, exec_post_condition, exec_pre_condition, resolve_case
from core.assertions import ApiAssertions
from utils.data_handler import DataHandler

CUR_MODULE = "member"
case_list = DataHandler.get_case_by_module(CUR_MODULE)

severity_map = {
    "high": allure.severity_level.CRITICAL,
    "medium": allure.severity_level.NORMAL,
    "low": allure.severity_level.MINOR,
}


@allure.feature(f"{CUR_MODULE} 业务模块接口")
class TestApiMember:
    @pytest.mark.parametrize("case", build_case_params(case_list))
    def test_api_case(self, api_client, case):
        allure.dynamic.id(case["test_case_id"])
        allure.dynamic.title(case["test_case_name"])
        allure.dynamic.story(case["api_name"])
        allure.dynamic.description(case["description"])
        allure.dynamic.severity(severity_map.get(case["priority"], allure.severity_level.NORMAL))

        tag_list = [t.strip() for t in case["tags"].split(",") if t.strip()]
        if tag_list:
            allure.dynamic.tag(*tag_list)

        exec_pre_condition(case["preconditions"], api_client)

        case = resolve_case(case)

        headers_raw = case["headers"] or "{}"
        req_raw = case["request_data"] or "{}"

        try:
            headers = json.loads(headers_raw) if headers_raw else {}
        except json.JSONDecodeError:
            headers = {}
        try:
            req_data = json.loads(req_raw) if req_raw else {}
        except json.JSONDecodeError:
            req_data = {}

        with allure.step(f"{case['method']} 请求：{case['url']}"):
            resp = api_client.request(
                method=case["method"],
                url=case["url"],
                headers=headers,
                data=req_data,
                content_type=case["content_type"],
            )

        ApiAssertions.assert_status_code(resp, int(case["expected_status_code"]))

        if case["expected_key_assert"]:
            for key in (k.strip() for k in case["expected_key_assert"].split(",") if k.strip()):
                ApiAssertions.assert_key_exists(resp, key)

        if case["expected_value_assert"]:
            for pair in (p.strip() for p in case["expected_value_assert"].split(",") if "=" in p.strip()):
                k, v = pair.split("=", 1)
                ApiAssertions.assert_key_equal(resp, k.strip(), v.strip())

        exec_post_condition(case["postconditions"], api_client)
