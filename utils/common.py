import os


def get_project_root() -> str:
    """返回 api_autotest 项目根目录。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
