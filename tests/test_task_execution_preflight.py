import unittest
from unittest.mock import Mock

from component.task_execution.preflight import ConciergeExecutionPreflight


class ConciergeExecutionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "id": "task-1",
            "name": "guide",
            "stops": [
                {
                    "poi_id": "poi-1",
                    "poi_name": "Welcome",
                    "content": "Hello",
                    "actions": [
                        {
                            "action_id": "concierge_present_left",
                            "phase": "with_speech",
                            "required": True,
                        }
                    ],
                }
            ],
        }
        self.task_designer = Mock()
        self.task_designer.resolve_task.return_value = self.task
        self.slam = Mock()
        self.slam.map_client.get_map_status.return_value = {
            "map_load_status": "LOADED"
        }
        self.slam.mapping.is_enabled.return_value = False
        self.slam.motion.get_current_action.return_value = None
        self.slam.localization.get_localization_quality.return_value = 87
        self.slam.power.get_status.return_value = {
            "dockingStatus": "not_on_dock",
            "isCharging": False,
        }
        self.slam.home_dock.require_bound_home_dock.return_value = {
            "id": "home-dock"
        }
        self.body_actions = Mock()
        self.body_actions.list_actions.return_value = [
            {"action_id": "concierge_present_left", "ready": True}
        ]
        self.body_actions.health.return_value = {"ready": True}
        self.preflight = ConciergeExecutionPreflight(
            self.task_designer,
            self.slam,
            self.body_actions,
        )

    def test_fresh_task_can_start_from_current_off_dock_position(self):
        result = self.preflight.check(self.task)

        self.assertEqual(result["power"]["dockingStatus"], "not_on_dock")
        self.slam.home_dock.require_on_dock.assert_not_called()
        self.slam.power.require_charging.assert_not_called()
        self.slam.home_dock.require_bound_home_dock.assert_called_once_with()

    def test_current_position_start_still_requires_bound_home_dock(self):
        self.slam.home_dock.require_bound_home_dock.side_effect = RuntimeError(
            "No bound dock"
        )

        with self.assertRaisesRegex(RuntimeError, "No bound dock"):
            self.preflight.check(self.task)

    def test_speech_only_stop_passes_arm_init_preflight(self):
        task = {
            **self.task,
            "stops": [{**self.task["stops"][0], "actions": []}],
        }
        self.task_designer.resolve_task.return_value = task

        result = self.preflight.check(task)

        self.assertEqual(result["task"]["stops"][0]["actions"], [])
        self.body_actions.health.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
