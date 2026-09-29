from __future__ import annotations

from typing import Any

from .home_dock import HomeDock
from .localization import LocalizationClient
from .map_client import MapClient
from .map_renderer import MapRenderer
from .mapping import Mapping
from .motion import Motion
from .poi import POI
from .power import Power
from .system_status import SystemStatus


class SLAM:
    """Single entry point for the SLAM capabilities used by the application."""

    def __init__(self, **kwargs: Any) -> None:
        self.motion = Motion(**kwargs)
        self.mapping = Mapping
        self.localization = LocalizationClient()
        self.map_client = MapClient
        self.power = Power
        self.home_dock = HomeDock
        self.system_status = SystemStatus
        self.poi = POI
        self.renderer = MapRenderer

    def require_action_success(self, action, label="SLAM action"):
        return self.motion.actions.require_success(action, label)
