import os


def get_project_root() -> str:
    """返回 api_autotest 项目根目录。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_dir(path: str) -> str:
    """确保目录存在并返回路径。"""
    os.makedirs(path, exist_ok=True)
    return path
