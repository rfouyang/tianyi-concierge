from __future__ import annotations

from util.slam_helper import SLAM


class NavigationService:
    """Navigate to resolved concierge POI stops."""

    def __init__(self, slam: SLAM) -> None:
        self.slam = slam
        self.acceptable_precision = 0.2
        self.fail_retry_count = 2
        self.speed_ratio = 0.5

    def navigate(self, stop, **kwargs):
        options = {
            "wait": True,
            "timeout": kwargs.get("move_timeout", 300),
            "poll_interval": kwargs.get("poll_interval", 1),
            "acceptable_precision": kwargs.get(
                "acceptable_precision", self.acceptable_precision
            ),
            "fail_retry_count": kwargs.get(
                "fail_retry_count", self.fail_retry_count
            ),
            "speed_ratio": kwargs.get("speed_ratio", self.speed_ratio),
        }
        pose = stop["poi"]["pose"]
        action = self.slam.motion.move_to_action(
            pose["x"],
            pose["y"],
            pose.get("yaw", 0),
            **options,
        )
        return self.slam.require_action_success(
            action,
            f"Navigate to {stop['poi_name']}",
        )
