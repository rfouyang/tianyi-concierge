from __future__ import annotations

import hashlib
import threading

from util.slam_helper import SLAM


class MapViewService:
    """Cache the robot's explore map as a marker-free PNG plus grid metadata.

    Markers (robot, dock, POIs, routes) are drawn by the browser from the
    metadata, so pose updates never require re-rendering the whole map.
    """

    def __init__(self, slam: SLAM) -> None:
        self.slam = slam
        self._lock = threading.Lock()
        self._revision: str | None = None
        self._metadata: dict | None = None
        self._png: bytes | None = None

    def refresh(self) -> dict:
        map_data = self.slam.map_client.explore_map(None)["map_data"]
        revision = hashlib.sha256(map_data).hexdigest()[:16]
        with self._lock:
            if revision == self._revision and self._metadata is not None:
                return self._view()
        metadata, png = self.slam.renderer.render_base_map(map_data)
        with self._lock:
            self._revision = revision
            self._metadata = metadata
            self._png = png
            return self._view()

    def view(self) -> dict | None:
        with self._lock:
            return self._view() if self._metadata is not None else None

    def png(self) -> tuple[str, bytes] | None:
        with self._lock:
            if self._png is None or self._revision is None:
                return None
            return self._revision, self._png

    def _view(self) -> dict:
        return {"revision": self._revision, **(self._metadata or {})}
