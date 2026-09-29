from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from .tianyi_action_artifact import RECORDER_JOINT_NAMES, TianyiActionTrajectory


@dataclass(frozen=True, slots=True)
class TianyiArmJoint:
    """Map one recorder joint to its Tianyi SDK arm motor."""

    recorder_name: str
    motor_id: int
    side: str


TIANYI_ARM_JOINTS = (
    TianyiArmJoint("shoulder_pitch_l_joint", 11, "left"),
    TianyiArmJoint("shoulder_roll_l_joint", 12, "left"),
    TianyiArmJoint("shoulder_yaw_l_joint", 13, "left"),
    TianyiArmJoint("elbow_pitch_l_joint", 14, "left"),
    TianyiArmJoint("elbow_yaw_l_joint", 15, "left"),
    TianyiArmJoint("wrist_pitch_l_joint", 16, "left"),
    TianyiArmJoint("wrist_roll_l_joint", 17, "left"),
    TianyiArmJoint("shoulder_pitch_r_joint", 21, "right"),
    TianyiArmJoint("shoulder_roll_r_joint", 22, "right"),
    TianyiArmJoint("shoulder_yaw_r_joint", 23, "right"),
    TianyiArmJoint("elbow_pitch_r_joint", 24, "right"),
    TianyiArmJoint("elbow_yaw_r_joint", 25, "right"),
    TianyiArmJoint("wrist_pitch_r_joint", 26, "right"),
    TianyiArmJoint("wrist_roll_r_joint", 27, "right"),
)

TIANYI_ARM_MOTOR_IDS = tuple(joint.motor_id for joint in TIANYI_ARM_JOINTS)
RECORDER_ARM_JOINT_NAMES = tuple(joint.recorder_name for joint in TIANYI_ARM_JOINTS)
RECORDER_ARM_INDEXES = tuple(
    RECORDER_JOINT_NAMES.index(joint_name)
    for joint_name in RECORDER_ARM_JOINT_NAMES
)
RECORDER_NAME_BY_MOTOR_ID = MappingProxyType(
    {joint.motor_id: joint.recorder_name for joint in TIANYI_ARM_JOINTS}
)


def extract_arm_positions(
    trajectory: TianyiActionTrajectory,
) -> NDArray[np.float64]:
    """Select the two arms in SDK motor order, excluding all other joints."""
    if trajectory.joint_names != RECORDER_JOINT_NAMES:
        raise ValueError("Trajectory does not use the canonical recorder joint order")
    positions = trajectory.joint_positions[:, RECORDER_ARM_INDEXES].copy()
    positions.flags.writeable = False
    return positions


def arm_positions_by_motor_id(
    trajectory: TianyiActionTrajectory,
    sample_index: int,
) -> dict[int, float]:
    """Return one trajectory sample keyed only by the 14 arm motor IDs."""
    if isinstance(sample_index, bool) or not isinstance(sample_index, int):
        raise ValueError("Trajectory sample index must be an integer")
    if not 0 <= sample_index < trajectory.sample_count:
        raise IndexError(f"Trajectory sample index is out of range: {sample_index}")
    positions = extract_arm_positions(trajectory)[sample_index]
    return {
        motor_id: float(position)
        for motor_id, position in zip(TIANYI_ARM_MOTOR_IDS, positions, strict=True)
    }
