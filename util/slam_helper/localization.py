import requests
from loguru import logger

try:
    from .base import Base
except ImportError:
    from util.slam_helper.base import Base


class LocalizationClient:
    def get_robot_pose(self):
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/pose"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        pose = response.json()

        logger.debug(f"(x, y, z): {pose['x']} {pose['y']} {pose['z']}")
        logger.debug(f"(yaw, pitch roll): {pose['yaw']} {pose['pitch']} {pose['roll']})")

        return pose

    def get_localization_quality(self):
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/quality"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        quality = int(response.text)

        logger.debug(f"Localization quality: {quality}")

        return quality

    def is_enabled(self):
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/:enable"

        response = requests.get(url, timeout=5)
        response.raise_for_status()

        return bool(response.json())

    def set_enabled(self, enabled):
        """Start or pause localization; SLAMTEC returns true on success."""
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/:enable"

        response = requests.put(url, json={"enable": bool(enabled)}, timeout=5)
        response.raise_for_status()
        if response.json() is not True:
            raise RuntimeError(f"Robot refused to set localization enabled={enabled}")
        logger.info(f"Localization enabled: {enabled}")

        return True

    def set_robot_pose(self, pose):
        """Force the robot pose in the loaded map (x, y in metres, yaw in radians)."""
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/pose"
        payload = {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "z": float(pose.get("z", 0.0)),
            "yaw": float(pose.get("yaw", 0.0)),
            "pitch": 0.0,
            "roll": 0.0,
        }

        response = requests.put(url, json=payload, timeout=5)
        response.raise_for_status()
        logger.info(
            f"Set robot pose: x={payload['x']}, y={payload['y']}, yaw={payload['yaw']}"
        )

        return payload

    def get_home_pose(self):
        """Get the pose of the currently registered charging dock."""
        url = f"{Base.BASE_URL}/api/core/slam/v1/homepose"

        response = requests.get(url, timeout=5)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def demo_localization():
    localization = LocalizationClient()
    return {
        "pose": localization.get_robot_pose(),
        "quality": localization.get_localization_quality(),
    }


def main():
    print(demo_localization())


if __name__ == "__main__":
    main()

