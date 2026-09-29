import sys
from pathlib import Path
from uuid import UUID, uuid4

import requests
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]

if __package__:
    from .base import Base
    from .localization import LocalizationClient
    from .map_client import MapClient
else:
    sys.path.insert(0, str(BASE_DIR))
    from util.slam_helper.base import Base
    from util.slam_helper.localization import LocalizationClient
    from util.slam_helper.map_client import MapClient


class POI:
    TYPES = (
        "ROOM",
        "REFILL",
        "RECEPTION",
        "TABLE",
        "PARKING",
        "RECYCLE",
        "DISINFECT",
    )

    @classmethod
    def get_all(cls, **kwargs):
        url = f"{Base.BASE_URL}/api/core/artifact/v1/pois"

        response = requests.get(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        return response.json()

    @classmethod
    def get_by_name(cls, name):
        expected = (name or "").strip().casefold()
        if not expected:
            raise ValueError("POI name cannot be empty")

        return next(
            (
                poi
                for poi in cls.get_all()
                if str(poi.get("metadata", {}).get("display_name") or "")
                .strip()
                .casefold()
                == expected
            ),
            None,
        )

    @classmethod
    def require_by_name(cls, name):
        poi = cls.get_by_name(name)
        if poi is None:
            raise LookupError(f"POI not found: {name}")

        return poi

    @classmethod
    def create(cls, name, **kwargs):
        name = (name or "").strip()
        if not name:
            raise ValueError("POI name cannot be empty")

        existing_names = {
            str(poi.get("metadata", {}).get("display_name") or "")
            .strip()
            .casefold()
            for poi in cls.get_all()
        }
        if name.casefold() in existing_names:
            raise ValueError(f"A POI named '{name}' already exists")

        poi_type = kwargs.get("poi_type", "ROOM").upper()
        if poi_type not in cls.TYPES:
            raise ValueError(f"Unsupported POI type: {poi_type}")

        localization = LocalizationClient()
        quality = localization.get_localization_quality()
        min_quality = kwargs.get("min_quality", 50)
        if quality < min_quality:
            raise RuntimeError(
                f"Localization quality is too low to record a POI: "
                f"{quality} < {min_quality}"
            )

        pose = kwargs.get("pose") or localization.get_robot_pose()
        payload = {
            "id": str(uuid4()),
            "pose": {
                "x": float(pose["x"]),
                "y": float(pose["y"]),
                "yaw": float(pose.get("yaw", 0)),
            },
            "metadata": {
                "display_name": name,
                "type": poi_type,
            },
        }
        url = f"{Base.BASE_URL}/api/core/artifact/v1/pois"
        response = requests.post(
            url,
            json=payload,
            timeout=kwargs.get("timeout", 5),
        )
        response.raise_for_status()
        logger.info(
            f"Recorded POI: name={name}, x={payload['pose']['x']}, "
            f"y={payload['pose']['y']}, yaw={payload['pose']['yaw']}"
        )

        if kwargs.get("persist", True):
            try:
                MapClient.persist_map(timeout=kwargs.get("persist_timeout", 30))
            except Exception as exc:
                raise RuntimeError(
                    f"POI '{name}' was recorded in memory, but the map could "
                    f"not be persisted: {exc}"
                ) from exc

        return payload

    @classmethod
    def delete(cls, poi_id, **kwargs):
        try:
            poi_id = str(UUID(str(poi_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("A valid POI ID is required") from exc

        url = f"{Base.BASE_URL}/api/core/artifact/v1/pois/{poi_id}"
        response = requests.delete(url, timeout=kwargs.get("timeout", 5))
        response.raise_for_status()

        try:
            deleted = response.json()
        except requests.exceptions.JSONDecodeError:
            deleted = True
        if deleted is False:
            raise RuntimeError(f"Robot did not delete POI: {poi_id}")

        logger.info(f"Deleted POI: id={poi_id}")

        if kwargs.get("persist", True):
            try:
                MapClient.persist_map(timeout=kwargs.get("persist_timeout", 30))
            except Exception as exc:
                raise RuntimeError(
                    f"POI '{poi_id}' was deleted from memory, but the map "
                    f"could not be persisted: {exc}"
                ) from exc

        return poi_id


def demo():
    """List the POIs in the currently loaded map without changing them."""
    return POI.get_all()


def main():
    print(demo())


if __name__ == "__main__":
    main()
