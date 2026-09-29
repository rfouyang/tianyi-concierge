import os
import time
from pathlib import Path

import requests
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]
MAP_DIR = BASE_DIR / "data" / "maps"

try:
    from .base import Base
except ImportError:
    from util.slam_helper.base import Base


class MapClient:
    @classmethod
    def get_map_status(cls):
        url = f"{Base.BASE_URL}/api/multi-floor/status"

        response = requests.get(url, timeout=5)
        response.raise_for_status()

        return response.json()

    @classmethod
    def wait_map_loaded(cls, **kwargs):
        timeout = kwargs.get("timeout", 30)
        poll_interval = kwargs.get("poll_interval", 0.5)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            status = cls.get_map_status()
            load_status = status.get("map_load_status")

            if load_status == "LOADED":
                logger.info("Map loaded")
                return status
            if load_status == "ERROR":
                raise RuntimeError("Robot failed to load the map")

            time.sleep(poll_interval)

        raise TimeoutError(f"Map did not load within {timeout} seconds")

    @classmethod
    def get_robot_current_floor(cls):
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/floors/:current"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        current_floor = response.json()

        logger.debug(f"Map ID: {current_floor.get('map_id')}")
        logger.debug(
            f"Current floor: {current_floor.get('building')} / "
            f"{current_floor.get('floor')}"
        )

        return current_floor

    @classmethod
    def get_floors(cls):
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/floors"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()

    @classmethod
    def upload_map(cls, map_path):
        path = Path(map_path).expanduser()
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/stcm"
        headers = {"Content-Type": "application/octet-stream"}

        with path.open("rb") as map_file:
            response = requests.post(url, data=map_file, headers=headers, timeout=30)

        response.raise_for_status()
        logger.info(f"Uploaded map: {path}")

        return response

    @classmethod
    def get_composite_map(cls, **kwargs):
        """Return the current in-memory composite map without changing it."""
        url = f"{Base.BASE_URL}/api/core/slam/v1/maps/stcm"
        timeout = kwargs.get("timeout", 30)
        poll_interval = kwargs.get("poll_interval", 0.5)

        deadline = time.monotonic() + timeout
        while True:
            response = requests.get(
                url,
                timeout=kwargs.get("request_timeout", 30),
            )
            if response.status_code != 403:
                response.raise_for_status()
                break
            if time.monotonic() >= deadline:
                response.raise_for_status()

            response.close()
            status = cls.get_map_status().get("map_load_status")
            if status == "ERROR":
                raise RuntimeError("Robot failed to load the map")

            logger.info(f"Map export unavailable while status is {status}; retrying")
            time.sleep(poll_interval)

        return response.content

    @classmethod
    def save_map(cls, **kwargs):
        """Download the current composite map into the selected output directory."""
        filename = Path(kwargs.get("filename", "map.stcm")).name
        output_dir = Path(kwargs.get("output_dir", MAP_DIR))
        output_path = output_dir / filename

        if output_path.suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")
        if output_path.exists() and not kwargs.get("overwrite", False):
            raise FileExistsError(f"Map already exists: {output_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary_path.write_bytes(cls.get_composite_map(**kwargs))
        os.replace(temporary_path, output_path)
        logger.info(f"Saved map: {output_path}")

        return output_path

    @classmethod
    def delete_map(cls):
        """Delete the map persisted on the robot without clearing memory."""
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/stcm"

        response = requests.delete(url, timeout=30)
        response.raise_for_status()
        logger.info("Deleted persisted map")

        return response

    @classmethod
    def persist_map(cls, **kwargs):
        """Persist the current in-memory map without reloading it.

        This endpoint is intended for a single-floor deployment. SLAMTEC warns
        that saving this way in a multi-floor deployment can discard the other
        floors.
        """
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/stcm/:save"

        response = requests.post(url, timeout=kwargs.get("timeout", 30))
        response.raise_for_status()
        logger.info("Persisted current map")

        return response

    @classmethod
    def reload_map(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/stcm/:reload"

        if kwargs.get("pose"):
            payload = {"pose": kwargs["pose"]}
        else:
            payload = None

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("Reloaded map")
        cls.wait_map_loaded(
            timeout=kwargs.get("timeout", 30),
            poll_interval=kwargs.get("poll_interval", 0.5),
        )

        return response

    @classmethod
    def sync_map(cls, **kwargs):
        """Save and reload the current map.

        Do not use this operation in a multi-floor environment because it can
        discard maps for other floors.
        """
        url = f"{Base.BASE_URL}/api/multi-floor/map/v1/stcm/:sync"

        response = requests.post(url, timeout=30)
        response.raise_for_status()
        logger.info("Synchronized map")
        cls.wait_map_loaded(**kwargs)

        return response

    @classmethod
    def explore_map(cls, robot_pose, **kwargs):
        url = f"{Base.BASE_URL}/api/core/slam/v1/maps/explore"
        params = {
            "min_x": kwargs.get('min_x', None),
            "min_y": kwargs.get('min_y', None),
            "max_x": kwargs.get('max_x', None),
            "max_y": kwargs.get('max_y', None)
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        map_data = response.content

        logger.debug(f"Fetched explore map: {len(map_data)} bytes")

        return {
            "map_data": map_data,
            "robot_pose": robot_pose,
        }

    @classmethod
    def get_virtual_walls(cls):
        url = f"{Base.BASE_URL}/api/core/artifact/v1/lines/walls"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()


def demo_map_client():
    """Read map state only; uploads and reloads are hardware-affecting."""
    return {
        "status": MapClient.get_map_status(),
        "floor": MapClient.get_robot_current_floor(),
    }


def main():
    print(demo_map_client())


if __name__ == "__main__":
    main()
