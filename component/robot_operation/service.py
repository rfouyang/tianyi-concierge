from __future__ import annotations

import copy
import threading
import traceback
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from loguru import logger

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RobotOperationBusy(RuntimeError):
    """Raised when a hardware-affecting operation is already running."""


class RobotOperationRunner:
    """Run one hardware-affecting robot operation at a time in the background.

    Browsers and API clients start work and return immediately; progress is
    read from a revisioned snapshot that the WebSocket streams. Stopping the
    robot is deliberately not routed through here so it never waits in line.
    """

    HISTORY_SIZE = 20
    EVENT_LOG_SIZE = 200

    def __init__(self, busy_check: Callable[[], str | None] | None = None) -> None:
        """``busy_check`` returns a reason when another subsystem holds the robot."""
        self.busy_check = busy_check
        self._lock = threading.Lock()
        self._revision = 0
        self._active: dict | None = None
        self._history: deque[dict] = deque(maxlen=self.HISTORY_SIZE)

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "revision": self._revision,
                "active": copy.deepcopy(self._active),
                "latest": copy.deepcopy(self._history[0]) if self._history else None,
            }

    def history(self) -> list[dict]:
        """Finished operations, newest first (kept in memory only)."""
        with self._lock:
            return [
                {key: value for key, value in item.items() if key != "events"}
                for item in copy.deepcopy(list(self._history))
            ]

    def is_busy(self) -> bool:
        with self._lock:
            return self._active is not None

    def start(
        self,
        kind: str,
        label: str,
        function: Callable[..., Any],
        *args: Any,
        details: dict | None = None,
        **kwargs: Any,
    ) -> dict:
        """Run ``function`` in a thread; its return value becomes the result."""
        operation = self._begin(kind, label, details)

        def target() -> None:
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                self._finish(operation["id"], "failed", error=error)
            else:
                self._finish(operation["id"], "completed", result=result)

        threading.Thread(target=target, name=f"robot-op-{kind}", daemon=True).start()
        return operation

    def start_events(
        self,
        kind: str,
        label: str,
        events: Callable[[], Iterable[dict]],
        *,
        details: dict | None = None,
        on_event: Callable[[dict, dict], None] | None = None,
    ) -> dict:
        """Consume an event generator; its last event decides the final status."""
        operation = self._begin(kind, label, details)

        def target() -> None:
            last_event = None
            try:
                for event in events():
                    last_event = event
                    self._record_event(operation["id"], event, on_event)
            except Exception as error:
                self._finish(operation["id"], "failed", error=error)
                return
            status = (last_event or {}).get("status")
            final = status if status in TERMINAL_STATUSES else "completed"
            self._finish(
                operation["id"],
                final,
                result=last_event,
                message=(last_event or {}).get("message"),
            )

        threading.Thread(target=target, name=f"robot-op-{kind}", daemon=True).start()
        return operation

    def _begin(self, kind: str, label: str, details: dict | None) -> dict:
        reason = self.busy_check() if self.busy_check else None
        if reason:
            raise RobotOperationBusy(reason)
        with self._lock:
            if self._active is not None:
                raise RobotOperationBusy(
                    f"Another robot operation is running: {self._active['label']}"
                )
            self._active = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "label": label,
                "status": "running",
                "message": f"{label} started",
                "details": copy.deepcopy(details or {}),
                "events": [],
                "progress": None,
                "result": None,
                "error": None,
                "started_at": _now(),
                "finished_at": None,
            }
            self._revision += 1
            logger.info(f"Robot operation started: {kind} ({label})")
            return copy.deepcopy(self._active)

    def _record_event(
        self,
        operation_id: str,
        event: dict,
        on_event: Callable[[dict, dict], None] | None,
    ) -> None:
        with self._lock:
            active = self._active
            if active is None or active["id"] != operation_id:
                return
            stamped = {**event, "at": _now()}
            active["events"].append(stamped)
            del active["events"][: -self.EVENT_LOG_SIZE]
            active["message"] = event.get("message") or active["message"]
            if on_event is not None:
                on_event(active, stamped)
            self._revision += 1

    def _finish(
        self,
        operation_id: str,
        status: str,
        *,
        result: Any = None,
        error: Exception | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            active = self._active
            if active is None or active["id"] != operation_id:
                return
            active["status"] = status
            active["result"] = _jsonable(result)
            if error is not None:
                active["error"] = str(error)
                active["message"] = f"{active['label']} failed: {error}"
                logger.error(
                    f"Robot operation failed: {active['kind']}: "
                    + "".join(traceback.format_exception_only(type(error), error)).strip()
                )
            else:
                active["message"] = message or f"{active['label']} {status}"
            active["finished_at"] = _now()
            self._history.appendleft(active)
            self._active = None
            self._revision += 1


def _jsonable(value: Any) -> Any:
    """Keep operation results serializable for the API and WebSocket."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)
