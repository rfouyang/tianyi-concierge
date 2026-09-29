from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _uuid(value, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a valid UUID") from exc


@dataclass(frozen=True)
class ConciergeBodyAction:
    action_id: str
    phase: str = "with_speech"
    required: bool = True

    @classmethod
    def from_dict(cls, value: dict) -> ConciergeBodyAction:
        if not isinstance(value, dict):
            raise ValueError("Task arm action must be an object")
        action_id = str(value.get("action_id") or "").strip()
        if not action_id:
            raise ValueError("Task arm action ID is required")
        phase = str(value.get("phase") or "with_speech").strip()
        if phase == "before_speech":
            phase = "with_speech"
        if phase != "with_speech":
            raise ValueError(f"Unsupported task arm action phase: {phase}")
        required = value.get("required", True)
        if not isinstance(required, bool):
            raise ValueError("Task arm action required flag must be a boolean")
        return cls(action_id=action_id, phase=phase, required=required)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "phase": self.phase,
            "required": self.required,
        }


UPLOADED_AUDIO_PATTERN = re.compile(r"^upload_[0-9a-f]{24}\.wav$")


@dataclass(frozen=True)
class ConciergeStop:
    poi_id: str
    poi_name: str
    content: str
    actions: list[ConciergeBodyAction] = field(default_factory=list)
    audio: str | None = None
    audio_name: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> ConciergeStop:
        if not isinstance(value, dict):
            raise ValueError("Each task stop must be an object")
        poi_id = _uuid(value.get("poi_id"), "POI ID")
        poi_name = str(value.get("poi_name") or "").strip()
        content = str(value.get("content") or "").strip()
        if not poi_name:
            raise ValueError("Each task stop must have a POI name")
        if not content:
            raise ValueError(f"Arrival content is required for POI '{poi_name}'")
        raw_actions = value.get("actions")
        if raw_actions is None:
            legacy_action = value.get("action")
            raw_actions = [] if legacy_action is None else [legacy_action]
        if not isinstance(raw_actions, list):
            raise ValueError("Task stop actions must be a list")
        actions = [ConciergeBodyAction.from_dict(action) for action in raw_actions]
        audio = str(value.get("audio") or "").strip() or None
        if audio is not None and not UPLOADED_AUDIO_PATTERN.fullmatch(audio):
            raise ValueError(f"Uploaded speech for POI '{poi_name}' has an invalid file name")
        audio_name = str(value.get("audio_name") or "").strip()[:120] or None
        return cls(poi_id, poi_name, content, actions, audio, audio_name if audio else None)

    def to_dict(self) -> dict:
        value = {
            "poi_id": self.poi_id,
            "poi_name": self.poi_name,
            "content": self.content,
            "actions": [action.to_dict() for action in self.actions],
        }
        if self.audio:
            value["audio"] = self.audio
            if self.audio_name:
                value["audio_name"] = self.audio_name
        return value


@dataclass(frozen=True)
class ConciergeTask:
    id: str
    name: str
    stops: list[ConciergeStop]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict, *, require_stops: bool = False) -> ConciergeTask:
        if not isinstance(value, dict):
            raise ValueError("Each task must be an object")
        task_id = _uuid(value.get("id"), "Task ID")
        name = str(value.get("name") or "").strip()
        if not name:
            raise ValueError("Task name cannot be empty")
        raw_stops = value.get("stops")
        if not isinstance(raw_stops, list):
            raise ValueError(f"Task '{name}' stops must be a list")
        stops = [ConciergeStop.from_dict(stop) for stop in raw_stops]
        if require_stops and not stops:
            raise ValueError(f"Task '{name}' must contain at least one POI")
        return cls(
            id=task_id,
            name=name,
            stops=stops,
            created_at=str(value.get("created_at") or datetime.now(timezone.utc).isoformat()),
            updated_at=str(value.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "stops": [stop.to_dict() for stop in self.stops],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
