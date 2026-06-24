import os
import re
from typing import Any, Dict, Optional

from utils.mock_data import MockData


class VarRender:
    """动态变量渲染：${ENV}、${DB:key}、场景 context、DB 别名、Mock。"""

    _pattern = re.compile(r"\$\{([^}]+)\}")

    @staticmethod
    def render_params(data: str, context: Optional[Dict[str, Any]] = None) -> str:
        if not data:
            return data
        context = context or {}

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key in context and context[key] is not None:
                return str(context[key])
            if key.startswith("DB:"):
                from utils.db_helper import CrmebDb

                return CrmebDb.get(key[3:])
            from utils.db_helper import CrmebDb

            db_val = CrmebDb.resolve_placeholder(key)
            if db_val is not None:
                return db_val
            try:
                return MockData.get(key)
            except KeyError:
                pass
            env_val = os.getenv(key)
            if env_val is not None:
                return env_val
            return match.group(0)

        return VarRender._pattern.sub(_replace, data)

    @staticmethod
    def render_dict(data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """递归渲染字典中的字符串占位符。"""
        context = context or {}
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = VarRender.render_params(value, context)
            elif isinstance(value, dict):
                result[key] = VarRender.render_dict(value, context)
            else:
                result[key] = value
        return result
