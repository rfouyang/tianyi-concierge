from __future__ import annotations

import hashlib
import json
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

RECORDER_JOINT_NAMES = (
    "head_yaw_joint",
    "head_pitch_joint",
    "head_roll_joint",
    "shoulder_pitch_l_joint",
    "shoulder_roll_l_joint",
    "shoulder_yaw_l_joint",
    "elbow_pitch_l_joint",
    "elbow_yaw_l_joint",
    "wrist_pitch_l_joint",
    "wrist_roll_l_joint",
    "shoulder_pitch_r_joint",
    "shoulder_roll_r_joint",
    "shoulder_yaw_r_joint",
    "elbow_pitch_r_joint",
    "elbow_yaw_r_joint",
    "wrist_pitch_r_joint",
    "wrist_roll_r_joint",
)


@dataclass(frozen=True, slots=True)
class TianyiActionTrajectory:
    """One validated trajectory produced by tianyi-action-recorder."""

    action_name: str
    robot_model_id: str
    fps: float
    joint_names: tuple[str, ...]
    timestamps: NDArray[np.float64]
    joint_positions: NDArray[np.float64]
    keyframe_sample_indices: tuple[int, ...]
    source_pose_names: tuple[str, ...]
    keyframe_hold_seconds: tuple[float, ...]

    @property
    def sample_count(self) -> int:
        return int(self.timestamps.shape[0])

    @property
    def duration_seconds(self) -> float:
        return float(self.timestamps[-1])


class TianyiActionArtifactLoader:
    """Read recorder artifacts without importing or converting their format."""

    TRAJECTORY_ARRAY_NAMES = frozenset(
        {
            "schema_version",
            "action_name",
            "robot_model_id",
            "fps",
            "joint_names",
            "timestamps",
            "joint_positions",
            "keyframe_sample_indices",
            "source_pose_names",
            "keyframe_hold_seconds",
        }
    )
    ACTION_REQUIRED_FIELDS = frozenset(
        {
            "schema_version",
            "name",
            "robot_model_id",
            "initial_pose",
            "transitions",
            "created_at",
        }
    )
    ACTION_ALLOWED_FIELDS = ACTION_REQUIRED_FIELDS | {"notes"}
    POSE_REQUIRED_FIELDS = frozenset(
        {
            "schema_version",
            "name",
            "pose_type",
            "robot_model_id",
            "joint_values",
            "source",
            "created_at",
        }
    )
    POSE_ALLOWED_FIELDS = POSE_REQUIRED_FIELDS | {"source_parts", "notes"}

    def __init__(self, recorder_dir: Path | str | None = None) -> None:
        default_dir = Path(__file__).resolve().parents[1]
        configured_dir = (
            recorder_dir
            or os.getenv("TIANYI_ACTION_DIR")
            or os.getenv("TIANYI_ACTION_RECORDER_DIR")
        )
        self.recorder_dir = Path(configured_dir or default_dir).expanduser().resolve()
        recorder_data_dir = self.recorder_dir / "data"
        self.action_dir = recorder_data_dir / "actions"
        self.trajectory_dir = recorder_data_dir / "trajectories"
        self.pose_dir = recorder_data_dir / "poses"
        self.asset_dir = self.recorder_dir / "asset" / "tianyi2"
        self._model_id: str | None = None
        self._joint_limits: dict[str, tuple[float, float]] | None = None

    def list_action_names(self) -> tuple[str, ...]:
        """Return actions having both an action definition and an NPZ trajectory."""
        if not self.action_dir.is_dir() or not self.trajectory_dir.is_dir():
            return ()
        definitions = {path.stem for path in self.action_dir.glob("*.json")}
        trajectories = {path.stem for path in self.trajectory_dir.glob("*.npz")}
        return tuple(sorted(definitions & trajectories, key=str.casefold))

    def validate_action(self, name: str) -> TianyiActionTrajectory:
        """Resolve and cross-check an action definition, its poses, and its NPZ."""
        normalized = self._safe_name(name)
        definition = self._read_json(self.action_dir / f"{normalized}.json")
        self._require_fields(
            definition,
            required=self.ACTION_REQUIRED_FIELDS,
            allowed=self.ACTION_ALLOWED_FIELDS,
            label="Action",
        )
        if definition["schema_version"] != 1:
            raise ValueError("Unsupported action schema version")
        if definition["name"] != normalized:
            raise ValueError("Action file contains a different action name")
        if definition["robot_model_id"] != self.model_id:
            raise ValueError("Action belongs to a different robot model")

        references, duration = self._validate_action_sequence(definition)
        for pose_type, pose_name in references:
            self.load_pose(pose_type=pose_type, name=pose_name)

        trajectory = self.load_trajectory(normalized)
        expected_pose_names = tuple(pose_name for _, pose_name in references)
        if trajectory.source_pose_names != expected_pose_names:
            raise ValueError("Trajectory source poses do not match the action definition")
        if not math.isclose(
            trajectory.duration_seconds,
            duration,
            rel_tol=0.0,
            abs_tol=1e-8,
        ):
            raise ValueError("Trajectory duration does not match the action definition")
        return trajectory

    def load_trajectory(self, name: str) -> TianyiActionTrajectory:
        normalized = self._safe_name(name)
        path = self.trajectory_dir / f"{normalized}.npz"
        try:
            with np.load(path, allow_pickle=False) as archive:
                arrays = {key: archive[key].copy() for key in archive.files}
        except FileNotFoundError:
            raise FileNotFoundError(f"Tianyi trajectory does not exist: {path}") from None
        except (OSError, ValueError) as error:
            raise ValueError(f"Could not read Tianyi trajectory {path}: {error}") from error

        if set(arrays) != self.TRAJECTORY_ARRAY_NAMES:
            raise ValueError("Trajectory archive does not contain the exact schema-1 arrays")
        if self._scalar_int(arrays["schema_version"], "schema_version") != 1:
            raise ValueError("Unsupported trajectory schema version")

        trajectory = TianyiActionTrajectory(
            action_name=self._scalar_string(arrays["action_name"], "action_name"),
            robot_model_id=self._scalar_string(
                arrays["robot_model_id"], "robot_model_id"
            ),
            fps=self._scalar_float(arrays["fps"], "fps"),
            joint_names=tuple(str(item) for item in arrays["joint_names"].tolist()),
            timestamps=np.asarray(arrays["timestamps"], dtype=np.float64),
            joint_positions=np.asarray(arrays["joint_positions"], dtype=np.float64),
            keyframe_sample_indices=tuple(
                int(item) for item in arrays["keyframe_sample_indices"].tolist()
            ),
            source_pose_names=tuple(
                str(item) for item in arrays["source_pose_names"].tolist()
            ),
            keyframe_hold_seconds=tuple(
                float(item) for item in arrays["keyframe_hold_seconds"].tolist()
            ),
        )
        self._validate_trajectory(trajectory, requested_name=normalized)
        trajectory.timestamps.flags.writeable = False
        trajectory.joint_positions.flags.writeable = False
        return trajectory

    def load_pose(self, *, pose_type: str, name: str) -> dict[str, float]:
        if pose_type not in {"base", "composed"}:
            raise ValueError(f"Hardware action pose must be base or composed: {pose_type}")
        normalized = self._safe_name(name)
        payload = self._read_json(self.pose_dir / pose_type / f"{normalized}.json")
        self._require_fields(
            payload,
            required=self.POSE_REQUIRED_FIELDS,
            allowed=self.POSE_ALLOWED_FIELDS,
            label="Pose",
        )
        if payload["schema_version"] != 1:
            raise ValueError("Unsupported pose schema version")
        if payload["name"] != normalized or payload["pose_type"] != pose_type:
            raise ValueError("Pose file identity does not match its path")
        if payload["robot_model_id"] != self.model_id:
            raise ValueError("Pose belongs to a different robot model")
        values = payload["joint_values"]
        if not isinstance(values, dict) or set(values) != set(RECORDER_JOINT_NAMES):
            raise ValueError("Hardware action pose must contain exactly 17 authored joints")
        return self._validate_positions(values, label=f"Pose {pose_type}/{normalized}")

    @property
    def model_id(self) -> str:
        if self._model_id is None:
            metadata = self._read_json(self.asset_dir / "model_metadata.json")
            if metadata.get("schema_version") != 1:
                raise ValueError("Unsupported Tianyi model metadata schema")
            model_id = metadata.get("model_id")
            urdf_name = metadata.get("urdf")
            hashes = metadata.get("sha256")
            if not isinstance(model_id, str) or not model_id:
                raise ValueError("Tianyi model metadata has no model_id")
            if not isinstance(urdf_name, str) or not isinstance(hashes, dict):
                raise ValueError("Tianyi model metadata has no canonical URDF contract")
            expected_hash = hashes.get(urdf_name)
            if not isinstance(expected_hash, str):
                raise ValueError("Tianyi model metadata has no canonical URDF hash")
            urdf_path = self.asset_dir / urdf_name
            actual_hash = hashlib.sha256(urdf_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError("Tianyi recorder URDF hash does not match its metadata")
            self._model_id = model_id
        return self._model_id

    @property
    def joint_limits(self) -> dict[str, tuple[float, float]]:
        if self._joint_limits is None:
            metadata = self._read_json(self.asset_dir / "model_metadata.json")
            urdf_name = metadata.get("urdf")
            if not isinstance(urdf_name, str):
                raise ValueError("Tianyi model metadata has no canonical URDF")
            root = ET.parse(self.asset_dir / urdf_name).getroot()
            limits: dict[str, tuple[float, float]] = {}
            for joint in root.findall("joint"):
                name = joint.get("name")
                limit = joint.find("limit")
                if name in RECORDER_JOINT_NAMES and limit is not None:
                    try:
                        limits[name] = (
                            float(limit.attrib["lower"]),
                            float(limit.attrib["upper"]),
                        )
                    except (KeyError, ValueError) as error:
                        raise ValueError(f"Invalid URDF limit for {name}") from error
            if set(limits) != set(RECORDER_JOINT_NAMES):
                missing = sorted(set(RECORDER_JOINT_NAMES) - set(limits))
                raise ValueError(f"Canonical Tianyi URDF is missing joint limits: {missing}")
            self._joint_limits = limits
        return dict(self._joint_limits)

    def _validate_action_sequence(
        self, definition: dict[str, object]
    ) -> tuple[tuple[tuple[str, str], ...], float]:
        initial = self._pose_reference(definition["initial_pose"])
        if initial != ("base", "concierge_init"):
            raise ValueError("Action must start at base/concierge_init")
        transitions = definition["transitions"]
        if not isinstance(transitions, list) or len(transitions) < 2:
            raise ValueError("Action requires an intermediate pose and a return home")
        references = [initial]
        duration = 0.0
        for index, transition in enumerate(transitions):
            if not isinstance(transition, dict):
                raise ValueError(f"Action transition {index} must be an object")
            unknown = set(transition) - {
                "target_pose",
                "duration_seconds",
                "hold_seconds",
            }
            if "target_pose" not in transition or "duration_seconds" not in transition:
                raise ValueError(f"Action transition {index} is incomplete")
            if unknown:
                raise ValueError(f"Action transition {index} has unknown fields")
            reference = self._pose_reference(transition["target_pose"])
            travel = self._duration(transition["duration_seconds"], positive=True)
            hold = self._duration(transition.get("hold_seconds", 0.0), positive=False)
            references.append(reference)
            duration += travel + hold
        if references[-1] != initial:
            raise ValueError("Action must finish at base/concierge_init")
        if self._duration(transitions[-1].get("hold_seconds", 0.0), positive=False) != 0.0:
            raise ValueError("The final home transition cannot add a hold")
        return tuple(references), duration

    def _validate_trajectory(
        self, trajectory: TianyiActionTrajectory, *, requested_name: str
    ) -> None:
        if trajectory.action_name != requested_name:
            raise ValueError("Trajectory archive contains a different action name")
        if trajectory.robot_model_id != self.model_id:
            raise ValueError("Trajectory belongs to a different robot model")
        if trajectory.joint_names != RECORDER_JOINT_NAMES:
            raise ValueError("Trajectory must contain the canonical 17 recorder joints")
        if not math.isfinite(trajectory.fps) or trajectory.fps <= 0.0:
            raise ValueError("Trajectory fps must be finite and greater than zero")
        if trajectory.timestamps.ndim != 1 or trajectory.sample_count < 2:
            raise ValueError("Trajectory timestamps must contain at least two samples")
        if trajectory.joint_positions.shape != (
            trajectory.sample_count,
            len(RECORDER_JOINT_NAMES),
        ):
            raise ValueError("Trajectory joint_positions shape does not match its contract")
        if not np.all(np.isfinite(trajectory.timestamps)) or not np.all(
            np.isfinite(trajectory.joint_positions)
        ):
            raise ValueError("Trajectory values must be finite")
        if trajectory.timestamps[0] != 0.0 or np.any(
            np.diff(trajectory.timestamps) <= 0.0
        ):
            raise ValueError("Trajectory timestamps must strictly increase from zero")
        keyframes = trajectory.keyframe_sample_indices
        if not keyframes or keyframes[0] != 0:
            raise ValueError("Trajectory first keyframe must be sample zero")
        if tuple(sorted(set(keyframes))) != keyframes:
            raise ValueError("Trajectory keyframe indices must be unique and increasing")
        if keyframes[-1] >= trajectory.sample_count:
            raise ValueError("Trajectory keyframe index exceeds its sample count")
        if not (
            len(keyframes)
            == len(trajectory.source_pose_names)
            == len(trajectory.keyframe_hold_seconds)
        ):
            raise ValueError("Trajectory keyframe metadata lengths do not match")
        if any(
            not math.isfinite(value) or value < 0.0
            for value in trajectory.keyframe_hold_seconds
        ):
            raise ValueError("Trajectory hold durations must be finite and nonnegative")
        self._validate_position_matrix(trajectory.joint_positions)

    def _validate_position_matrix(self, positions: NDArray[np.float64]) -> None:
        limits = self.joint_limits
        for index, joint_name in enumerate(RECORDER_JOINT_NAMES):
            lower, upper = limits[joint_name]
            values = positions[:, index]
            if np.any(values < lower) or np.any(values > upper):
                raise ValueError(f"Trajectory joint {joint_name} exceeds its model limit")

    def _validate_positions(
        self, values: dict[object, object], *, label: str
    ) -> dict[str, float]:
        validated: dict[str, float] = {}
        limits = self.joint_limits
        for joint_name in RECORDER_JOINT_NAMES:
            value = values[joint_name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{label} joint {joint_name} must be a real number")
            normalized = float(value)
            lower, upper = limits[joint_name]
            if not math.isfinite(normalized) or not lower <= normalized <= upper:
                raise ValueError(f"{label} joint {joint_name} exceeds its model limit")
            validated[joint_name] = normalized
        return validated

    @staticmethod
    def _pose_reference(value: object) -> tuple[str, str]:
        if not isinstance(value, dict) or set(value) != {"pose_type", "name"}:
            raise ValueError("Action pose reference must contain pose_type and name")
        pose_type = value["pose_type"]
        name = value["name"]
        if pose_type not in {"base", "composed"} or not isinstance(name, str):
            raise ValueError("Action pose reference must identify a base or composed pose")
        return str(pose_type), TianyiActionArtifactLoader._safe_name(name)

    @staticmethod
    def _duration(value: object, *, positive: bool) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Action duration must be a real number")
        normalized = float(value)
        valid = normalized > 0.0 if positive else normalized >= 0.0
        if not math.isfinite(normalized) or not valid:
            raise ValueError("Action duration is outside its allowed range")
        return normalized

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError(f"Tianyi recorder artifact does not exist: {path}") from None
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in {path}: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"JSON artifact root must be an object: {path}")
        return payload

    @staticmethod
    def _require_fields(
        payload: dict[str, object],
        *,
        required: frozenset[str],
        allowed: frozenset[str],
        label: str,
    ) -> None:
        missing = sorted(required - set(payload))
        unknown = sorted(set(payload) - allowed)
        if missing:
            raise ValueError(f"{label} is missing fields: {missing}")
        if unknown:
            raise ValueError(f"{label} has unknown fields: {unknown}")

    @staticmethod
    def _safe_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("Tianyi action name must be a string")
        normalized = name.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or any(character in normalized for character in '<>:"/\\|?*')
            or any(ord(character) < 32 for character in normalized)
        ):
            raise ValueError("Tianyi action name is not path-safe")
        return normalized

    @staticmethod
    def _scalar_string(array: NDArray[np.generic], name: str) -> str:
        if array.shape != ():
            raise ValueError(f"Trajectory {name} must be a scalar")
        return str(array.item())

    @staticmethod
    def _scalar_float(array: NDArray[np.generic], name: str) -> float:
        if array.shape != ():
            raise ValueError(f"Trajectory {name} must be a scalar")
        return float(array.item())

    @staticmethod
    def _scalar_int(array: NDArray[np.generic], name: str) -> int:
        if array.shape != ():
            raise ValueError(f"Trajectory {name} must be a scalar")
        return int(array.item())
