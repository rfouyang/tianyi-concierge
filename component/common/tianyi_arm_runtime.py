from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass

from util.tianyi_action_artifact import TianyiActionArtifactLoader
from util.tianyi_arm_command import (
    TianyiArmCommandBuilder,
    TianyiArmCommandPublisher,
)
from util.tianyi_arm_mapping import RECORDER_NAME_BY_MOTOR_ID
from util.tianyi_arm_status import (
    TianyiArmStatusSnapshot,
    TianyiArmStatusSubscriber,
)

from .tianyi_arm_motion import TianyiArmMotionService


@dataclass(frozen=True, slots=True)
class TianyiArmRuntimeHealth:
    ready: bool
    error: str | None
    motor_count: int
    action_names: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "error": self.error,
            "motor_count": self.motor_count,
            "action_names": list(self.action_names),
        }


class TianyiArmRuntime:
    """Compose direct vendor ROS I/O with recorder-format arm actions."""

    def __init__(
        self,
        *,
        artifact_loader: TianyiActionArtifactLoader | None = None,
        status_subscriber: TianyiArmStatusSubscriber | None = None,
        command_publisher: TianyiArmCommandPublisher | None = None,
        motion_service: TianyiArmMotionService | None = None,
    ) -> None:
        self.artifact_loader = artifact_loader or TianyiActionArtifactLoader()
        self.status_subscriber = status_subscriber or TianyiArmStatusSubscriber()
        self.command_publisher = command_publisher or TianyiArmCommandPublisher()
        self.motion_service = motion_service or TianyiArmMotionService(
            artifact_loader=self.artifact_loader,
            status_monitor=self.status_subscriber.monitor,
            command_builder=TianyiArmCommandBuilder(self.artifact_loader),
            command_sink=self.command_publisher,
        )

    def list_actions(self) -> list[dict[str, object]]:
        """Return only complete, internally consistent local recorder actions."""
        actions = []
        for action_name in self.artifact_loader.list_action_names():
            try:
                trajectory = self.artifact_loader.validate_action(action_name)
            except (FileNotFoundError, OSError, ValueError):
                continue
            actions.append(
                {
                    "action_id": action_name,
                    "label": action_name.replace("_", " ").title(),
                    "ready": True,
                    "duration": trajectory.duration_seconds,
                }
            )
        return actions

    def preflight(self) -> TianyiArmRuntimeHealth:
        """Check artifacts and live ROS endpoints without publishing commands."""
        action_names: tuple[str, ...] = ()
        motor_count = 0
        try:
            actions = self.list_actions()
            action_names = tuple(str(action["action_id"]) for action in actions)
            if not action_names:
                raise RuntimeError("No valid Tianyi recorder actions are available")
            snapshot = self.status_subscriber.require_ready()
            motor_count = len(snapshot.motors)
            self.command_publisher.require_subscriber()
        except Exception as error:
            return TianyiArmRuntimeHealth(
                ready=False,
                error=str(error),
                motor_count=motor_count,
                action_names=action_names,
            )
        return TianyiArmRuntimeHealth(
            ready=True,
            error=None,
            motor_count=motor_count,
            action_names=action_names,
        )

    def require_preflight(self) -> TianyiArmStatusSnapshot:
        """Raise on any unsafe condition and return the measured arm state."""
        if not self.list_actions():
            raise RuntimeError("No valid Tianyi recorder actions are available")
        snapshot = self.status_subscriber.require_ready()
        self.command_publisher.require_subscriber()
        return snapshot

    def move_to_concierge_init(self, *, confirmed: bool) -> dict[str, object]:
        """Run the first guarded physical move for the two arms only."""
        if confirmed is not True:
            raise PermissionError("Explicit Tianyi arm-motion confirmation is required")
        before = self.require_preflight().positions_by_motor_id()
        self.motion_service.move_to_concierge_init(threading.Event())
        after = self.status_subscriber.require_ready().positions_by_motor_id()
        target_pose = self.artifact_loader.load_pose(
            pose_type="base",
            name="concierge_init",
        )
        target = {
            motor_id: target_pose[RECORDER_NAME_BY_MOTOR_ID[motor_id]]
            for motor_id in before
        }
        maximum_error = max(
            abs(after[motor_id] - target[motor_id]) for motor_id in target
        )
        return {
            "status": "completed",
            "motor_ids": list(before),
            "before": before,
            "target": target,
            "after": after,
            "maximum_error_rad": maximum_error,
        }

    def execute_action(
        self,
        action_name: str,
        *,
        confirmed: bool,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, object]:
        """Prepare, execute one recorder action, and verify its home finish."""
        if confirmed is not True:
            raise PermissionError("Explicit Tianyi arm-motion confirmation is required")
        available = {
            str(action["action_id"]): action for action in self.list_actions()
        }
        if action_name not in available:
            raise ValueError(f"Tianyi arm action is unavailable: {action_name}")
        before = self.require_preflight().positions_by_motor_id()
        self.motion_service.execute(action_name, cancel_event or threading.Event())
        after = self.status_subscriber.require_ready().positions_by_motor_id()
        target_pose = self.artifact_loader.load_pose(
            pose_type="base",
            name="concierge_init",
        )
        target = {
            motor_id: target_pose[RECORDER_NAME_BY_MOTOR_ID[motor_id]]
            for motor_id in before
        }
        maximum_error = max(
            abs(after[motor_id] - target[motor_id]) for motor_id in target
        )
        return {
            "status": "completed",
            "action_name": action_name,
            "duration_seconds": available[action_name]["duration"],
            "motor_ids": list(before),
            "before": before,
            "target": target,
            "after": after,
            "maximum_final_error_rad": maximum_error,
        }

    def close(self) -> None:
        self.status_subscriber.close()
        self.command_publisher.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Direct Tianyi two-arm runtime")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--move-to-init",
        action="store_true",
        help="physically move both arms to the bundled concierge_init pose",
    )
    operation.add_argument(
        "--execute-action",
        metavar="ACTION_NAME",
        help="physically prepare and execute one bundled two-arm action",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="must be MOVE_ARMS for a physical move",
    )
    arguments = parser.parse_args()
    runtime = TianyiArmRuntime()
    try:
        if arguments.move_to_init or arguments.execute_action:
            if arguments.confirm != "MOVE_ARMS":
                raise PermissionError(
                    "Pass --confirm MOVE_ARMS after checking the area and emergency stop"
                )
            if arguments.move_to_init:
                result = runtime.move_to_concierge_init(confirmed=True)
            else:
                result = runtime.execute_action(
                    arguments.execute_action,
                    confirmed=True,
                )
        else:
            result = runtime.preflight().to_dict()
        print(json.dumps(result, indent=2))
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
