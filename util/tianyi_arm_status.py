from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .tianyi_arm_mapping import TIANYI_ARM_MOTOR_IDS


@dataclass(frozen=True, slots=True)
class TianyiArmMotorStatus:
    motor_id: int
    position: float
    speed: float
    current: float
    temperature: float
    error: int
    received_at: float


@dataclass(frozen=True, slots=True)
class TianyiArmStatusSnapshot:
    motors: tuple[TianyiArmMotorStatus, ...]

    def positions_by_motor_id(self) -> dict[int, float]:
        return {motor.motor_id: motor.position for motor in self.motors}


class TianyiArmStatusMonitor:
    """Validate the latest vendor status for the fourteen arm motors."""

    def __init__(
        self,
        *,
        stale_after_seconds: float = 1.0,
        maximum_temperature_c: float = 75.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if stale_after_seconds <= 0.0:
            raise ValueError("Arm status freshness duration must be positive")
        if not math.isfinite(maximum_temperature_c):
            raise ValueError("Arm maximum temperature must be finite")
        self.stale_after_seconds = float(stale_after_seconds)
        self.maximum_temperature_c = float(maximum_temperature_c)
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._statuses: dict[int, TianyiArmMotorStatus] = {}
        self._input_error: str | None = None

    def update(self, message: Any) -> None:
        """Consume one bodyctrl_msgs/MotorStatusMsg-compatible message."""
        received_at = self._monotonic()
        try:
            entries = tuple(message.status)
        except (AttributeError, TypeError) as error:
            with self._lock:
                self._input_error = f"Invalid /arm/status message: {error}"
            return

        updates: dict[int, TianyiArmMotorStatus] = {}
        try:
            for entry in entries:
                motor_id = int(entry.name)
                if motor_id not in TIANYI_ARM_MOTOR_IDS:
                    continue
                if motor_id in updates:
                    raise ValueError(f"duplicate motor ID {motor_id}")
                updates[motor_id] = TianyiArmMotorStatus(
                    motor_id=motor_id,
                    position=float(entry.pos),
                    speed=float(entry.speed),
                    current=float(entry.current),
                    temperature=float(entry.temperature),
                    error=int(entry.error),
                    received_at=received_at,
                )
        except (AttributeError, TypeError, ValueError) as error:
            with self._lock:
                self._input_error = f"Invalid /arm/status message: {error}"
            return

        with self._lock:
            self._statuses.update(updates)
            self._input_error = None

    def require_ready(self) -> TianyiArmStatusSnapshot:
        """Return a canonical snapshot or explain why arm motion is unsafe."""
        now = self._monotonic()
        with self._lock:
            statuses = dict(self._statuses)
            input_error = self._input_error
        if input_error is not None:
            raise RuntimeError(input_error)

        missing = [
            motor_id for motor_id in TIANYI_ARM_MOTOR_IDS if motor_id not in statuses
        ]
        if missing:
            raise RuntimeError(
                "Arm status is missing motor IDs: "
                + ", ".join(str(motor_id) for motor_id in missing)
            )

        stale = [
            motor_id
            for motor_id in TIANYI_ARM_MOTOR_IDS
            if now - statuses[motor_id].received_at > self.stale_after_seconds
        ]
        if stale:
            raise RuntimeError(
                "Arm status is stale for motor IDs: "
                + ", ".join(str(motor_id) for motor_id in stale)
            )

        ordered = tuple(statuses[motor_id] for motor_id in TIANYI_ARM_MOTOR_IDS)
        for motor in ordered:
            values = (
                motor.position,
                motor.speed,
                motor.current,
                motor.temperature,
            )
            if not all(math.isfinite(value) for value in values):
                raise RuntimeError(
                    f"Arm motor {motor.motor_id} reports a non-finite status value"
                )
            if motor.error != 0:
                raise RuntimeError(
                    f"Arm motor {motor.motor_id} reports error {motor.error}"
                )
            if motor.temperature > self.maximum_temperature_c:
                raise RuntimeError(
                    f"Arm motor {motor.motor_id} temperature "
                    f"{motor.temperature:.1f} C exceeds "
                    f"{self.maximum_temperature_c:.1f} C"
                )
        return TianyiArmStatusSnapshot(motors=ordered)

    def health(self) -> dict[str, object]:
        try:
            snapshot = self.require_ready()
        except RuntimeError as error:
            return {"ready": False, "error": str(error), "motor_count": 0}
        return {
            "ready": True,
            "error": None,
            "motor_count": len(snapshot.motors),
        }


class TianyiArmStatusSubscriber:
    """Own the direct ROS 2 subscription to the vendor /arm/status topic."""

    STATUS_TOPIC = "/arm/status"

    def __init__(self, monitor: TianyiArmStatusMonitor | None = None) -> None:
        self.monitor = monitor or TianyiArmStatusMonitor()
        self._rclpy: Any = None
        self._node: Any = None
        self._executor: Any = None
        self._thread: threading.Thread | None = None
        self._subscription: Any = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            import rclpy
            from bodyctrl_msgs.msg import MotorStatusMsg
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import qos_profile_sensor_data
        except ImportError as error:
            raise RuntimeError(
                "ROS 2 Python packages are unavailable; source "
                "/opt/ros/humble/setup.bash before starting Tianyi Concierge"
            ) from error

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init()
        self._node = Node("tianyi_concierge_tianyi_arm_status")
        self._subscription = self._node.create_subscription(
            MotorStatusMsg,
            self.STATUS_TOPIC,
            self.monitor.update,
            qos_profile_sensor_data,
        )
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(
            target=self._executor.spin,
            name="tianyi-arm-status",
            daemon=True,
        )
        self._thread.start()

    def require_ready(
        self, *, wait_timeout_seconds: float = 1.5
    ) -> TianyiArmStatusSnapshot:
        self.start()
        deadline = time.monotonic() + wait_timeout_seconds
        last_error: RuntimeError | None = None
        while True:
            try:
                return self.monitor.require_ready()
            except RuntimeError as error:
                last_error = error
            if time.monotonic() >= deadline:
                assert last_error is not None
                raise last_error
            time.sleep(0.02)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._node is not None:
            self._node.destroy_node()
        self._subscription = None
        self._executor = None
        self._thread = None
        self._node = None
