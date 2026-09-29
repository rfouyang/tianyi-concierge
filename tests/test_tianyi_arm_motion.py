import unittest

import numpy as np

from component.common.errors import ConciergeTaskCancelled
from component.common.tianyi_arm_motion import TianyiArmMotionService
from util.tianyi_action_artifact import (
    RECORDER_JOINT_NAMES,
    TianyiActionTrajectory,
)
from util.tianyi_arm_command import TianyiArmCommandBuilder
from util.tianyi_arm_mapping import (
    RECORDER_NAME_BY_MOTOR_ID,
    TIANYI_ARM_MOTOR_IDS,
)
from util.tianyi_arm_status import (
    TianyiArmMotorStatus,
    TianyiArmStatusSnapshot,
)


class FakeArtifacts:
    joint_limits = {name: (-2.0, 2.0) for name in RECORDER_JOINT_NAMES}

    def __init__(self):
        self.init = {name: 0.0 for name in RECORDER_JOINT_NAMES}
        for motor_id in TIANYI_ARM_MOTOR_IDS:
            self.init[RECORDER_NAME_BY_MOTOR_ID[motor_id]] = 0.2
        positions = np.zeros((3, len(RECORDER_JOINT_NAMES)), dtype=np.float64)
        for motor_id in TIANYI_ARM_MOTOR_IDS:
            index = RECORDER_JOINT_NAMES.index(RECORDER_NAME_BY_MOTOR_ID[motor_id])
            positions[:, index] = (0.2, 0.3, 0.2)
        self.trajectory = TianyiActionTrajectory(
            action_name="wave",
            robot_model_id="fixture",
            fps=25.0,
            joint_names=RECORDER_JOINT_NAMES,
            timestamps=np.asarray([0.0, 0.04, 0.08]),
            joint_positions=positions,
            keyframe_sample_indices=(0, 1, 2),
            source_pose_names=("concierge_init", "wave", "concierge_init"),
            keyframe_hold_seconds=(0.0, 0.0, 0.0),
        )

    def load_pose(self, *, pose_type, name):
        if (pose_type, name) != ("base", "concierge_init"):
            raise AssertionError((pose_type, name))
        return dict(self.init)

    def validate_action(self, name):
        if name != "wave":
            raise AssertionError(name)
        return self.trajectory


class FakeStatus:
    def __init__(self):
        self.positions = {motor_id: 0.0 for motor_id in TIANYI_ARM_MOTOR_IDS}
        self.error = None

    def require_ready(self):
        if self.error is not None:
            raise RuntimeError(self.error)
        return TianyiArmStatusSnapshot(
            motors=tuple(
                TianyiArmMotorStatus(
                    motor_id=motor_id,
                    position=self.positions[motor_id],
                    speed=0.0,
                    current=0.0,
                    temperature=25.0,
                    error=0,
                    received_at=0.0,
                )
                for motor_id in TIANYI_ARM_MOTOR_IDS
            )
        )


class FakeSink:
    def __init__(self, status):
        self.status = status
        self.batches = []

    def publish(self, batch):
        self.batches.append(batch)
        self.status.positions = batch.positions_by_motor_id()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FakeCancelEvent:
    def __init__(self, clock, cancel_after_waits=None):
        self.clock = clock
        self.cancel_after_waits = cancel_after_waits
        self.wait_count = 0
        self.cancelled = False

    def is_set(self):
        return self.cancelled

    def wait(self, timeout):
        self.clock.now += timeout
        self.wait_count += 1
        if (
            self.cancel_after_waits is not None
            and self.wait_count >= self.cancel_after_waits
        ):
            self.cancelled = True
        return self.cancelled


class TianyiArmMotionServiceTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = FakeArtifacts()
        self.status = FakeStatus()
        self.sink = FakeSink(self.status)
        self.clock = FakeClock()
        self.service = TianyiArmMotionService(
            artifact_loader=self.artifacts,
            status_monitor=self.status,
            command_builder=TianyiArmCommandBuilder(self.artifacts),
            command_sink=self.sink,
            sample_frequency_hz=5.0,
            init_speed_rad_s=0.2,
            maximum_action_speed_rad_s=3.0,
            monotonic=self.clock.monotonic,
        )

    def test_moves_to_init_before_playing_and_returns_to_init(self):
        self.service.execute("wave", FakeCancelEvent(self.clock))

        published = [batch.positions_by_motor_id()[11] for batch in self.sink.batches]
        np.testing.assert_allclose(published[:5], [0.04, 0.08, 0.12, 0.16, 0.2])
        np.testing.assert_allclose(published[5:], [0.2, 0.3, 0.2])
        self.assertEqual(self.status.positions[11], 0.2)
        self.assertTrue(
            all(
                set(batch.positions_by_motor_id()) == set(TIANYI_ARM_MOTOR_IDS)
                for batch in self.sink.batches
            )
        )
        expected_currents = {
            motor_id: 5.0 if motor_id % 10 <= 4 else 3.0
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }
        self.assertTrue(
            all(
                batch.maximum_currents_by_motor_id() == expected_currents
                for batch in self.sink.batches
            )
        )

    def test_prepared_action_rejects_wrong_start_pose(self):
        with self.assertRaisesRegex(RuntimeError, "not at action start"):
            self.service.play_prepared_action(
                "wave",
                FakeCancelEvent(self.clock),
            )
        self.assertEqual(self.sink.batches, [])

    def test_status_failure_blocks_motion_before_publish(self):
        self.status.error = "arm motor fault"

        with self.assertRaisesRegex(RuntimeError, "arm motor fault"):
            self.service.execute("wave", FakeCancelEvent(self.clock))
        self.assertEqual(self.sink.batches, [])

    def test_cancellation_publishes_measured_hold(self):
        event = FakeCancelEvent(self.clock, cancel_after_waits=2)

        with self.assertRaises(ConciergeTaskCancelled):
            self.service.execute("wave", event)

        self.assertGreaterEqual(len(self.sink.batches), 2)
        self.assertEqual(
            self.sink.batches[-1].positions_by_motor_id(),
            self.status.positions,
        )


if __name__ == "__main__":
    unittest.main()
