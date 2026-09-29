from __future__ import annotations

from typing import Any

from ..api_client import SlamApiClient
from .action_client import ActionClient
from .docking_client import DockingClient
from .movement_client import MovementClient
from .path_planner import PathPlanner
from .relocalization_client import RelocalizationClient

START_POINT = {"x": 0.0, "y": 0.0}
RELOCALIZATION_RADIUS = 3.0


class Motion:
    """Compose the focused low-level SLAM motion clients."""

    PRECISE = 16

    def __init__(self, **kwargs: Any) -> None:
        self.api = SlamApiClient(**kwargs)
        self.actions = ActionClient(self.api, **kwargs)
        self.movement = MovementClient(self.actions, **kwargs)
        self.docking = DockingClient(self.actions, **kwargs)
        self.path_planner = PathPlanner(self.api, **kwargs)
        self.relocalizer = RelocalizationClient(self.actions, **kwargs)

    def get_action(self, action_id):
        return self.actions.get(action_id)

    def get_action_status(self, action_id):
        return self.actions.get_status(action_id)

    def get_current_action(self):
        return self.actions.get_current()

    def cancel_current_action(self):
        return self.actions.cancel_current()

    def is_current_action_finished(self):
        return self.actions.is_current_finished()

    def wait_current_action_finished(self, **kwargs):
        return self.actions.wait_current_finished(**kwargs)

    def wait_action(self, action_id, **kwargs):
        return self.actions.wait(action_id, **kwargs)

    def get_all_actions(self):
        return self.actions.get_all()

    def search_path(self, x, y, **kwargs):
        return self.path_planner.search(x, y, **kwargs)

    def relocalization(self, **kwargs):
        return self.relocalizer.start(**kwargs)

    def move_to_action(self, x, y, yaw, **kwargs):
        return self.movement.move_to(x, y, yaw, **kwargs)

    def move_to_precise_action(self, x, y, yaw, **kwargs):
        return self.movement.move_to_precise(x, y, yaw, **kwargs)

    def move_by_action(self, direction, **kwargs):
        return self.movement.move_by(direction, **kwargs)

    def rotate_action(self, angle, **kwargs):
        return self.movement.rotate(angle, **kwargs)

    def dock(self, **kwargs):
        return self.docking.go_home(**kwargs)

    def reflector_dock_action(self, x, y, yaw, reflect_tag_num, **kwargs):
        return self.docking.move_to_tag(
            x,
            y,
            yaw,
            reflect_tag_num,
            **kwargs,
        )

    def reflector_undock_action(self, back_up_distance, **kwargs):
        return self.docking.back_off_from_tag(back_up_distance, **kwargs)

__all__ = [
    "ActionClient",
    "DockingClient",
    "Motion",
    "MovementClient",
    "PathPlanner",
    "RelocalizationClient",
]
