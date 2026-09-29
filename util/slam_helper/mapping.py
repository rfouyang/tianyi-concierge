import sys
import time
from pathlib import Path

import requests
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]

if __package__:
    from .base import Base
else:
    sys.path.insert(0, str(BASE_DIR))
    from util.slam_helper.base import Base


class Mapping:
    @classmethod
    def is_enabled(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/mapping/:enable"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return bool(response.json())

    @classmethod
    def set_enabled(cls, enabled, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/mapping/:enable"

        response = requests.put(
            url,
            json={"enable": enabled},
            timeout=kwargs.get("timeout", 5),
        )
        response.raise_for_status()
        logger.info(f"Mapping enabled: {enabled}")

        return response.json()

    @classmethod
    def start(cls, **kwargs):
        return cls.set_enabled(True, **kwargs)

    @classmethod
    def stop(cls, **kwargs):
        return cls.set_enabled(False, **kwargs)

    @classmethod
    def wait_enabled(cls, enabled, **kwargs):
        timeout = kwargs.get("timeout", 10)
        poll_interval = kwargs.get("poll_interval", 0.25)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if cls.is_enabled() is enabled:
                return enabled
            time.sleep(poll_interval)

        raise TimeoutError(f"Mapping mode did not become {enabled} within {timeout} seconds")

    @classmethod
    def clear_map(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/maps"

        response = requests.delete(url, timeout=kwargs.get("timeout", 10))
        response.raise_for_status()
        logger.info("Cleared in-memory SLAM map")

        return response

    @classmethod
    def is_loop_closure_enabled(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/loopclosure/:enable"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return bool(response.json())

    @classmethod
    def set_loop_closure(cls, enabled, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/loopclosure/:enable"

        response = requests.put(
            url,
            json={"enable": enabled},
            timeout=kwargs.get("timeout", 5),
        )
        response.raise_for_status()
        logger.info(f"Loop closure enabled: {enabled}")

        return response.json()


def demo():
    """Read the current mapping and loop-closure states."""
    return {
        "mapping": Mapping.is_enabled(),
        "loop_closure": Mapping.is_loop_closure_enabled(),
    }


def main():
    print(demo())


if __name__ == "__main__":
    main()
