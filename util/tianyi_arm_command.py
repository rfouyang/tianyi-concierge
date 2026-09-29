from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .tianyi_action_artifact import TianyiActionArtifactLoader, TianyiActionTrajectory
from .tianyi_arm_mapping import (
    RECORDER_NAME_BY_MOTOR_ID,
    TIANYI_ARM_MOTOR_IDS,
    arm_positions_by_motor_id,
)


@dataclass(frozen=True, slots=True)
class TianyiArmMotorCommand:
    motor_id: int
    position: float
    speed: float
    maximum_current: float


@dataclass(frozen=True, slots=True)
class TianyiArmCommandBatch:
    """One complete two-arm position command in SDK motor order."""

    commands: tuple[TianyiArmMotorCommand, ...]

    def positions_by_motor_id(self) -> dict[int, float]:
        return {command.motor_id: command.position for command in self.commands}

    def maximum_currents_by_motor_id(self) -> dict[int, float]:
        return {
            command.motor_id: command.maximum_current
            for command in self.commands
        }


class TianyiArmCommandSink(Protocol):
    def publish(self, batch: TianyiArmCommandBatch) -> None: ...


class TianyiArmCommandBuilder:
    """Build bounded vendor commands for motors 11-17 and 21-27 only."""

    def __init__(self, artifact_loader: TianyiActionArtifactLoader) -> None:
        self.artifact_loader = artifact_loader

    def from_trajectory_sample(
        self,
        trajectory: TianyiActionTrajectory,
        sample_index: int,
        *,
        speed_rad_s: float,
        maximum_current_a: float,
    ) -> TianyiArmCommandBatch:
        return self.build(
            positions_by_motor_id=arm_positions_by_motor_id(
                trajectory,
                sample_index,
            ),
            speed_rad_s=speed_rad_s,
            maximum_current_a=maximum_current_a,
        )

    def build(
        self,
        *,
        positions_by_motor_id: Mapping[int, object],
        speed_rad_s: float,
        maximum_current_a: float | Mapping[int, object],
    ) -> TianyiArmCommandBatch:
        if set(positions_by_motor_id) != set(TIANYI_ARM_MOTOR_IDS):
            missing = sorted(set(TIANYI_ARM_MOTOR_IDS) - set(positions_by_motor_id))
            unknown = sorted(set(positions_by_motor_id) - set(TIANYI_ARM_MOTOR_IDS))
            details = []
            if missing:
                details.append(f"missing={missing}")
            if unknown:
                details.append(f"unknown={unknown}")
            raise ValueError("Invalid Tianyi arm motor set: " + ", ".join(details))
        speed = self._positive_value(speed_rad_s, label="Arm command speed")
        maximum_currents = self._maximum_currents(maximum_current_a)

        limits = self.artifact_loader.joint_limits
        commands = []
        for motor_id in TIANYI_ARM_MOTOR_IDS:
            value = positions_by_motor_id[motor_id]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Arm motor {motor_id} position must be a real number")
            position = float(value)
            recorder_name = RECORDER_NAME_BY_MOTOR_ID[motor_id]
            lower, upper = limits[recorder_name]
            if not math.isfinite(position) or not lower <= position <= upper:
                raise ValueError(
                    f"Arm motor {motor_id} position {position} is outside "
                    f"[{lower}, {upper}] rad"
                )
            commands.append(
                TianyiArmMotorCommand(
                    motor_id=motor_id,
                    position=position,
                    speed=speed,
                    maximum_current=maximum_currents[motor_id],
                )
            )
        return TianyiArmCommandBatch(commands=tuple(commands))

    @classmethod
    def _maximum_currents(
        cls,
        value: float | Mapping[int, object],
    ) -> dict[int, float]:
        if not isinstance(value, Mapping):
            maximum_current = cls._positive_value(
                value,
                label="Arm command maximum current",
            )
            return {
                motor_id: maximum_current for motor_id in TIANYI_ARM_MOTOR_IDS
            }

        if set(value) != set(TIANYI_ARM_MOTOR_IDS):
            missing = sorted(set(TIANYI_ARM_MOTOR_IDS) - set(value))
            unknown = sorted(set(value) - set(TIANYI_ARM_MOTOR_IDS))
            details = []
            if missing:
                details.append(f"missing={missing}")
            if unknown:
                details.append(f"unknown={unknown}")
            raise ValueError(
                "Invalid Tianyi arm maximum-current motor set: "
                + ", ".join(details)
            )
        return {
            motor_id: cls._positive_value(
                value[motor_id],
                label=f"Arm motor {motor_id} maximum current",
            )
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }

    @staticmethod
    def _positive_value(value: object, *, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a real number")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized <= 0.0:
            raise ValueError(f"{label} must be finite and greater than zero")
        return normalized


class TianyiArmCommandPublisher:
    """Publish complete arm batches directly to the vendor ROS 2 topic."""

    COMMAND_TOPIC = "/arm/cmd_pos"

    def __init__(self, *, node_name: str = "tianyi_concierge_tianyi_arm_command") -> None:
        self.node_name = node_name
        self._rclpy: Any = None
        self._node: Any = None
        self._publisher: Any = None
        self._message_type: Any = None
        self._command_type: Any = None

    def start(self) -> None:
        if self._publisher is not None:
            return
        try:
            import rclpy
            from bodyctrl_msgs.msg import CmdSetMotorPosition, SetMotorPosition
            from rclpy.node import Node
        except ImportError as error:
            raise RuntimeError(
                "ROS 2 Python packages are unavailable; source "
                "/opt/ros/humble/setup.bash before starting Tianyi Concierge"
            ) from error

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init()
        self._node = Node(self.node_name)
        self._message_type = CmdSetMotorPosition
        self._command_type = SetMotorPosition
        self._publisher = self._node.create_publisher(
            CmdSetMotorPosition,
            self.COMMAND_TOPIC,
            10,
        )

    def require_subscriber(self, *, wait_timeout_seconds: float = 1.5) -> None:
        self.start()
        deadline = time.monotonic() + wait_timeout_seconds
        while self._publisher.get_subscription_count() < 1:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "No Tianyi vendor subscriber is available on /arm/cmd_pos"
                )
            time.sleep(0.02)

    def publish(self, batch: TianyiArmCommandBatch) -> None:
        self.start()
        if tuple(command.motor_id for command in batch.commands) != TIANYI_ARM_MOTOR_IDS:
            raise ValueError("Arm command batch must contain the canonical 14 motor IDs")
        message = self._message_type()
        message.header.stamp = self._node.get_clock().now().to_msg()
        for source in batch.commands:
            command = self._command_type()
            command.name = source.motor_id
            command.pos = source.position
            command.spd = source.speed
            command.cur = source.maximum_current
            message.cmds.append(command)
        self._publisher.publish(message)

    def close(self) -> None:
        if self._node is not None:
            self._node.destroy_node()
        self._publisher = None
        self._message_type = None
        self._command_type = None
        self._node = None
