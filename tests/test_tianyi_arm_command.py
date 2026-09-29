import unittest

import numpy as np

from util.tianyi_action_artifact import (
    RECORDER_JOINT_NAMES,
    TianyiActionTrajectory,
)
from util.tianyi_arm_command import TianyiArmCommandBuilder
from util.tianyi_arm_mapping import TIANYI_ARM_MOTOR_IDS


class StubArtifactLoader:
    joint_limits = {
        name: (-2.0, 2.0)
        for name in RECORDER_JOINT_NAMES
    }


class TianyiArmCommandBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = TianyiArmCommandBuilder(StubArtifactLoader())
        self.positions = {
            motor_id: (index - 7) / 10.0
            for index, motor_id in enumerate(TIANYI_ARM_MOTOR_IDS)
        }

    def test_builds_complete_command_in_sdk_motor_order(self):
        batch = self.builder.build(
            positions_by_motor_id=self.positions,
            speed_rad_s=0.5,
            maximum_current_a=2.0,
        )

        self.assertEqual(
            tuple(command.motor_id for command in batch.commands),
            TIANYI_ARM_MOTOR_IDS,
        )
        self.assertTrue(all(command.speed == 0.5 for command in batch.commands))
        self.assertTrue(
            all(command.maximum_current == 2.0 for command in batch.commands)
        )
        self.assertEqual(batch.positions_by_motor_id(), self.positions)

    def test_builds_from_recorder_trajectory_without_head_commands(self):
        positions = np.zeros((2, len(RECORDER_JOINT_NAMES)), dtype=np.float64)
        positions[1] = np.arange(len(RECORDER_JOINT_NAMES)) / 20.0
        trajectory = TianyiActionTrajectory(
            action_name="fixture",
            robot_model_id="fixture",
            fps=25.0,
            joint_names=RECORDER_JOINT_NAMES,
            timestamps=np.asarray([0.0, 0.04]),
            joint_positions=positions,
            keyframe_sample_indices=(0, 1),
            source_pose_names=("concierge_init", "concierge_init"),
            keyframe_hold_seconds=(0.0, 0.0),
        )

        batch = self.builder.from_trajectory_sample(
            trajectory,
            1,
            speed_rad_s=0.4,
            maximum_current_a=1.5,
        )

        self.assertEqual(len(batch.commands), 14)
        self.assertTrue(
            set(batch.positions_by_motor_id()).isdisjoint({1, 2, 3, 31, 32, 51, 52})
        )

    def test_builds_per_motor_maximum_currents(self):
        maximum_currents = {
            motor_id: 5.0 if motor_id % 10 <= 4 else 3.0
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }

        batch = self.builder.build(
            positions_by_motor_id=self.positions,
            speed_rad_s=0.5,
            maximum_current_a=maximum_currents,
        )

        self.assertEqual(
            batch.maximum_currents_by_motor_id(),
            maximum_currents,
        )

    def test_rejects_incomplete_per_motor_maximum_currents(self):
        maximum_currents = {
            motor_id: 5.0 for motor_id in TIANYI_ARM_MOTOR_IDS[:-1]
        }

        with self.assertRaisesRegex(ValueError, "maximum-current motor set"):
            self.builder.build(
                positions_by_motor_id=self.positions,
                speed_rad_s=0.5,
                maximum_current_a=maximum_currents,
            )

    def test_rejects_missing_or_non_arm_motor_ids(self):
        invalid = dict(self.positions)
        invalid.pop(17)
        invalid[3] = 0.0

        with self.assertRaisesRegex(ValueError, "Invalid Tianyi arm motor set"):
            self.builder.build(
                positions_by_motor_id=invalid,
                speed_rad_s=0.5,
                maximum_current_a=2.0,
            )

    def test_rejects_position_outside_recorder_model_limit(self):
        invalid = dict(self.positions)
        invalid[11] = 2.1

        with self.assertRaisesRegex(ValueError, "motor 11 position"):
            self.builder.build(
                positions_by_motor_id=invalid,
                speed_rad_s=0.5,
                maximum_current_a=2.0,
            )

    def test_rejects_invalid_speed_and_current(self):
        with self.assertRaisesRegex(ValueError, "speed"):
            self.builder.build(
                positions_by_motor_id=self.positions,
                speed_rad_s=0.0,
                maximum_current_a=2.0,
            )
        with self.assertRaisesRegex(ValueError, "maximum current"):
            self.builder.build(
                positions_by_motor_id=self.positions,
                speed_rad_s=0.5,
                maximum_current_a=float("nan"),
            )


if __name__ == "__main__":
    unittest.main()
