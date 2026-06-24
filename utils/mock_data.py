"""Mock 测试数据：非关键字段、运行时动态值。"""
import time
import uuid
from typing import Any, Dict


class MockData:
    """场景用例中的 mock 占位符（非 DB 关键数据）。"""

    _run_id: str = ""

    @classmethod
    def run_id(cls) -> str:
        if not cls._run_id:
            cls._run_id = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
        return cls._run_id

    @classmethod
    def reset(cls) -> None:
        cls._run_id = ""

    @classmethod
    def get(cls, key: str) -> str:
        key_upper = key.upper()
        if key_upper == "RUN_ID":
            return cls.run_id()
        if key_upper == "MOCK_NAME":
            return f"auto_name_{cls.run_id()}"
        if key_upper == "MOCK_TITLE":
            return f"auto_title_{cls.run_id()}"
        if key_upper == "MOCK_CONTENT":
            return "autotest mock content"
        if key_upper == "MOCK_EMPTY":
            return ""
        raise KeyError(f"未知 Mock 占位符：{key}")

    @classmethod
    def base_context(cls) -> Dict[str, Any]:
        rid = cls.run_id()
        return {
            "RUN_ID": rid,
            "MOCK_NAME": f"auto_name_{rid}",
            "MOCK_TITLE": f"auto_title_{rid}",
            "MOCK_CONTENT": "autotest mock content",
        }
