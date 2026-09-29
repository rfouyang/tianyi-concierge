from __future__ import annotations

import time
from typing import Any

from loguru import logger

from ..action_status import ActionStatus
from ..api_client import SlamApiClient


class ActionClient:
    """Generic SLAM action submission, polling, and cancellation."""

    def __init__(self, api: SlamApiClient, **kwargs: Any) -> None:
        self.api = api
        self.request_timeout = kwargs.get("request_timeout", 5)
        self.action_timeout = kwargs.get("action_timeout", 30)
        self.poll_interval = kwargs.get("poll_interval", 1)

    @staticmethod
    def require_success(action, label="Motion action"):
        state = action.get("state", {})
        if state.get("status") != 4 or state.get("result") != 0:
            raise RuntimeError(f"{label} failed: {state}")
        return action

    def submit(self, path, payload, **kwargs):
        response = self.api.post(path, json=payload, timeout=self.request_timeout)
        response.raise_for_status()
        action = response.json()
        action_id = action.get("action_id")
        if kwargs.get("log_message"):
            logger.info(f"{kwargs['log_message']}: {action_id}")
        if not kwargs.get("wait", False) or not action_id:
            return action
        return self.wait(action_id, **kwargs)

    def get(self, action_id):
        response = self.api.get(
            f"/api/core/motion/v1/actions/{action_id}",
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_status(self, action_id):
        action = self.get(action_id)
        state = action.get("state", {})
        if state.get("status") != 4:
            status = ActionStatus.DOING
        elif state.get("result") == 0:
            status = ActionStatus.SUCCESS
        else:
            status = ActionStatus.FAILED
        logger.info(
            f"Action {action_id} status: {status.value} "
            f"(status={state.get('status')}, result={state.get('result')})"
        )
        return status

    def get_current(self):
        response = self.api.get(
            "/api/core/motion/v1/actions/:current",
            timeout=self.request_timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def cancel_current(self):
        response = self.api.delete(
            "/api/core/motion/v1/actions/:current",
            timeout=self.request_timeout,
        )
        if response.status_code != 404:
            response.raise_for_status()
        logger.info("Canceled current action")
        return response

    def is_current_finished(self):
        action = self.get_current()
        if action is None:
            return True
        return action.get("state", {}).get("status") == 4

    def wait_current_finished(self, **kwargs):
        timeout = kwargs.get("timeout", 3600)
        poll_interval = kwargs.get("poll_interval", self.poll_interval)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            action = self.get_current()
            if action is None or action.get("state", {}).get("status") == 4:
                return action
            time.sleep(poll_interval)
        raise TimeoutError(f"Current action did not finish within {timeout} seconds")

    def wait(self, action_id, **kwargs):
        timeout = kwargs.get("timeout", self.action_timeout)
        poll_interval = kwargs.get("poll_interval", self.poll_interval)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            action = self.get(action_id)
            if action.get("state", {}).get("status") == 4:
                logger.info(f"Action finished: {action_id}")
                return action
            time.sleep(poll_interval)
        raise TimeoutError(f"Action did not finish within {timeout} seconds: {action_id}")

    def get_all(self):
        response = self.api.get(
            "/api/core/motion/v1/action-factories",
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return response.json()
