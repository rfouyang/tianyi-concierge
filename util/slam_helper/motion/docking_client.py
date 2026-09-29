from __future__ import annotations

from typing import Any

from .action_client import ActionClient


class DockingClient:
    """Low-level SLAM docking action payloads; no recovery policy."""

    def __init__(self, action_client: ActionClient, **kwargs: Any) -> None:
        self.actions = action_client

    def go_home(self, **kwargs):
        options = {"flags": kwargs.get("flags", "dock")}
        for key in ("back_to_landing", "charging_retry_count"):
            if kwargs.get(key) is not None:
                options[key] = kwargs[key]
        if kwargs.get("move_mode") is not None:
            options["move_options"] = {"mode": kwargs["move_mode"]}
        payload = {
            "action_name": "slamtec.agent.actions.GoHomeAction",
            "options": {"gohome_options": options},
        }
        options = dict(kwargs)
        options.setdefault("wait", True)
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started dock action",
            **options,
        )

    def move_to_tag(self, x, y, yaw, reflect_tag_num, **kwargs):
        options = {
            "target": {"x": x, "y": y, "yaw": yaw},
            "tag_type": 2,
            "backward_docking": kwargs.get("backward_docking", False),
            "reflect_tag_num": reflect_tag_num,
            "target_relative_pose": {
                "x": kwargs.get("relative_x", 0.075),
                "y": kwargs.get("relative_y", 0.0),
            },
        }
        payload = {
            "action_name": "slamtec.agent.actions.MoveToTagAction",
            "options": options,
        }
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started reflector dock action",
            **kwargs,
        )

    def back_off_from_tag(self, back_up_distance, **kwargs):
        target = kwargs.get("target")
        if target is None:
            raise ValueError("Reflector undocking requires the dock target pose")
        options = {
            "target": {
                "x": target["x"],
                "y": target["y"],
                "yaw": target.get("yaw", 0),
            },
            "tag_type": 2,
            "backward_docking": kwargs.get("backward_docking", False),
            "backup_distance": back_up_distance,
        }
        if kwargs.get("backup_mode") is not None:
            options["backup_mode"] = kwargs["backup_mode"]
        payload = {
            "action_name": "slamtec.agent.actions.BackOffFromTagAction",
            "options": options,
        }
        return self.actions.submit(
            "/api/core/motion/v1/actions",
            payload,
            log_message="Started reflector undock action",
            **kwargs,
        )
