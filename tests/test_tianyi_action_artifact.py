import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from util.tianyi_action_artifact import (
    RECORDER_JOINT_NAMES,
    TianyiActionArtifactLoader,
)


class TianyiActionArtifactLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.recorder_dir = Path(self.temporary_directory.name)
        self._write_fixture()
        self.loader = TianyiActionArtifactLoader(self.recorder_dir)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_fixture(self):
        action_dir = self.recorder_dir / "data" / "actions"
        trajectory_dir = self.recorder_dir / "data" / "trajectories"
        pose_dir = self.recorder_dir / "data" / "poses"
        asset_dir = self.recorder_dir / "asset" / "tianyi2"
        for directory in (
            action_dir,
            trajectory_dir,
            pose_dir / "base",
            pose_dir / "composed",
            asset_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        joints = "\n".join(
            f'<joint name="{name}" type="revolute"><limit lower="-3" upper="3"/></joint>'
            for name in RECORDER_JOINT_NAMES
        )
        urdf = f'<robot name="fixture">{joints}</robot>\n'.encode()
        (asset_dir / "tianyi.urdf").write_bytes(urdf)
        self._write_json(
            asset_dir / "model_metadata.json",
            {
                "schema_version": 1,
                "model_id": "fixture-tianyi",
                "urdf": "tianyi.urdf",
                "sha256": {"tianyi.urdf": hashlib.sha256(urdf).hexdigest()},
            },
        )

        zero_values = {name: 0.0 for name in RECORDER_JOINT_NAMES}
        wave_values = dict(zero_values)
        wave_values["shoulder_pitch_l_joint"] = 0.2
        self._write_pose(
            pose_dir / "base" / "concierge_init.json", "concierge_init", "base", zero_values
        )
        self._write_pose(pose_dir / "composed" / "wave.json", "wave", "composed", wave_values)
        self._write_json(
            action_dir / "wave.json",
            {
                "schema_version": 1,
                "name": "wave",
                "robot_model_id": "fixture-tianyi",
                "initial_pose": {"pose_type": "base", "name": "concierge_init"},
                "transitions": [
                    {
                        "target_pose": {"pose_type": "composed", "name": "wave"},
                        "duration_seconds": 0.04,
                        "hold_seconds": 0.0,
                    },
                    {
                        "target_pose": {"pose_type": "base", "name": "concierge_init"},
                        "duration_seconds": 0.04,
                        "hold_seconds": 0.0,
                    },
                ],
                "created_at": "2026-09-14T00:00:00Z",
                "notes": "",
            },
        )
        positions = np.zeros((3, len(RECORDER_JOINT_NAMES)), dtype=np.float64)
        positions[1, RECORDER_JOINT_NAMES.index("shoulder_pitch_l_joint")] = 0.2
        np.savez_compressed(
            trajectory_dir / "wave.npz",
            schema_version=np.asarray(1, dtype=np.int64),
            action_name=np.asarray("wave"),
            robot_model_id=np.asarray("fixture-tianyi"),
            fps=np.asarray(25.0, dtype=np.float64),
            joint_names=np.asarray(RECORDER_JOINT_NAMES),
            timestamps=np.asarray([0.0, 0.04, 0.08], dtype=np.float64),
            joint_positions=positions,
            keyframe_sample_indices=np.asarray([0, 1, 2], dtype=np.int64),
            source_pose_names=np.asarray(["concierge_init", "wave", "concierge_init"]),
            keyframe_hold_seconds=np.asarray([0.0, 0.0, 0.0], dtype=np.float64),
        )

    def _write_pose(self, path, name, pose_type, values):
        self._write_json(
            path,
            {
                "schema_version": 1,
                "name": name,
                "pose_type": pose_type,
                "robot_model_id": "fixture-tianyi",
                "joint_values": values,
                "source": "simulation",
                "created_at": "2026-09-14T00:00:00Z",
                "source_parts": {},
                "notes": "",
            },
        )

    @staticmethod
    def _write_json(path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_validates_complete_recorder_action_without_conversion(self):
        self.assertEqual(self.loader.list_action_names(), ("wave",))

        trajectory = self.loader.validate_action("wave")

        self.assertEqual(trajectory.robot_model_id, "fixture-tianyi")
        self.assertEqual(trajectory.joint_names, RECORDER_JOINT_NAMES)
        self.assertEqual(trajectory.sample_count, 3)
        self.assertAlmostEqual(trajectory.duration_seconds, 0.08)
        self.assertFalse(trajectory.timestamps.flags.writeable)
        self.assertFalse(trajectory.joint_positions.flags.writeable)

    def test_rejects_trajectory_with_different_joint_order(self):
        path = self.recorder_dir / "data" / "trajectories" / "wave.npz"
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: archive[name].copy() for name in archive.files}
        arrays["joint_names"] = arrays["joint_names"][::-1]
        np.savez_compressed(path, **arrays)

        with self.assertRaisesRegex(ValueError, "canonical 17 recorder joints"):
            self.loader.validate_action("wave")

    def test_rejects_position_outside_canonical_urdf_limit(self):
        path = self.recorder_dir / "data" / "trajectories" / "wave.npz"
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: archive[name].copy() for name in archive.files}
        arrays["joint_positions"][1, 0] = 4.0
        np.savez_compressed(path, **arrays)

        with self.assertRaisesRegex(ValueError, "exceeds its model limit"):
            self.loader.validate_action("wave")

    def test_rejects_recorder_urdf_that_no_longer_matches_metadata(self):
        urdf_path = self.recorder_dir / "asset" / "tianyi2" / "tianyi.urdf"
        urdf_path.write_text("<robot name='changed'/>", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "URDF hash"):
            self.loader.validate_action("wave")


class BundledTianyiActionTests(unittest.TestCase):
    def test_default_loader_uses_self_contained_tianyi_concierge_bundle(self):
        loader = TianyiActionArtifactLoader()

        action_names = loader.list_action_names()
        self.assertIn("concierge_present_left", action_names)
        self.assertGreaterEqual(len(action_names), 1)
        for action_name in action_names:
            trajectory = loader.validate_action(action_name)
            self.assertGreaterEqual(trajectory.sample_count, 2)
            self.assertGreater(trajectory.duration_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
