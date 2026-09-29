from __future__ import annotations

import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from component.common.body_action import BodyActionClient
from component.common.errors import ConciergeTaskCancelled
from util.audio_helper import AudioPlayer

BASE_DIR = Path(__file__).resolve().parents[2]
LEFT_MESSAGE = (
    "Sorry to interrupt. There may be an issue with your tap. "
    "Please check with our staff before continuing."
)
RIGHT_MESSAGE = (
    "Sorry to interrupt. There may be an issue with your entry. "
    "Please check with our staff before continuing."
)


@dataclass(frozen=True, slots=True)
class MrtAction:
    label: str
    message: str
    audio_file: str


MRT_ACTIONS = {
    "urs_mrt_stop_left": MrtAction("Stop Left 1", LEFT_MESSAGE, "mrt_stop_left.wav"),
    "urs_mrt_stop_left_2": MrtAction("Stop Left 2", LEFT_MESSAGE, "mrt_stop_left.wav"),
    "urs_mrt_stop_right": MrtAction(
        "Stop Right 1", RIGHT_MESSAGE, "mrt_stop_right.wav"
    ),
    "urs_mrt_stop_right_2": MrtAction(
        "Stop Right 2", RIGHT_MESSAGE, "mrt_stop_right.wav"
    ),
}
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class MrtInterventionService:
    """Run one authenticated MRT announcement and arm gesture at a time."""

    def __init__(
        self,
        *,
        body_actions: BodyActionClient | None = None,
        player: AudioPlayer | None = None,
        audio_dir: Path | str = BASE_DIR / "data/tts",
        busy_check=None,
    ) -> None:
        """``busy_check`` returns a reason when a tour or manual move holds the robot."""
        self.body_actions = body_actions or BodyActionClient()
        self.busy_check = busy_check
        self.player = player or AudioPlayer()
        self.audio_dir = Path(audio_dir)
        self._lock = threading.Lock()
        self._operations: dict[str, dict[str, object]] = {}
        self._operation_by_request_id: dict[str, str] = {}
        self._active_operation_id: str | None = None
        self._active_cancel_event: threading.Event | None = None

    def list_actions(self) -> list[dict[str, object]]:
        """Return the four allowed MRT actions that pass artifact validation."""
        available = {
            str(action["action_id"]): action
            for action in self.body_actions.list_actions()
        }
        return [
            {
                "action_id": action_id,
                "label": action.label,
                "message": action.message,
                "ready": action_id in available and self._audio_path(action_id).is_file(),
                "duration": (
                    available[action_id].get("duration")
                    if action_id in available
                    else None
                ),
            }
            for action_id, action in MRT_ACTIONS.items()
        ]

    def health(self) -> dict[str, object]:
        """Return read-only readiness plus the current operation."""
        body_health = self.body_actions.health()
        actions = self.list_actions()
        with self._lock:
            active_id = self._active_operation_id
            active = dict(self._operations[active_id]) if active_id else None
        return {
            "ready": bool(body_health.get("ready"))
            and all(action["ready"] for action in actions),
            "error": body_health.get("error"),
            "motor_count": body_health.get("motor_count", 0),
            "actions": actions,
            "active_operation": active,
        }

    def start(
        self,
        *,
        request_id: str,
        action_id: str,
        arm_motion_confirmed: bool,
    ) -> tuple[dict[str, object], bool]:
        """Start an intervention and return ``(operation, newly_created)``."""
        normalized_request_id = self._validate_request_id(request_id)
        normalized_action_id = str(action_id).strip()
        if normalized_action_id not in MRT_ACTIONS:
            raise ValueError(f"Unsupported MRT action: {normalized_action_id}")
        if arm_motion_confirmed is not True:
            raise PermissionError("Explicit Tianyi arm-motion confirmation is required")

        with self._lock:
            existing_id = self._operation_by_request_id.get(normalized_request_id)
            if existing_id is not None:
                existing = self._operations[existing_id]
                if existing["action_id"] != normalized_action_id:
                    raise ValueError(
                        "request_id was already used with different intervention data"
                    )
                return dict(existing), False

            if self._active_operation_id is not None:
                raise RuntimeError("Another MRT intervention is already active")
            reason = self.busy_check() if self.busy_check else None
            if reason:
                raise RuntimeError(reason)

            ready_actions = {
                str(action["action_id"])
                for action in self.list_actions()
                if action.get("ready") is True
            }
            if normalized_action_id not in ready_actions:
                raise ValueError(f"MRT action is unavailable: {normalized_action_id}")

            operation_id = uuid.uuid4().hex
            created_at = self._now()
            action = MRT_ACTIONS[normalized_action_id]
            audio_path = self._audio_path(normalized_action_id)
            operation = {
                "operation_id": operation_id,
                "request_id": normalized_request_id,
                "action_id": normalized_action_id,
                "text": action.message,
                "status": "accepted",
                "message": "Intervention accepted",
                "created_at": created_at,
                "updated_at": created_at,
                "audio_path": str(audio_path),
                "error": None,
            }
            cancel_event = threading.Event()
            self._operations[operation_id] = operation
            self._operation_by_request_id[normalized_request_id] = operation_id
            self._active_operation_id = operation_id
            self._active_cancel_event = cancel_event

        thread = threading.Thread(
            target=self._run,
            args=(operation_id, cancel_event),
            name=f"mrt-intervention-{operation_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.get(operation_id), True

    @property
    def active_operation_id(self) -> str | None:
        with self._lock:
            return self._active_operation_id

    def recent(self, limit: int = 10) -> list[dict[str, object]]:
        """Return the newest interventions first (kept in memory only)."""
        with self._lock:
            operations = [dict(operation) for operation in self._operations.values()]
        return sorted(operations, key=lambda item: str(item["created_at"]), reverse=True)[:limit]

    def get(self, operation_id: str) -> dict[str, object]:
        normalized = str(operation_id).strip()
        with self._lock:
            if normalized not in self._operations:
                raise KeyError(normalized)
            return dict(self._operations[normalized])

    def cancel(self, operation_id: str) -> dict[str, object]:
        normalized = str(operation_id).strip()
        with self._lock:
            if normalized not in self._operations:
                raise KeyError(normalized)
            operation = self._operations[normalized]
            if operation["status"] in TERMINAL_STATUSES:
                return dict(operation)
            if normalized != self._active_operation_id:
                raise RuntimeError("The requested MRT intervention is not active")
            cancel_event = self._active_cancel_event
            operation["status"] = "cancelling"
            operation["message"] = "Cancellation requested"
            operation["updated_at"] = self._now()
        if cancel_event is not None:
            cancel_event.set()
        self.body_actions.cancel_current()
        return self.get(normalized)

    def close(self) -> None:
        """Cancel active motion and release ROS resources."""
        with self._lock:
            cancel_event = self._active_cancel_event
        if cancel_event is not None:
            cancel_event.set()
        self.body_actions.close()

    def _run(self, operation_id: str, cancel_event: threading.Event) -> None:
        operation = self.get(operation_id)
        action_id = str(operation["action_id"])
        audio_path = Path(str(operation["audio_path"]))
        try:
            self._raise_if_cancelled(cancel_event)
            self._update(
                operation_id,
                "preparing_arms",
                "Checking and preparing the Tianyi arms",
            )
            arm_token = self.body_actions.arm([action_id], confirmed=True)
            self.body_actions.prepare(arm_token)

            self._raise_if_cancelled(cancel_event)
            self._update(
                operation_id,
                "performing",
                "Performing the gesture and announcement",
            )
            self._perform(action_id, arm_token, audio_path, cancel_event)
            self._update(operation_id, "completed", "Intervention completed")
        except ConciergeTaskCancelled as error:
            self._update(operation_id, "cancelled", str(error))
        except Exception as error:
            if cancel_event.is_set():
                self._update(operation_id, "cancelled", "Intervention cancelled")
            else:
                self._update(
                    operation_id,
                    "failed",
                    "Intervention failed",
                    error=str(error),
                )
        finally:
            with self._lock:
                if self._active_operation_id == operation_id:
                    self._active_operation_id = None
                    self._active_cancel_event = None

    def _perform(
        self,
        action_id: str,
        arm_token: str,
        audio_path: Path,
        cancel_event: threading.Event,
    ) -> None:
        start = threading.Event()

        def run_together(function, *args):
            start.wait()
            return function(*args)

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mrt") as executor:
            action = executor.submit(
                run_together,
                self.body_actions.execute,
                action_id,
                arm_token,
                cancel_event,
            )
            speech = executor.submit(run_together, self.player.play, audio_path)
            start.set()
            action.result()
            speech.result()

    def _update(
        self,
        operation_id: str,
        status: str | None = None,
        message: str | None = None,
        *,
        error: str | None = None,
    ) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            if status is not None:
                operation["status"] = status
            if message is not None:
                operation["message"] = message
            operation["updated_at"] = self._now()
            operation["error"] = error

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise ConciergeTaskCancelled("Intervention cancelled")

    @staticmethod
    def _validate_request_id(request_id: str) -> str:
        normalized = str(request_id).strip()
        if not REQUEST_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "request_id must be 1-128 path-safe letters, numbers, or ._:-"
            )
        return normalized

    def _audio_path(self, action_id: str) -> Path:
        return self.audio_dir / MRT_ACTIONS[action_id].audio_file

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
