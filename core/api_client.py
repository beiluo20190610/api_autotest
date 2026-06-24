from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.config import Config
from core.logger import logger


class ApiClient:
    """统一 HTTP 客户端：Session、重试、多 content_type。"""

    def __init__(self):
        self.config = Config()
        self.session = requests.Session()
        self.session.headers.update(self.config.global_headers)
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        content_type: str = "json",
        **kwargs,
    ) -> requests.Response:
        full_url = f"{self.config.base_url}{url}"
        merge_headers = {**self.session.headers, **(headers or {})}
        try:
            logger.info(f"【{method.upper()}】{full_url}")
            logger.debug(f"请求头：{merge_headers}")
            logger.debug(f"请求参数：{data}")

            if content_type == "json":
                resp = self.session.request(
                    method=method,
                    url=full_url,
                    headers=merge_headers,
                    json=data,
                    timeout=self.config.timeout,
                    **kwargs,
                )
            elif content_type == "form":
                form_headers = {
                    k: v
                    for k, v in merge_headers.items()
                    if k.lower() != "content-type"
                }
                form_headers["Content-Type"] = "application/x-www-form-urlencoded"
                form_data = {
                    k: "" if v is None else str(v) for k, v in (data or {}).items()
                }
                resp = self.session.request(
                    method=method,
                    url=full_url,
                    headers=form_headers,
                    data=form_data,
                    timeout=self.config.timeout,
                    **kwargs,
                )
            elif content_type == "form-data":
                resp = self.session.request(
                    method=method,
                    url=full_url,
                    headers=merge_headers,
                    files=data,
                    timeout=self.config.timeout,
                    **kwargs,
                )
            else:
                resp = self.session.request(
                    method=method,
                    url=full_url,
                    headers=merge_headers,
                    data=data,
                    timeout=self.config.timeout,
                    **kwargs,
                )

            logger.info(f"响应码：{resp.status_code}")
            logger.debug(f"响应内容：{resp.text[:800]}")
            return resp
        except Exception as e:
            logger.error(f"请求异常：{str(e)}")
            raise
