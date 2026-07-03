"""场景执行共用工具（解析、路径提取）。"""
import json
import re
from typing import Any, Optional

_UNRESOLVED = re.compile(r"^\$\{[^}]+\}$")


def normalize_path(path: str) -> str:
    return re.sub(r"\[(\d+)\]", r".\1", path.strip())


def extract_by_path(root: Any, path: str) -> Any:
    """支持 response.data.list[0].id；列表直出时自动回退为 response.data[0].id。"""
    candidates = [path]
    if ".list[" in path or ".list." in path:
        candidates.append(re.sub(r"\.list(?=\[|\.)", "", path))
    last_exc: Optional[Exception] = None
    for candidate in candidates:
        try:
            cur = root
            for part in normalize_path(candidate).split("."):
                if not part:
                    continue
                if part.isdigit():
                    cur = cur[int(part)]
                else:
                    cur = cur[part]
            return cur
        except (KeyError, IndexError, TypeError) as exc:
            last_exc = exc
            continue
    if last_exc:
        raise last_exc
    raise KeyError(path)


def parse_json(raw: str, default: Any) -> Any:
    raw = (raw or "").strip()
    if not raw or raw == "{}":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def sanitize_payload(data: Any) -> Any:
    """未解析占位符：id 类置 0，其余省略。"""
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if isinstance(value, str) and _UNRESOLVED.match(value):
                if key.lower() in ("id", "entity_id", "cid", "pid", "cateid", "tempid"):
                    cleaned[key] = 0
                continue
            cleaned[key] = sanitize_payload(value)
        return cleaned
    if isinstance(data, list):
        return [sanitize_payload(v) for v in data]
    return data
