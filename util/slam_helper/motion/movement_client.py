from __future__ import annotations

from typing import Any

from .action_client import ActionClient


class MovementClient:
    """Low-level MoveTo, MoveBy, and Rotate SLAM actions."""

    def __init__(self, action_client: ActionClient, **kwargs: Any) -> None:
        self.actions = action_client
        self.default_mode = kwargs.get("mode", 0)

    def _move_to(self, x, y, yaw, flags, **kwargs):
        move_options = {
            "mode": kwargs.get("mode", self.default_mode),
            "flags": flags,
            "yaw": yaw,
        }
        for key in ("acceptable_precision", "fail_retry_count", "speed_ratio"):
            if kwargs.get(key) is not None:
                move_options[key] = kwargs[key]
        payload = {
            "action_name": "slamtec.agent.actions.MoveToAction",
            "options": {
                "target": {"x": x, "y": y, "z": kwargs.get("z", 0)},
                "move_options": move_options,
            },
        }
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started move-to action",
            **kwargs,
        )

    def move_to(self, x, y, yaw=0, **kwargs):
        return self._move_to(x, y, yaw, ["with_yaw"], **kwargs)

    def move_to_precise(self, x, y, yaw=0, **kwargs):
        return self._move_to(x, y, yaw, ["with_yaw", "precise"], **kwargs)

    def move_by(self, direction, **kwargs):
        if direction not in {0, 1, 2, 3}:
            raise ValueError("MoveBy direction must be 0, 1, 2, or 3")
        duration = kwargs.get("duration", 250)
        if not 0 < duration <= 500:
            raise ValueError("MoveBy duration must be between 1 and 500 ms")
        payload = {
            "action_name": "slamtec.agent.actions.MoveByAction",
            "options": {"direction": direction, "duration": duration},
        }
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started move-by action",
            **kwargs,
        )

    def rotate(self, angle, **kwargs):
        payload = {
            "action_name": "slamtec.agent.actions.RotateAction",
            "options": {"angle": angle},
        }
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started rotate action",
            **kwargs,
        )
