import sys
from pathlib import Path

import requests
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]

if __package__:
    from .base import Base
else:
    sys.path.insert(0, str(BASE_DIR))
    from util.slam_helper.base import Base


class Power:
    @classmethod
    def get_status(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/system/v1/power/status"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()
        status = response.json()

        logger.debug(
            f"Power: battery={status.get('batteryPercentage')}%, "
            f"charging={status.get('isCharging')}, "
            f"dc_connected={status.get('isDCConnected')}"
        )

        return status

    @classmethod
    def get_battery_percentage(cls):
        return cls.get_status().get("batteryPercentage")

    @classmethod
    def is_charging(cls):
        return bool(cls.get_status().get("isCharging"))

    @classmethod
    def is_dc_connected(cls):
        return bool(cls.get_status().get("isDCConnected"))

    @classmethod
    def require_charging(cls, **kwargs):
        status = kwargs.get("status") or cls.get_status()
        if not status.get("isCharging"):
            raise RuntimeError("Robot is not charging")

        return status


def demo():
    """Read the robot's current power state."""
    return Power.get_status()


def main():
    print(demo())


if __name__ == "__main__":
    main()
