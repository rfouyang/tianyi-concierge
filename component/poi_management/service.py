from __future__ import annotations

from util.slam_helper import SLAM


class PoiManager:
    """Manage the POI catalog of the map loaded on the robot."""

    def __init__(self, slam: SLAM, localization_guard=None) -> None:
        self.slam = slam
        self.localization_guard = localization_guard

    def list(self):
        return self.slam.poi.get_all()

    def get_catalog(self):
        """Return sorted POIs plus the context the POI page shows beside them."""
        pois = sorted(
            self.list(),
            key=lambda item: str(item.get("metadata", {}).get("display_name") or "").casefold(),
        )
        return {
            "pois": pois,
            "map_status": self.slam.map_client.get_map_status(),
            "quality": self.slam.localization.get_localization_quality(),
            "robot_pose": self.slam.localization.get_robot_pose(),
            "start_pose": self.slam.home_dock.get_home_pose(),
        }

    def create(self, name):
        """Record the current pose; only meaningful once Tianyi is localized."""
        if self.localization_guard is not None:
            self.localization_guard()
        return self.slam.poi.create(name)

    def delete(self, poi_id):
        return self.slam.poi.delete(poi_id)
