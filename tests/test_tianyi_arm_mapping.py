import unittest

import numpy as np

from util.tianyi_action_artifact import (
    RECORDER_JOINT_NAMES,
    TianyiActionTrajectory,
)
from util.tianyi_arm_mapping import (
    RECORDER_ARM_INDEXES,
    RECORDER_ARM_JOINT_NAMES,
    TIANYI_ARM_MOTOR_IDS,
    arm_positions_by_motor_id,
    extract_arm_positions,
)


class TianyiArmMappingTests(unittest.TestCase):
    def setUp(self):
        positions = np.arange(34, dtype=np.float64).reshape(2, 17) / 10.0
        self.trajectory = TianyiActionTrajectory(
            action_name="fixture",
            robot_model_id="fixture-model",
            fps=25.0,
            joint_names=RECORDER_JOINT_NAMES,
            timestamps=np.asarray([0.0, 0.04], dtype=np.float64),
            joint_positions=positions,
            keyframe_sample_indices=(0, 1),
            source_pose_names=("concierge_init", "concierge_init"),
            keyframe_hold_seconds=(0.0, 0.0),
        )

    def test_maps_only_the_two_arms_to_sdk_motor_ids(self):
        values = arm_positions_by_motor_id(self.trajectory, 1)

        self.assertEqual(tuple(values), tuple(range(11, 18)) + tuple(range(21, 28)))
        expected = self.trajectory.joint_positions[1, RECORDER_ARM_INDEXES]
        np.testing.assert_array_equal(tuple(values.values()), expected)

    def test_never_includes_head_or_non_arm_motors(self):
        values = arm_positions_by_motor_id(self.trajectory, 0)

        self.assertTrue(set(values).isdisjoint({1, 2, 3, 31, 32, 51, 52}))
        self.assertEqual(set(values), set(TIANYI_ARM_MOTOR_IDS))
        self.assertTrue(all("head_" not in name for name in RECORDER_ARM_JOINT_NAMES))

    def test_extracts_an_immutable_fourteen_joint_matrix(self):
        arm_positions = extract_arm_positions(self.trajectory)

        self.assertEqual(arm_positions.shape, (2, 14))
        self.assertFalse(arm_positions.flags.writeable)

    def test_rejects_an_out_of_range_sample(self):
        with self.assertRaisesRegex(IndexError, "out of range"):
            arm_positions_by_motor_id(self.trajectory, 2)


if __name__ == "__main__":
    unittest.main()
