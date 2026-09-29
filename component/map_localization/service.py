from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from util.slam_helper import SLAM

from .map_identity import MapIdentityRegistry, StcmIdentity, inspect_stcm

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAP_DIR = BASE_DIR / "data" / "maps"
MIN_LOCALIZATION_QUALITY = 50


def _meta(confirmed: dict | None) -> dict:
    if not confirmed:
        return {}
    return {"method": confirmed.get("method"), "localized_at": confirmed.get("at")}


class ConciergeMapLocalizer:
    """Load maps from data/maps onto the robot and localize in the loaded map.

    Loading follows the SLAMTEC procedure: upload persists the file to robot
    storage, reload loads it from that storage, and the composite map read back
    afterwards must match the selected file. A map cannot be loaded while
    localization is running; stop localization first.
    """

    def __init__(
        self,
        slam: SLAM,
        map_dir: Path = DEFAULT_MAP_DIR,
        registry_path: Path | None = None,
    ) -> None:
        self.slam = slam
        self.map_dir = Path(map_dir)
        self.registry = MapIdentityRegistry(
            Path(registry_path) if registry_path else self.map_dir / "map_registry.json"
        )
        self._state_lock = threading.Lock()
        self._localized: dict | None = None

    # ---------------------------------------------------- localization state
    def mark_localized(self, method: str, quality: int) -> None:
        """Record a successful localization on the currently loaded map."""
        map_status = self.slam.map_client.get_map_status()
        with self._state_lock:
            self._localized = {
                "method": method,
                "map_id": map_status.get("current_map_id"),
                "quality": quality,
                "at": datetime.now(timezone.utc).isoformat(),
            }

    def invalidate_localization(self, reason: str) -> None:
        with self._state_lock:
            if self._localized is not None:
                logger.info(f"Localization is no longer confirmed: {reason}")
            self._localized = None

    def localization_state(
        self,
        *,
        enabled: bool | None,
        quality: int | None,
        map_status: dict,
        mapping: bool,
        localizing: bool = False,
    ) -> dict:
        """not_localized | localizing | localized | lost, with the reason."""
        with self._state_lock:
            confirmed = dict(self._localized) if self._localized else None
        if localizing:
            return {"state": "localizing", "reason": "Localization is running", **_meta(confirmed)}
        if map_status.get("map_load_status") != "LOADED":
            return {"state": "not_localized", "reason": "No map is loaded"}
        if mapping:
            return {"state": "not_localized", "reason": "Map building is active"}
        if enabled is False:
            return {"state": "not_localized", "reason": "Localization is stopped"}
        if confirmed is None:
            return {
                "state": "not_localized",
                "reason": "Localize Tianyi on Map & localization first",
            }
        if confirmed.get("map_id") != map_status.get("current_map_id"):
            return {"state": "not_localized", "reason": "A different map is loaded now"}
        if not isinstance(quality, (int, float)) or quality < MIN_LOCALIZATION_QUALITY:
            return {
                "state": "lost",
                "reason": f"Localization quality dropped to {quality}; localize again",
                **_meta(confirmed),
            }
        return {"state": "localized", "reason": None, **_meta(confirmed)}

    def require_localized(self) -> None:
        """Raise unless Tianyi has been localized on the loaded map."""
        state = self.localization_state(
            enabled=self.slam.localization.is_enabled(),
            quality=self.slam.localization.get_localization_quality(),
            map_status=self.slam.map_client.get_map_status(),
            mapping=self.slam.mapping.is_enabled(),
        )
        if state["state"] != "localized":
            raise RuntimeError(f"Tianyi is not localized: {state['reason']}")

    # ------------------------------------------------------------------ maps
    def list_maps(self) -> list[dict]:
        maps = []
        for path in sorted(self.map_dir.glob("*.stcm"), key=lambda item: item.name):
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                maps.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "size": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                    }
                )
        return maps

    def resolve_map(self, selection: str | Path) -> Path:
        """Resolve a selection to a direct child of data/maps."""
        selected = Path(str(selection))
        if selected.is_absolute() or selected.parent != Path("."):
            raise ValueError("Select a map by name from data/maps")
        if selected.suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")
        candidates = {Path(item["path"]).resolve() for item in self.list_maps()}
        resolved = (self.map_dir / selected.name).resolve()
        if resolved not in candidates:
            raise FileNotFoundError(f"Map does not exist: data/maps/{selected.name}")
        return resolved

    @staticmethod
    def _inspect_path(path: Path) -> StcmIdentity:
        return inspect_stcm(path.read_bytes())

    def _map_identities(self) -> list[tuple[dict, StcmIdentity]]:
        candidates = []
        for item in self.list_maps():
            try:
                candidates.append((item, self._inspect_path(Path(item["path"]))))
            except (OSError, ValueError) as exc:
                logger.warning(f"Cannot inspect map data/maps/{item['name']}: {exc}")
        return candidates

    def get_current_map_identity(self) -> dict:
        """Identify the loaded robot map against data/maps without changing it."""
        map_status = self.slam.map_client.get_map_status()
        load_status = map_status.get("map_load_status", "UNKNOWN")
        try:
            floor = self.slam.map_client.get_robot_current_floor()
        except Exception as exc:
            logger.warning(f"Cannot read current map floor: {exc}")
            floor = {}

        map_id = floor.get("map_id") or map_status.get("current_map_id")
        result = {
            "display_name": "Unknown",
            "source": None,
            "match": "unknown",
            "verified": False,
            "map_id": map_id,
            "load_status": load_status,
            "building": floor.get("building"),
            "floor": floor.get("floor"),
            "mapping": self.slam.mapping.is_enabled(),
            "managed_by_cloud": bool(map_status.get("is_managed_by_cloud")),
            "home_dock_bound": bool(map_status.get("is_homedock_binded")),
            "map_status": map_status,
            "matched_candidates": [],
        }
        if load_status != "LOADED":
            return result

        try:
            current = inspect_stcm(self.slam.map_client.get_composite_map())
        except Exception as exc:
            result["identity_error"] = str(exc)
            registered = self.registry.get(map_id)
            if registered:
                result.update(
                    display_name=registered.get("name", "Unknown"),
                    source=registered.get("source"),
                    match="registry",
                )
            return result

        result.update(
            sha256=current.sha256,
            canonical_sha256=current.canonical_sha256,
            dimensions={"width": current.width, "height": current.height},
            origin={"x": current.origin_x, "y": current.origin_y},
            resolution={"x": current.resolution_x, "y": current.resolution_y},
        )
        candidates = self._map_identities()
        exact = [item for item, identity in candidates if identity.sha256 == current.sha256]
        matches = exact or [
            item
            for item, identity in candidates
            if identity.canonical_sha256 == current.canonical_sha256
        ]
        result["matched_candidates"] = [f"data/maps/{item['name']}" for item in matches]
        if len(matches) == 1:
            item = matches[0]
            result.update(
                display_name=item["name"],
                source=f"data/maps/{item['name']}",
                match="exact" if exact else "normalized",
                verified=True,
            )
            try:
                self.register_verified_identity(result)
            except (OSError, ValueError) as exc:
                logger.warning(f"Cannot update the map identity registry: {exc}")
        elif len(matches) > 1:
            result.update(display_name="Ambiguous map match", match="ambiguous")
        else:
            registered = self.registry.get(map_id)
            if registered:
                result.update(
                    display_name=registered.get("name", "Unknown"),
                    source=registered.get("source"),
                    match="registry",
                )
        return result

    def register_verified_identity(self, identity: dict) -> None:
        if not identity.get("verified") or not identity.get("map_id"):
            return
        self.registry.set(
            identity["map_id"],
            {
                "name": identity["display_name"],
                "source": identity["source"],
                "canonical_sha256": identity["canonical_sha256"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _require_idle(self) -> dict:
        if self.slam.mapping.is_enabled():
            raise RuntimeError("Stop map building before changing the active map")
        map_status = self.slam.map_client.get_map_status()
        if map_status.get("is_managed_by_cloud"):
            raise RuntimeError(
                "Local map changes are blocked while the robot map is managed by cloud"
            )
        health = self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if current_action is not None and current_action.get("state", {}).get("status") != 4:
            raise RuntimeError(f"Robot has an active action: {current_action.get('action_id')}")
        return {"map_status": map_status, "health": health}

    def load_preflight(self) -> dict:
        """Loading is allowed only on the dock, charging, idle, and not localized."""
        state = self._require_idle()
        if self.slam.localization.is_enabled():
            raise RuntimeError("Localization is running. Stop localization before loading a map")
        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        return {**state, "power": power}

    def load_map(self, selection: str | Path, **kwargs: Any) -> dict:
        """Upload a data/maps file to robot storage, reload it, and verify it."""
        map_path = self.resolve_map(selection)
        expected = self._inspect_path(map_path)
        self.load_preflight()
        self.invalidate_localization(f"loading data/maps/{map_path.name}")
        self.slam.map_client.upload_map(map_path)
        try:
            self.slam.map_client.reload_map(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"data/maps/{map_path.name} was uploaded to robot storage, but the "
                "robot did not reload it successfully"
            ) from exc

        try:
            identity = self.get_current_map_identity()
        except Exception as exc:
            raise RuntimeError(
                f"data/maps/{map_path.name} was reloaded, but its active identity "
                "could not be verified"
            ) from exc
        if identity.get("canonical_sha256") != expected.canonical_sha256:
            raise RuntimeError(
                f"Robot reloaded a map, but its identity does not match data/maps/{map_path.name}"
            )
        self.register_verified_identity(identity)
        logger.info(f"Loaded and verified data/maps/{map_path.name} on the robot")
        return identity

    @staticmethod
    def _floor_count(document: Any) -> int:
        if isinstance(document, list):
            return len(document)
        if isinstance(document, dict):
            for key in ("floors", "data", "maps"):
                value = document.get(key)
                if isinstance(value, list):
                    return len(value)
                if isinstance(value, dict):
                    try:
                        return ConciergeMapLocalizer._floor_count(value)
                    except ValueError:
                        pass
        raise ValueError("Robot returned an unrecognized floor-list response")

    def require_single_floor(self) -> None:
        floor_count = self._floor_count(self.slam.map_client.get_floors())
        if floor_count != 1:
            raise RuntimeError(
                f"Saving the robot map is allowed only with exactly one floor; found {floor_count}"
            )

    def sync_current_map(self, **kwargs: Any) -> dict:
        """Persist and reload the robot's in-memory map (single floor only)."""
        self._require_idle()
        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        self.require_single_floor()
        self.invalidate_localization("the map was synced and reloaded")
        self.slam.map_client.sync_map(**kwargs)
        identity = self.get_current_map_identity()
        self.register_verified_identity(identity)
        return identity

    def save_snapshot(self, filename: str, *, overwrite: bool = False) -> Path:
        name = Path(filename).name
        if Path(name).suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")
        return self.slam.map_client.save_map(
            filename=name,
            output_dir=self.map_dir,
            overwrite=overwrite,
        )

    # ---------------------------------------------------------- localization
    def get_localization_status(self) -> dict:
        home_dock = None
        try:
            result = self.slam.home_dock.get_current_home_dock()
            if result.get("result"):
                home_dock = result.get("data")
        except Exception as exc:
            logger.warning(f"Cannot read the bound home dock: {exc}")
        return {
            "enabled": self.slam.localization.is_enabled(),
            "quality": self.slam.localization.get_localization_quality(),
            "pose": self.slam.localization.get_robot_pose(),
            "home_dock": home_dock,
            "min_quality": MIN_LOCALIZATION_QUALITY,
        }

    def stop_localization(self) -> dict:
        self._require_no_motion()
        self.slam.localization.set_enabled(False)
        self.invalidate_localization("localization was stopped")
        return self.get_localization_status()

    def _require_no_motion(self) -> None:
        current_action = self.slam.motion.get_current_action()
        if current_action is not None and current_action.get("state", {}).get("status") != 4:
            raise RuntimeError(f"Robot has an active action: {current_action.get('action_id')}")

    def _require_localizable(self) -> dict:
        if self.slam.mapping.is_enabled():
            raise RuntimeError("Localization is unavailable while map building is active")
        map_status = self.slam.map_client.get_map_status()
        if map_status.get("map_load_status") != "LOADED":
            raise RuntimeError("Load a map before localizing")
        self._require_no_motion()
        if not self.slam.localization.is_enabled():
            self.slam.localization.set_enabled(True)
        return map_status

    def _wait_for_quality(self, timeout: float, poll_interval: float) -> int:
        deadline = time.monotonic() + timeout
        quality = self.slam.localization.get_localization_quality()
        while quality < MIN_LOCALIZATION_QUALITY and time.monotonic() < deadline:
            time.sleep(poll_interval)
            quality = self.slam.localization.get_localization_quality()
        if quality < MIN_LOCALIZATION_QUALITY:
            raise RuntimeError(
                f"Localization quality is {quality}; it needs at least {MIN_LOCALIZATION_QUALITY}"
            )
        return quality

    def bind_home_dock(self) -> dict:
        """Re-bind the map's charging dock while Tianyi sits on it (single floor)."""
        self._require_idle()
        if self.slam.mapping.is_enabled():
            raise RuntimeError("Stop map building before binding the charging dock")
        self.slam.home_dock.require_on_dock()
        self.require_single_floor()
        current = self.slam.home_dock.get_current_home_dock()
        dock = current.get("data") or {}
        if not dock.get("id"):
            raise RuntimeError(
                "The loaded map has no charging dock to bind. Build the map from the dock"
            )
        if dock.get("is_binded"):
            return dock
        self.slam.home_dock.bind_home_dock(dock["id"])
        bound = self.slam.home_dock.get_current_home_dock().get("data") or {}
        if not bound.get("is_binded"):
            raise RuntimeError(f"The robot did not confirm binding dock {dock['id']}")
        logger.info(f"Bound charging dock {dock['id']} ({dock.get('dock_name')})")
        return bound

    def localize_at_dock(self, **kwargs: Any) -> dict:
        """Reset the pose to the bound charging dock while Tianyi is on it."""
        self._require_localizable()
        self.slam.home_dock.require_on_dock()
        dock = self.slam.home_dock.require_bound_home_dock()
        self.invalidate_localization("localizing again at the dock")
        dock_id = dock.get("id")
        if not dock_id:
            raise RuntimeError("The bound home dock has no ID")
        self.slam.home_dock.relocalize_at_home_dock(dock_id)
        quality = self._wait_for_quality(
            kwargs.get("timeout", 10), kwargs.get("poll_interval", 0.5)
        )
        rebound = self._restore_dock_binding(dock_id)
        self.mark_localized("dock", quality)
        logger.info(f"Localized at home dock {dock_id}; quality={quality}")
        return {**self.get_localization_status(), "dock_rebound": rebound}

    def _restore_dock_binding(self, dock_id: str) -> bool:
        """Re-bind the dock if the localization reset dropped the binding.

        On this firmware the dock reset has been observed to leave the dock
        unbound, which would block tours from returning home.
        """
        current = self.slam.home_dock.get_current_home_dock().get("data") or {}
        if current.get("is_binded"):
            return False
        logger.warning(f"Localization at dock {dock_id} dropped the dock binding; binding it again")
        self.slam.home_dock.bind_home_dock(dock_id)
        current = self.slam.home_dock.get_current_home_dock().get("data") or {}
        if not current.get("is_binded"):
            raise RuntimeError(
                f"Localized at the dock, but the robot did not keep dock {dock_id} bound"
            )
        return True

    def localize_at_pose(
        self,
        x: float,
        y: float,
        yaw: float,
        *,
        search_half_size: float = 1.0,
        allow_rotation: bool = False,
        **kwargs: Any,
    ) -> dict:
        """Use an operator-placed pose as the guess, then refine it locally."""
        for label, value in (("x", x), ("y", y), ("yaw", yaw)):
            if not math.isfinite(float(value)):
                raise ValueError(f"Pose {label} must be a finite number")
        if not 0.25 <= float(search_half_size) <= 5.0:
            raise ValueError("Search half-size must be between 0.25 and 5 metres")

        self._require_localizable()
        self.invalidate_localization("localizing again at a placed pose")
        self.slam.localization.set_robot_pose({"x": x, "y": y, "yaw": yaw})
        area = {
            "x": float(x) - search_half_size,
            "y": float(y) - search_half_size,
            "width": 2 * search_half_size,
            "height": 2 * search_half_size,
        }
        timeout = kwargs.get("timeout", 30)
        action = self.slam.motion.relocalization(
            area=area,
            max_recover_time=int(timeout * 1000),
            recover_movement_type="RotateOnly" if allow_rotation else "NoMove",
            wait=True,
            timeout=timeout + 5,
            poll_interval=kwargs.get("poll_interval", 0.5),
        )
        self.slam.require_action_success(action, "Relocalize at the placed pose")
        quality = self._wait_for_quality(
            kwargs.get("quality_timeout", 5), kwargs.get("poll_interval", 0.5)
        )
        self.mark_localized("pose", quality)
        logger.info(f"Localized at operator pose ({x}, {y}, {yaw}); quality={quality}")
        return self.get_localization_status()


def demo_localization_status():
    """Read localization and map identity without changing the robot."""
    localizer = ConciergeMapLocalizer(SLAM())
    return {
        "maps": localizer.list_maps(),
        "localization": localizer.get_localization_status(),
    }


def main():
    print(demo_localization_status())


if __name__ == "__main__":
    main()
