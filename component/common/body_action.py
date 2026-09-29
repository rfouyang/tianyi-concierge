from __future__ import annotations

import secrets
import threading
import time

from .errors import ConciergeTaskCancelled
from .tianyi_arm_runtime import TianyiArmRuntime


class BodyActionClient:
    """Execute bundled recorder actions through the direct Tianyi arm runtime."""

    ARM_TTL_SECONDS = 2 * 60 * 60

    def __init__(self, runtime: TianyiArmRuntime | None = None) -> None:
        self.runtime = runtime or TianyiArmRuntime()
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[frozenset[str], float]] = {}
        self._active_cancel_event: threading.Event | None = None

    def list_actions(self, *, ready_only: bool = True) -> list[dict[str, object]]:
        actions = self.runtime.list_actions()
        if not ready_only:
            return actions
        return [action for action in actions if action.get("ready") is True]

    def health(self) -> dict[str, object]:
        """Read arm health without keeping the 500 Hz status subscription open."""
        try:
            result = self.runtime.preflight().to_dict()
        finally:
            self._release_idle_subscription()
        result["actions"] = self.list_actions()
        return result

    def arm(self, action_ids: list[str], *, confirmed: bool) -> str:
        if confirmed is not True:
            raise PermissionError("Physical Tianyi arm-motion confirmation is required")
        requested = frozenset(str(action_id).strip() for action_id in action_ids)
        available = {str(action["action_id"]) for action in self.list_actions()}
        unknown = sorted(requested - available)
        if unknown:
            raise ValueError("Unavailable Tianyi arm actions: " + ", ".join(unknown))
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._expire_sessions()
            self._sessions[token] = (
                requested,
                time.monotonic() + self.ARM_TTL_SECONDS,
            )
        return token

    def prepare(self, arm_token: str) -> dict[str, object]:
        self._require_session(arm_token)
        cancel_event = threading.Event()
        self._begin_operation(cancel_event)
        try:
            self.runtime.require_preflight()
            self.runtime.motion_service.move_to_concierge_init(cancel_event)
            return {
                "status": "completed",
                "message": "Tianyi arms reached concierge_init",
            }
        finally:
            self._finish_operation(cancel_event)

    def execute(
        self,
        action_id: str,
        arm_token: str,
        cancel_event: threading.Event,
        *,
        timeout: float = 120.0,
        poll_interval: float = 0.2,
    ) -> dict[str, object]:
        del timeout, poll_interval
        allowed = self._require_session(arm_token)
        normalized = str(action_id).strip()
        if normalized not in allowed:
            raise PermissionError(
                f"Tianyi arm action is not authorized for this run: {normalized}"
            )
        self._begin_operation(cancel_event)
        try:
            self.runtime.require_preflight()
            self.runtime.motion_service.execute(normalized, cancel_event)
            return {"status": "completed", "action_id": normalized}
        except ConciergeTaskCancelled:
            raise
        finally:
            self._finish_operation(cancel_event)

    def cancel_current(self) -> bool:
        with self._lock:
            cancel_event = self._active_cancel_event
        if cancel_event is None:
            return False
        cancel_event.set()
        return True

    def close(self) -> None:
        self.cancel_current()
        self.runtime.close()

    def _begin_operation(self, cancel_event: threading.Event) -> None:
        with self._lock:
            if self._active_cancel_event is not None:
                raise RuntimeError("Another Tianyi arm operation is already running")
            self._active_cancel_event = cancel_event

    def _finish_operation(self, cancel_event: threading.Event) -> None:
        with self._lock:
            if self._active_cancel_event is cancel_event:
                self._active_cancel_event = None
        self._release_idle_subscription()

    def _release_idle_subscription(self) -> None:
        """Stop /arm/status (500 Hz) while no arm operation needs it.

        The next preflight re-subscribes and waits for fresh status before any
        motion, so releasing it only saves CPU while the arms are idle.
        """
        with self._lock:
            if self._active_cancel_event is not None:
                return
            subscriber = getattr(self.runtime, "status_subscriber", None)
            if subscriber is not None:
                subscriber.close()

    def _require_session(self, token: str) -> frozenset[str]:
        with self._lock:
            self._expire_sessions()
            session = self._sessions.get(str(token))
        if session is None:
            raise PermissionError("Tianyi arm authorization is missing or expired")
        return session[0]

    def _expire_sessions(self) -> None:
        now = time.monotonic()
        self._sessions = {
            token: session
            for token, session in self._sessions.items()
            if session[1] > now
        }
