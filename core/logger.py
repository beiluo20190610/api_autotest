import logging
import os

from config.config import Config

conf = Config()
log_path = conf._config_data["logging"]["file"]
os.makedirs(os.path.dirname(log_path), exist_ok=True)

logging.basicConfig(
    level=conf._config_data["logging"]["level"],
    format=conf._config_data["logging"]["format"],
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("api_auto_test")
