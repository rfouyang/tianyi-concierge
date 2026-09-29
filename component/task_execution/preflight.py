from __future__ import annotations

from util.slam_helper import SLAM


class ConciergeExecutionPreflight:
    """Validate that the concierge execution environment is ready."""

    def __init__(self, task_designer, slam: SLAM, body_actions=None) -> None:
        self.task_designer = task_designer
        self.slam = slam
        self.body_actions = body_actions

    def _resolve_and_check_actions(self, task):
        resolved = self.task_designer.resolve_task(task)
        action_ids = {
            action["action_id"]
            for stop in resolved["stops"]
            for action in stop.get("actions", [])
        }
        if self.body_actions is None:
            raise RuntimeError("Direct Tianyi arm runtime is not configured")
        available = {
            action["action_id"] for action in self.body_actions.list_actions()
        }
        missing = sorted(action_ids - available)
        if missing:
            raise RuntimeError(
                "Tianyi arm actions are unavailable: " + ", ".join(missing)
            )
        health = self.body_actions.health()
        if health.get("ready") is not True:
            raise RuntimeError(
                "Tianyi body-action preflight failed: "
                + str(health.get("error") or "unknown error")
            )
        return resolved

    def _check_environment(self, **kwargs):
        map_status = self.slam.map_client.get_map_status()
        if map_status.get("map_load_status") != "LOADED":
            raise RuntimeError(f"Map is not loaded: {map_status}")
        if self.slam.mapping.is_enabled():
            raise RuntimeError("A task cannot run while map building is active")

        self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if (
            current_action is not None
            and current_action.get("state", {}).get("status") != 4
        ):
            raise RuntimeError(
                f"Robot has an active action: {current_action.get('action_id')}"
            )

        quality = self.slam.localization.get_localization_quality()
        min_quality = kwargs.get("min_quality", 50)
        return map_status, quality, min_quality

    def check(self, task, **kwargs):
        map_status, quality, min_quality = self._check_environment(**kwargs)
        if quality < min_quality:
            raise RuntimeError(
                f"Localization quality is too low: {quality} < {min_quality}"
            )

        power = self.slam.power.get_status()
        home_dock = self.slam.home_dock.require_bound_home_dock()
        return {
            "task": self._resolve_and_check_actions(task),
            "map": map_status,
            "localization_quality": quality,
            "power": power,
            "home_dock": home_dock,
        }

    def check_resume(self, task, **kwargs):
        """Validate a resume without requiring the robot to be on the dock."""
        map_status, quality, _ = self._check_environment(**kwargs)
        return {
            "task": self._resolve_and_check_actions(task),
            "map": map_status,
            "localization_quality": quality,
        }
