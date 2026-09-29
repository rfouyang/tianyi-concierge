from __future__ import annotations

import math
import time

from loguru import logger

from util.slam_helper import SLAM


class DockingService:
    """Concierge docking policy, including bounded undocking and recovery."""

    def __init__(self, slam: SLAM) -> None:
        self.slam = slam
        self.target_distance = 0.3
        self.max_distance = 0.6
        self.max_pulses = 30
        self.pulse_ms = 100
        self.action_timeout = 30
        self.poll_interval = 1

    def undock(self, **kwargs):
        target_distance = kwargs.get("distance", self.target_distance)
        max_distance = kwargs.get("max_distance", self.max_distance)
        max_pulses = kwargs.get("max_pulses", self.max_pulses)
        pulse_ms = kwargs.get("pulse_ms", self.pulse_ms)

        power = self.slam.power.get_status()
        if power.get("dockingStatus") != "on_dock":
            raise RuntimeError("Robot is not on the charging dock")
        if not 0 < target_distance <= max_distance:
            raise ValueError(
                "distance must be positive and no greater than max_distance"
            )

        start_pose = self.slam.localization.get_robot_pose()
        last_pose = start_pose
        last_power = power
        last_distance = 0.0

        if kwargs.get("use_dock_tag", True):
            dock_pose = kwargs.get("dock_pose") or self.slam.home_dock.get_home_pose()
            if dock_pose:
                try:
                    action = self.slam.motion.reflector_undock_action(
                        target=dock_pose,
                        back_up_distance=target_distance,
                        backward_docking=kwargs.get("backward_docking", True),
                        backup_mode=kwargs.get("backup_mode", 1),
                        wait=True,
                        timeout=kwargs.get("timeout", self.action_timeout),
                        poll_interval=kwargs.get("poll_interval", self.poll_interval),
                    )
                    self.slam.require_action_success(
                        action,
                        "Undock from dock tag",
                    )
                    pose = self.slam.localization.get_robot_pose()
                    power = self.slam.power.get_status()
                    distance = math.hypot(
                        pose["x"] - start_pose["x"],
                        pose["y"] - start_pose["y"],
                    )
                    return {
                        "action": action,
                        "mode": "dock_tag",
                        "distance": distance,
                        "pose": pose,
                        "power": power,
                    }
                except Exception as exc:
                    logger.warning(
                        f"Dock-tag undock unavailable; using bounded pulses: {exc}"
                    )

        actions = []
        for _ in range(max_pulses):
            action = self.slam.motion.move_by_action(0, duration=pulse_ms, wait=True)
            self.slam.require_action_success(action, "Undock pulse")
            actions.append(action)

            last_pose = self.slam.localization.get_robot_pose()
            last_distance = math.hypot(
                last_pose["x"] - start_pose["x"],
                last_pose["y"] - start_pose["y"],
            )
            last_power = self.slam.power.get_status()
            on_dock = last_power.get("dockingStatus") == "on_dock"
            if not on_dock and last_distance >= target_distance:
                return {
                    "actions": actions,
                    "distance": last_distance,
                    "pose": last_pose,
                    "power": last_power,
                }
            if last_distance >= max_distance:
                break

        raise RuntimeError(
            "Robot did not clear the dock within the safety limits; "
            f"measured_distance={last_distance:.3f} m, "
            f"docking_status={last_power.get('dockingStatus')}, "
            f"last_pose=({last_pose.get('x'):.3f}, {last_pose.get('y'):.3f})"
        )

    @staticmethod
    def wait_for_charging(power_client, **kwargs):
        timeout = kwargs.get("timeout", 60)
        poll_interval = kwargs.get("poll_interval", 1)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            power = power_client.get_status()
            if power.get("dockingStatus") == "on_dock" and power.get("isCharging"):
                return power
            time.sleep(poll_interval)
        raise TimeoutError("Robot returned home but charging was not detected")

    def return_home(self, **kwargs):
        action = self.slam.motion.dock(
            wait=True,
            timeout=kwargs.get("home_timeout", 300),
            poll_interval=kwargs.get("poll_interval", self.poll_interval),
            charging_retry_count=kwargs.get("charging_retry_count", 3),
            back_to_landing=True,
        )
        self.slam.require_action_success(action, "Return home")
        charging_options = {
            "timeout": kwargs.get("charging_timeout", 60),
            "poll_interval": kwargs.get("poll_interval", self.poll_interval),
        }
        power = self.wait_for_charging(self.slam.power, **charging_options)
        return {"action": action, "power": power}


def demo_undock():
    """Perform a real undock operation; invoke explicitly when debugging."""
    return DockingService(SLAM()).undock()


def main():
    print(demo_undock())


if __name__ == "__main__":
    main()
