import sys
from pathlib import Path

import requests
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]

if __package__:
    from .base import Base
    from .motion import Motion
    from .power import Power
else:
    sys.path.insert(0, str(BASE_DIR))
    from util.slam_helper.base import Base
    from util.slam_helper.motion import Motion
    from util.slam_helper.power import Power


class HomeDock:
    @classmethod
    def is_on_dock(cls):
        return Power.get_status().get("dockingStatus") == "on_dock"

    @classmethod
    def require_on_dock(cls):
        status = Power.get_status()
        if status.get("dockingStatus") != "on_dock":
            raise RuntimeError("Robot is not on the charging dock")

        return status

    @classmethod
    def get_home_pose(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/homepose"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        if response.status_code == 404:
            return None
        response.raise_for_status()

        return response.json()

    @classmethod
    def set_home_pose(cls, pose, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/homepose"

        response = requests.put(
            url,
            json=pose,
            timeout=kwargs.get("timeout", 5),
        )
        response.raise_for_status()
        logger.info(
            f"Set home pose: x={pose.get('x')}, y={pose.get('y')}, "
            f"yaw={pose.get('yaw')}"
        )

        return response.json()

    @classmethod
    def get_home_docks(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/homedocks"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return response.json()

    @classmethod
    def register_home_dock(cls, display_name="home_dock", **kwargs):
        if kwargs.get("require_charging", True):
            status = cls.require_on_dock()
            Power.require_charging(status=status)

        url = f"{Base.BASE_URL}/api/core/slam/v1/homedocks/:register"
        payload = {"metadata": {"display_name": display_name}}

        response = requests.post(
            url,
            json=payload,
            timeout=kwargs.get("timeout", 5),
        )
        response.raise_for_status()
        home_dock = response.json()
        logger.info(
            f"Registered home dock: id={home_dock.get('id')}, "
            f"name={display_name}"
        )

        return home_dock

    @classmethod
    def find_home_dock(cls, dock_id):
        return next(
            (dock for dock in cls.get_home_docks() if dock.get("id") == dock_id),
            None,
        )

    @classmethod
    def get_current_home_dock(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/homedocks/:current"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return response.json()

    @classmethod
    def require_bound_home_dock(cls):
        result = cls.get_current_home_dock()
        home_dock = result.get("data") or {}
        if not result.get("result") or not home_dock.get("is_binded"):
            raise RuntimeError(
                "The current map does not have a bound home dock. Bind it on the "
                "Map & localization page while Tianyi is on the charging dock"
            )

        return home_dock

    @classmethod
    def bind_home_dock(cls, dock_id, **kwargs):
        """Bind a dock of the loaded map as the robot's home dock."""
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/homedocks/:current"

        response = requests.put(
            url,
            json={"dock_id": str(dock_id)},
            timeout=kwargs.get("timeout", 10),
        )
        response.raise_for_status()
        logger.info(f"Bound home dock: {dock_id}")

        return response

    @classmethod
    def relocalize_at_home_dock(cls, dock_id, **kwargs):
        """Reset localization to the front of a dock (firmware 6.2.0 or later)."""
        url = f"{Base.BASE_URL}/api/multi-floor/localization/v1/homedock"

        response = requests.put(
            url,
            json={"dock_id": str(dock_id)},
            timeout=kwargs.get("timeout", 10),
        )
        response.raise_for_status()
        logger.info(f"Reset localization at home dock: {dock_id}")

        return response

    @classmethod
    def go_home(cls, **kwargs):
        options = dict(kwargs)
        options.setdefault("wait", False)
        return Motion().dock(**options)


def demo():
    """Read the current registered home-dock state."""
    return {
        "on_dock": HomeDock.is_on_dock(),
        "home_pose": HomeDock.get_home_pose(),
        "home_docks": HomeDock.get_home_docks(),
    }


def main():
    print(demo())


if __name__ == "__main__":
    main()
