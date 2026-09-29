from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from util.slam_helper import SLAM

from ..map_localization.map_identity import inspect_stcm
from ..map_localization.service import ConciergeMapLocalizer

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAP_DIR = BASE_DIR / "data" / "maps"


class ConciergeMapBuilder:
    """Own the concierge workflow for building a new map from the charging dock.

    The build session lives here rather than in a browser, so a page reload or a
    second operator sees the same run. Finishing persists the new map on the
    robot (single floor only) and downloads the same map into data/maps.
    """

    def __init__(
        self,
        slam: SLAM,
        map_dir: Path = DEFAULT_MAP_DIR,
        localizer: ConciergeMapLocalizer | None = None,
    ) -> None:
        self.map_dir = Path(map_dir)
        self.slam = slam
        self.localizer = localizer or ConciergeMapLocalizer(slam, map_dir=self.map_dir)
        self._lock = threading.RLock()
        self._session: dict | None = None

    @property
    def session(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._session)

    def get_map_path(self, filename: str) -> Path:
        name = Path(filename).name
        if not name or Path(name).suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")
        return self.map_dir / name

    def preflight(self, filename: str, **kwargs: Any) -> dict:
        map_path = self.get_map_path(filename)
        if map_path.exists() and not kwargs.get("overwrite", False):
            raise FileExistsError(f"Map already exists: data/maps/{map_path.name}")
        if self.slam.mapping.is_enabled():
            raise RuntimeError(
                "Mapping is already active on the robot. Finish this build or stop "
                "the existing mapping run before starting a new one."
            )

        health = self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if current_action is not None and current_action.get("state", {}).get("status") != 4:
            raise RuntimeError(f"Robot has an active action: {current_action.get('action_id')}")

        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        return {"health": health, "power": power, "map_path": str(map_path)}

    def start(self, filename: str, **kwargs: Any) -> dict:
        dock_name = str(kwargs.get("dock_name", "office2_charger")).strip()
        if not dock_name:
            raise ValueError("Charging dock name cannot be empty")

        with self._lock:
            if self._session and self._session.get("active"):
                raise RuntimeError("A map-building session is already active")
            preflight = self.preflight(filename, **kwargs)
            mapping_started = False
            self.localizer.invalidate_localization("a new map is being built")
            self.slam.mapping.clear_map()
            try:
                self.slam.mapping.start()
                mapping_started = True
                self.slam.mapping.wait_enabled(True)
                if kwargs.get("enable_loop_closure", True):
                    self.slam.mapping.set_loop_closure(True)

                settle_time = kwargs.get("settle_time", 1.0)
                if settle_time > 0:
                    time.sleep(settle_time)

                start_pose = self.slam.localization.get_robot_pose()
                home_dock = self.slam.home_dock.register_home_dock(
                    dock_name,
                    require_charging=False,
                )
                home_pose = home_dock.get("pose")
                if home_pose:
                    self.slam.home_dock.set_home_pose(home_pose)

                self._session = {
                    "active": True,
                    "filename": Path(filename).name,
                    "map_path": preflight["map_path"],
                    "overwrite": bool(kwargs.get("overwrite", False)),
                    "start_pose": start_pose,
                    "home_dock": home_dock,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
            except Exception:
                if mapping_started:
                    try:
                        self.slam.mapping.stop()
                    except Exception:
                        logger.exception("Failed to stop mapping after start error")
                raise
            logger.info(
                f"Started map build: filename={self._session['filename']}, "
                f"dock_id={home_dock.get('id')}"
            )
            return copy.deepcopy(self._session)

    def stop_active_mapping(self, **kwargs: Any) -> None:
        """Pause a mapping run this process does not own, without clearing it."""
        with self._lock:
            if self._session and self._session.get("active"):
                raise RuntimeError("Use Finish and save for the active build session")
            if not self.slam.mapping.is_enabled():
                raise RuntimeError("Mapping is not active")
            self.slam.mapping.stop(timeout=kwargs.get("timeout", 10))
            self.slam.mapping.wait_enabled(
                False,
                timeout=kwargs.get("timeout", 10),
                poll_interval=kwargs.get("poll_interval", 0.25),
            )
        logger.info("Stopped active mapping run without clearing its map")

    def finish(self, **kwargs: Any) -> dict:
        """Stop mapping, persist the map on the robot, and save it to data/maps."""
        with self._lock:
            session = self._session
            if not session or not session.get("active"):
                raise RuntimeError("No active map-building session")

            self.slam.mapping.stop()
            self.slam.mapping.wait_enabled(False)
            final_pose = self.slam.localization.get_robot_pose()

            dock_id = session.get("home_dock", {}).get("id")
            home_dock = self.slam.home_dock.find_home_dock(dock_id) if dock_id else None
            if home_dock is None:
                raise RuntimeError("Registered home dock is missing from the completed map")

            self.localizer.require_single_floor()
            self.slam.map_client.persist_map(timeout=kwargs.get("persist_timeout", 30))
            map_path = self.slam.map_client.save_map(
                filename=session["filename"],
                output_dir=self.map_dir,
                overwrite=kwargs.get("overwrite", session.get("overwrite", False)),
            )
            saved = inspect_stcm(Path(map_path).read_bytes())
            robot = inspect_stcm(self.slam.map_client.get_composite_map())
            if saved.canonical_sha256 != robot.canonical_sha256:
                raise RuntimeError(f"data/maps/{Path(map_path).name} does not match the robot map")

            result = {
                **session,
                "active": False,
                "home_dock": home_dock,
                "final_pose": final_pose,
                "map_path": str(map_path),
                "canonical_sha256": saved.canonical_sha256,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
            self._session = result
        logger.info(f"Finished map build: {map_path}")
        return copy.deepcopy(result)

    def get_status(self) -> dict:
        session = self.session
        dock_id = (session or {}).get("home_dock", {}).get("id")
        return {
            "session": session,
            "mapping": self.slam.mapping.is_enabled(),
            "pose": self.slam.localization.get_robot_pose(),
            "power": self.slam.power.get_status(),
            "home_dock": (self.slam.home_dock.find_home_dock(dock_id) if dock_id else None),
        }


def demo_map_build_preflight():
    """Run only non-destructive map-building preflight checks."""
    return ConciergeMapBuilder(SLAM()).preflight("preflight_check.stcm", overwrite=True)


def main():
    print(demo_map_build_preflight())


if __name__ == "__main__":
    main()
