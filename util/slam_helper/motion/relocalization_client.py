from __future__ import annotations

from typing import Any

from .action_client import ActionClient


class RelocalizationClient:
    """Low-level localization recovery action."""

    def __init__(self, action_client: ActionClient, **kwargs: Any) -> None:
        self.actions = action_client

    def start(self, **kwargs):
        options = {}
        if kwargs.get("area") is not None:
            options["area"] = kwargs["area"]
        recovery = {}
        for key in ("max_recover_time", "recover_movement_type"):
            if kwargs.get(key) is not None:
                recovery[key] = kwargs[key]
        if recovery:
            options["relocalization_options"] = recovery
        payload = {
            "action_name": "slamtec.agent.actions.RecoverLocalizationAction",
            "options": options,
        }
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started relocalization action",
            **kwargs,
        )
