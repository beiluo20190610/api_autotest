import os
import re
from typing import Any, Dict, Optional

from utils.context_data import ctx_get_from
from utils.db_helper import DB_PLACEHOLDER_ALIAS
from utils.mock_data import MockData


class VarRender:
    """动态变量渲染：仅从 context / Mock / ENV 取值，运行时不查库。"""

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
                db_key = key[3:]
                val = ctx_get_from(context, db_key, "")
                if val != "":
                    return val
                if db_key in context:
                    return str(context[db_key])
                return match.group(0)
            db_key = DB_PLACEHOLDER_ALIAS.get(key)
            if db_key:
                val = ctx_get_from(context, db_key, "")
                if val != "":
                    return val
            if key in DB_PLACEHOLDER_ALIAS.values() and key in context:
                return str(context[key])
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
