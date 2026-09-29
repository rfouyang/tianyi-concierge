from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping

import numpy as np

from util.tianyi_action_artifact import TianyiActionArtifactLoader
from util.tianyi_arm_command import TianyiArmCommandBuilder, TianyiArmCommandSink
from util.tianyi_arm_mapping import (
    RECORDER_NAME_BY_MOTOR_ID,
    TIANYI_ARM_MOTOR_IDS,
    extract_arm_positions,
)
from util.tianyi_arm_status import TianyiArmStatusMonitor

from .errors import ConciergeTaskCancelled


class TianyiArmMotionService:
    """Move to concierge_init, then play one validated recorder action."""

    INIT_POSE_NAME = "concierge_init"
    DEFAULT_MAXIMUM_CURRENT_A_BY_MOTOR_ID = {
        motor_id: 5.0
        if motor_id in {11, 12, 13, 14, 21, 22, 23, 24}
        else 3.0
        for motor_id in TIANYI_ARM_MOTOR_IDS
    }

    def __init__(
        self,
        *,
        artifact_loader: TianyiActionArtifactLoader,
        status_monitor: TianyiArmStatusMonitor,
        command_builder: TianyiArmCommandBuilder,
        command_sink: TianyiArmCommandSink,
        sample_frequency_hz: float = 25.0,
        init_speed_rad_s: float = 0.25,
        maximum_action_speed_rad_s: float = 1.2,
        minimum_command_speed_rad_s: float = 0.05,
        maximum_current_a_by_motor_id: Mapping[int, object] | None = None,
        start_tolerance_rad: float = 0.10,
        final_tolerance_rad: float = 0.10,
        convergence_timeout_seconds: float = 2.0,
        maximum_schedule_lag_seconds: float = 0.10,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.artifact_loader = artifact_loader
        self.status_monitor = status_monitor
        self.command_builder = command_builder
        self.command_sink = command_sink
        self.sample_frequency_hz = self._positive(
            sample_frequency_hz,
            "Arm preparation sample frequency",
        )
        self.init_speed_rad_s = self._positive(
            init_speed_rad_s,
            "Arm preparation speed",
        )
        self.maximum_action_speed_rad_s = self._positive(
            maximum_action_speed_rad_s,
            "Arm action maximum speed",
        )
        self.minimum_command_speed_rad_s = self._positive(
            minimum_command_speed_rad_s,
            "Arm minimum command speed",
        )
        self.maximum_current_a_by_motor_id = self._maximum_currents(
            maximum_current_a_by_motor_id
            or self.DEFAULT_MAXIMUM_CURRENT_A_BY_MOTOR_ID
        )
        self.start_tolerance_rad = self._positive(
            start_tolerance_rad,
            "Arm action start tolerance",
        )
        self.final_tolerance_rad = self._positive(
            final_tolerance_rad,
            "Arm action final tolerance",
        )
        self.convergence_timeout_seconds = self._positive(
            convergence_timeout_seconds,
            "Arm convergence timeout",
        )
        self.maximum_schedule_lag_seconds = self._positive(
            maximum_schedule_lag_seconds,
            "Arm maximum schedule lag",
        )
        self._monotonic = monotonic
        self._operation_lock = threading.Lock()

    def move_to_concierge_init(self, cancel_event: threading.Event) -> None:
        """Interpolate both arms from measured state to the recorder home pose."""
        with self._operation():
            self._move_to_concierge_init(cancel_event)

    def execute(self, action_name: str, cancel_event: threading.Event) -> None:
        """Prepare at concierge_init, play an action, and verify its final pose."""
        with self._operation():
            self._move_to_concierge_init(cancel_event)
            self._play_action(action_name, cancel_event)

    def play_prepared_action(
        self,
        action_name: str,
        cancel_event: threading.Event,
    ) -> None:
        """Play only after another call has prepared concierge_init."""
        with self._operation():
            self._play_action(action_name, cancel_event)

    def _move_to_concierge_init(self, cancel_event: threading.Event) -> None:
        target = self._init_positions()
        current = self._current_positions()
        largest_distance = max(
            abs(target[motor_id] - current[motor_id])
            for motor_id in TIANYI_ARM_MOTOR_IDS
        )
        if largest_distance <= self.final_tolerance_rad:
            return

        duration = largest_distance / self.init_speed_rad_s
        step_count = max(1, math.ceil(duration * self.sample_frequency_hz))
        interval = duration / step_count
        started_at = self._monotonic()
        for step in range(1, step_count + 1):
            self._wait_until(started_at + interval * step, cancel_event)
            self.status_monitor.require_ready()
            fraction = step / step_count
            positions = {
                motor_id: current[motor_id]
                + (target[motor_id] - current[motor_id]) * fraction
                for motor_id in TIANYI_ARM_MOTOR_IDS
            }
            self._publish(
                positions,
                speed_rad_s=self.init_speed_rad_s,
            )
        self._wait_for_target(target, cancel_event, label=self.INIT_POSE_NAME)

    def _play_action(self, action_name: str, cancel_event: threading.Event) -> None:
        trajectory = self.artifact_loader.validate_action(action_name)
        arm_positions = extract_arm_positions(trajectory)
        self._require_close(
            self._current_positions(),
            self._row_by_motor_id(arm_positions[0]),
            tolerance=self.start_tolerance_rad,
            label="action start",
        )

        started_at = self._monotonic()
        previous = arm_positions[0]
        for index, (timestamp, row) in enumerate(
            zip(trajectory.timestamps, arm_positions, strict=True)
        ):
            self._wait_until(started_at + float(timestamp), cancel_event)
            self.status_monitor.require_ready()
            if index == 0:
                speed = self.minimum_command_speed_rad_s
            else:
                interval = float(
                    trajectory.timestamps[index] - trajectory.timestamps[index - 1]
                )
                speed = max(
                    self.minimum_command_speed_rad_s,
                    float(np.max(np.abs(row - previous))) / interval,
                )
            if speed > self.maximum_action_speed_rad_s:
                raise RuntimeError(
                    f"Action {action_name} requires {speed:.4f} rad/s; limit is "
                    f"{self.maximum_action_speed_rad_s:.4f} rad/s"
                )
            self._publish(self._row_by_motor_id(row), speed_rad_s=speed)
            previous = row

        final_target = self._row_by_motor_id(arm_positions[-1])
        self._wait_for_target(final_target, cancel_event, label="action final pose")
        self._require_close(
            final_target,
            self._init_positions(),
            tolerance=1e-8,
            label="action final pose versus concierge_init",
        )

    def hold_current(self) -> None:
        """Command the current measured pose after an explicit cancellation."""
        self._publish(
            self._current_positions(),
            speed_rad_s=self.minimum_command_speed_rad_s,
        )

    def _wait_until(self, target_time: float, cancel_event: threading.Event) -> None:
        while True:
            if cancel_event.is_set():
                self.hold_current()
                raise ConciergeTaskCancelled("Task was cancelled during Tianyi arm motion")
            remaining = target_time - self._monotonic()
            if remaining <= 0.0:
                if -remaining > self.maximum_schedule_lag_seconds:
                    raise RuntimeError(
                        f"Tianyi arm playback fell {-remaining:.3f} seconds behind schedule"
                    )
                return
            if cancel_event.wait(remaining):
                self.hold_current()
                raise ConciergeTaskCancelled("Task was cancelled during Tianyi arm motion")

    def _wait_for_target(
        self,
        target: dict[int, float],
        cancel_event: threading.Event,
        *,
        label: str,
    ) -> None:
        deadline = self._monotonic() + self.convergence_timeout_seconds
        while True:
            current = self._current_positions()
            difference = self._maximum_difference(current, target)
            if difference <= self.final_tolerance_rad:
                return
            if self._monotonic() >= deadline:
                raise RuntimeError(
                    f"Tianyi arms did not reach {label}: maximum difference is "
                    f"{difference:.4f} rad"
                )
            if cancel_event.wait(0.02):
                self.hold_current()
                raise ConciergeTaskCancelled("Task was cancelled during Tianyi arm motion")

    def _publish(self, positions: dict[int, float], *, speed_rad_s: float) -> None:
        batch = self.command_builder.build(
            positions_by_motor_id=positions,
            speed_rad_s=speed_rad_s,
            maximum_current_a=self.maximum_current_a_by_motor_id,
        )
        self.command_sink.publish(batch)

    def _init_positions(self) -> dict[int, float]:
        pose = self.artifact_loader.load_pose(
            pose_type="base",
            name=self.INIT_POSE_NAME,
        )
        return {
            motor_id: pose[RECORDER_NAME_BY_MOTOR_ID[motor_id]]
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }

    def _current_positions(self) -> dict[int, float]:
        return self.status_monitor.require_ready().positions_by_motor_id()

    @staticmethod
    def _row_by_motor_id(row: np.ndarray) -> dict[int, float]:
        return {
            motor_id: float(position)
            for motor_id, position in zip(TIANYI_ARM_MOTOR_IDS, row, strict=True)
        }

    @classmethod
    def _require_close(
        cls,
        actual: dict[int, float],
        expected: dict[int, float],
        *,
        tolerance: float,
        label: str,
    ) -> None:
        difference = cls._maximum_difference(actual, expected)
        if difference > tolerance:
            raise RuntimeError(
                f"Tianyi arms are not at {label}: maximum difference is "
                f"{difference:.4f} rad (limit {tolerance:.4f} rad)"
            )

    @staticmethod
    def _maximum_difference(
        actual: dict[int, float], expected: dict[int, float]
    ) -> float:
        return max(
            abs(actual[motor_id] - expected[motor_id])
            for motor_id in TIANYI_ARM_MOTOR_IDS
        )

    @staticmethod
    def _positive(value: object, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a real number")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized <= 0.0:
            raise ValueError(f"{label} must be finite and greater than zero")
        return normalized

    @classmethod
    def _maximum_currents(
        cls,
        values: Mapping[int, object],
    ) -> dict[int, float]:
        if set(values) != set(TIANYI_ARM_MOTOR_IDS):
            raise ValueError(
                "Arm maximum-current settings must cover exactly the 14 arm motors"
            )
        return {
            motor_id: cls._positive(
                values[motor_id],
                f"Arm motor {motor_id} maximum current",
            )
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }

    class _Operation:
        def __init__(self, lock: threading.Lock) -> None:
            self.lock = lock

        def __enter__(self) -> None:
            if not self.lock.acquire(blocking=False):
                raise RuntimeError("Another Tianyi arm operation is already running")

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            self.lock.release()

    def _operation(self) -> _Operation:
        return self._Operation(self._operation_lock)
