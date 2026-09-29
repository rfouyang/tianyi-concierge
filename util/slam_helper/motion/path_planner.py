from __future__ import annotations

from typing import Any

from ..api_client import SlamApiClient


class PathPlanner:
    """Read-only path search through the SLAM planner API."""

    def __init__(self, api: SlamApiClient, **kwargs: Any) -> None:
        self.api = api
        self.request_timeout = kwargs.get("request_timeout", 30)

    def search(self, x, y, **kwargs):
        payload = {"target": {"x": x, "y": y}}
        planner_timeout = kwargs.get("planner_timeout")
        if planner_timeout is not None:
            if planner_timeout <= 0:
                raise ValueError("planner_timeout must be positive milliseconds")
            payload["timeout"] = planner_timeout
        response = self.api.post(
            "/api/core/motion/v1/:search_path",
            json=payload,
            timeout=kwargs.get("request_timeout", self.request_timeout),
        )
        response.raise_for_status()
        return response.json()
