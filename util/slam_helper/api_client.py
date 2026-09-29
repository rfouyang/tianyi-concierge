from __future__ import annotations

from typing import Any

import requests

from .base import Base


class SlamApiClient:
    """Small stateful HTTP client shared by the SLAM API utilities."""

    def __init__(self, **kwargs: Any) -> None:
        self.base_url = str(kwargs.get("base_url", Base.BASE_URL)).rstrip("/")
        self.request_timeout = kwargs.get("request_timeout", 5)
        self.session = kwargs.get("session") or requests.Session()

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.request_timeout)
        return self.session.request(method, url, **kwargs)

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", path, **kwargs)
