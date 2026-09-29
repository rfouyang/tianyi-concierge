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


class SystemStatus:
    @classmethod
    def get_health(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/system/v1/robot/health"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return response.json()

    @classmethod
    def is_healthy(cls, **kwargs):
        health = kwargs.get("health") or cls.get_health()

        return not any(
            health.get(key, False)
            for key in (
                "hasError",
                "hasFatal",
                "hasSystemEmergencyStop",
                "hasLidarDisconnected",
                "hasSdpDisconnected",
            )
        )

    @classmethod
    def require_healthy(cls):
        health = cls.get_health()
        if not cls.is_healthy(health=health):
            errors = [
                error.get("message", "Unknown error")
                for error in health.get("baseError", [])
            ]
            message = ", ".join(errors) or "Robot health check failed"
            raise RuntimeError(message)

        return health

    @classmethod
    def clear_error(cls, error_code, **kwargs):
        url = f"{Base.BASE_URL}/api/core/system/v1/robot/health/{error_code}"

        response = requests.delete(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()
        logger.info(f"Cleared robot error: {error_code}")

        return response

    @classmethod
    def get_info(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/system/v1/robot/info"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return response.json()

    @classmethod
    def get_capabilities(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/system/v1/capabilities"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return response.json()

    @classmethod
    def has_capability(cls, name):
        return any(
            capability.get("name") == name and capability.get("enabled", False)
            for capability in cls.get_capabilities()
        )


def demo_system_status():
    """Read the robot's health, identity, and enabled capabilities."""
    return {
        "health": SystemStatus.get_health(),
        "info": SystemStatus.get_info(),
        "capabilities": SystemStatus.get_capabilities(),
    }


def main():
    print(demo_system_status())


if __name__ == "__main__":
    main()

