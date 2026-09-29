from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from util.slam_helper import SLAM

from ..common.map_view import MapViewService
from ..map_localization.map_identity import MapIdentityRegistry


class RobotStatusMonitor:
    """Poll robot state in one background thread and publish revisioned snapshots.

    Every browser reads the same cached snapshot instead of polling the robot
    itself. Fast fields refresh every second; slower ones (health, arms, POIs,
    the explore map) refresh less often, and the map refreshes every two
    seconds while mapping so a build preview stays live.
    """

    def __init__(
        self,
        slam: SLAM,
        map_view: MapViewService,
        body_actions: Any = None,
        registry: MapIdentityRegistry | None = None,
        localizer: Any = None,
        operations: Any = None,
        *,
        fast_interval: float = 1.0,
        slow_interval: float = 5.0,
        map_interval: float = 10.0,
        mapping_map_interval: float = 2.0,
        arms_interval: float = 30.0,
    ) -> None:
        self.slam = slam
        self.map_view = map_view
        self.body_actions = body_actions
        self.registry = registry
        self.localizer = localizer
        self.operations = operations
        self.fast_interval = fast_interval
        self.slow_interval = slow_interval
        self.map_interval = map_interval
        self.mapping_map_interval = mapping_map_interval
        self.arms_interval = arms_interval
        self._next_arms = 0.0
        self._lock = threading.Lock()
        self._state: dict = {"connected": False, "error": "Waiting for the first update"}
        self._revision = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_slow = 0.0
        self._next_map = 0.0
        self._map_requested = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="robot-status", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def snapshot(self) -> dict:
        with self._lock:
            return {"revision": self._revision, **copy.deepcopy(self._state)}

    def request_refresh(self, *, include_map: bool = False) -> None:
        """Ask for an immediate refresh after an operation changed the robot."""
        self._next_slow = 0.0
        self._next_arms = 0.0
        if include_map:
            self._next_map = 0.0
        self._map_requested.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._poll(started)
            except Exception as error:
                self._publish({"connected": False, "error": str(error)}, merge=True)
                logger.warning(f"Robot status poll failed: {error}")
            self._map_requested.clear()
            remaining = self.fast_interval - (time.monotonic() - started)
            if remaining > 0:
                self._map_requested.wait(remaining)

    def _poll(self, now: float) -> None:
        map_status = self.slam.map_client.get_map_status()
        mapping = bool(map_status.get("is_in_mapping_mode"))
        state: dict[str, Any] = {
            "connected": True,
            "error": None,
            "pose": self.slam.localization.get_robot_pose(),
            "quality": self.slam.localization.get_localization_quality(),
            "localization_enabled": self.slam.localization.is_enabled(),
            "power": self.slam.power.get_status(),
            "map_status": map_status,
            "mapping": mapping,
            "map_name": self._map_name(map_status.get("current_map_id")),
            "current_action": self._current_action(),
        }
        state["localization_state"] = self._localization_state(state)

        if now >= self._next_slow:
            state.update(self._slow_fields())
            self._next_slow = now + self.slow_interval
        if self.body_actions is not None and now >= self._next_arms:
            state["arms"] = self._arm_health()
            self._next_arms = now + self.arms_interval

        interval = self.mapping_map_interval if mapping else self.map_interval
        if now >= self._next_map:
            try:
                state["map"] = self.map_view.refresh()
            except Exception as error:
                logger.warning(f"Explore map refresh failed: {error}")
            self._next_map = now + interval
        self._publish(state, merge=True)

    def _slow_fields(self) -> dict:
        fields: dict[str, Any] = {}
        try:
            health = self.slam.system_status.get_health()
            fields["health"] = {
                "healthy": self.slam.system_status.is_healthy(health=health),
                "messages": [
                    error.get("message", "Unknown error") for error in health.get("baseError", [])
                ],
            }
        except Exception as error:
            fields["health"] = {"healthy": False, "messages": [str(error)]}
        try:
            fields["pois"] = self.slam.poi.get_all()
        except Exception as error:
            logger.warning(f"POI refresh failed: {error}")
        try:
            fields["home_pose"] = self.slam.home_dock.get_home_pose()
        except Exception as error:
            logger.warning(f"Home pose refresh failed: {error}")
        return fields

    def _arm_health(self) -> dict:
        """Brief check; the arm status subscription is released right after."""
        try:
            health = self.body_actions.health()
        except Exception as error:
            return {"ready": False, "motor_count": 0, "error": str(error)}
        return {
            "ready": bool(health.get("ready")),
            "motor_count": health.get("motor_count", 0),
            "error": health.get("error"),
        }

    LOCALIZING_KINDS = frozenset({"localization_dock", "localization_pose"})

    def _localization_state(self, state: dict) -> dict | None:
        if self.localizer is None:
            return None
        active = (self.operations.snapshot()["active"] or {}) if self.operations else {}
        return self.localizer.localization_state(
            enabled=state["localization_enabled"],
            quality=state["quality"],
            map_status=state["map_status"],
            mapping=state["mapping"],
            localizing=active.get("kind") in self.LOCALIZING_KINDS,
        )

    def _current_action(self) -> dict | None:
        action = self.slam.motion.get_current_action()
        if not action:
            return None
        state = action.get("state", {})
        if state.get("status") == 4:
            return None
        return {"action_id": action.get("action_id"), "action_name": action.get("action_name")}

    def _map_name(self, map_id: str | None) -> str | None:
        if self.registry is None or not map_id:
            return None
        try:
            entry = self.registry.get(map_id)
        except (OSError, ValueError):
            return None
        return entry.get("name") if entry else None

    def _publish(self, state: dict, *, merge: bool) -> None:
        with self._lock:
            next_state = {**self._state, **state} if merge else state
            comparable_old = {k: v for k, v in self._state.items() if k != "updated_at"}
            comparable_new = {k: v for k, v in next_state.items() if k != "updated_at"}
            if comparable_old == comparable_new:
                return
            next_state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._state = next_state
            self._revision += 1
