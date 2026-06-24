import os
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

load_dotenv()


class Config:
    """单例配置：加载 YAML + 环境变量。"""

    _instance = None
    _config_data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._config_data:
            self.load_config()

    def load_config(self):
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            self._config_data = yaml.safe_load(f)

    @property
    def env(self) -> str:
        return os.getenv("TEST_ENV", "test")

    @property
    def base_url(self) -> str:
        return (
            os.getenv("BASE_URL")
            or os.getenv("LOGIN_API_URL")
            or self._config_data["env"][self.env]["base_url"]
        )

    @property
    def login_api_url(self) -> str:
        return (
            os.getenv("BASE_URL")
            or os.getenv("LOGIN_API_URL")
            or self._config_data.get("ui", {}).get("login_api_url", self.base_url)
        )

    @property
    def login_ui_url(self) -> str:
        return os.getenv("LOGIN_UI_URL") or self._config_data.get("ui", {}).get("login_ui_url", "")

    @property
    def login_page_url(self) -> str:
        ui = self.login_ui_url.rstrip("/")
        if not ui:
            return ""
        return f"{ui}/login?redirect=%2Fdashboard"

    @property
    def chromium_executable(self) -> str:
        return os.getenv("CHROMIUM_EXECUTABLE_PATH", "")

    @property
    def global_headers(self) -> Dict[str, str]:
        return self._config_data["headers"]

    @property
    def timeout(self) -> int:
        return self._config_data["env"][self.env]["timeout"]

    @property
    def login_user(self) -> str:
        return os.getenv("LOGIN_USER", "")

    @property
    def login_pass(self) -> str:
        return os.getenv("LOGIN_PASS", "")

    @property
    def common_token(self) -> str:
        return os.getenv("COMMON_TOKEN", "")

    # --- MySQL ---
    @property
    def mysql_host(self) -> str:
        return os.getenv("MYSQL_HOST", "127.0.0.1")

    @property
    def mysql_port(self) -> int:
        return int(os.getenv("MYSQL_PORT", "3306"))

    @property
    def mysql_database(self) -> str:
        return os.getenv("MYSQL_DATABASE", "")

    @property
    def mysql_user(self) -> str:
        return os.getenv("MYSQL_USER", "root")

    @property
    def mysql_password(self) -> str:
        return os.getenv("MYSQL_PASSWORD", "")

    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    # --- Redis ---
    @property
    def redis_host(self) -> str:
        return os.getenv("REDIS_HOST", "127.0.0.1")

    @property
    def redis_port(self) -> int:
        return int(os.getenv("REDIS_PORT", "6379"))

    @property
    def redis_database(self) -> int:
        return int(os.getenv("REDIS_DATABASE", "0"))

    @property
    def redis_password(self) -> str:
        return os.getenv("REDIS_PASSWORD", "")
