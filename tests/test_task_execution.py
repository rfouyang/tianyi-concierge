import threading
import unittest
from unittest.mock import Mock

from component.task_execution.executor import ConciergeTaskExecutor


class ConciergeTaskExecutionTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "id": "task-1",
            "name": "guide",
            "stops": [
                {
                    "poi_id": "poi-1",
                    "poi_name": "Welcome",
                    "content": "Hello",
                    "poi": {
                        "id": "poi-1",
                        "pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
                    },
                    "actions": [
                        {
                            "action_id": "concierge_welcome",
                            "phase": "with_speech",
                            "required": True,
                        }
                    ],
                }
            ],
        }

    def make_executor(self, docking_status="not_on_dock"):
        task_designer = Mock()
        task_designer.get_task.return_value = self.task
        slam = Mock()
        slam.power.get_status.return_value = {
            "dockingStatus": docking_status,
        }
        body_actions = Mock()
        body_actions.arm.return_value = "arm-token"
        body_actions.cancel_current.return_value = False
        executor = ConciergeTaskExecutor(
            task_designer,
            slam=slam,
            body_actions=body_actions,
        )
        executor.preflight = Mock(return_value={"task": self.task})
        executor.speech = Mock()
        executor.speech.prepare.return_value = "welcome.mp3"
        executor.navigation = Mock()
        executor._perform_undock = Mock()
        executor._return_home = Mock()
        return executor

    def task_with_body_action(self):
        task = {
            **self.task,
            "stops": [{**self.task["stops"][0]}],
        }
        task["stops"][0]["actions"] = [
            {
                "action_id": "concierge_welcome",
                "phase": "with_speech",
                "required": True,
            }
        ]
        return task

    def task_with_multiple_body_actions(self):
        task = self.task_with_body_action()
        task["stops"][0]["actions"].append(
            {
                "action_id": "concierge_point",
                "phase": "with_speech",
                "required": True,
            }
        )
        return task

    def test_fresh_task_departs_with_first_navigation(self):
        executor = self.make_executor()

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor._perform_undock.assert_not_called()
        executor.navigation.navigate.assert_called_once()
        executor._return_home.assert_called_once()
        self.assertEqual(events[-1]["status"], "completed")
        self.assertTrue(any("from the current position" in event["message"] for event in events))

    def test_unlocalized_robot_cannot_start_a_task(self):
        executor = self.make_executor()
        executor.localization_guard = Mock(side_effect=RuntimeError("Tianyi is not localized"))

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor.navigation.navigate.assert_not_called()
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("not localized", events[-1]["message"])

    def test_unlocalized_robot_cannot_navigate_or_go_home(self):
        executor = self.make_executor()
        executor.localization_guard = Mock(side_effect=RuntimeError("Tianyi is not localized"))

        with self.assertRaisesRegex(RuntimeError, "not localized"):
            executor.debug_poi("poi-1")
        with self.assertRaisesRegex(RuntimeError, "not localized"):
            executor.return_home()
        executor.navigation.navigate.assert_not_called()

    def test_navigation_failure_on_dock_does_not_run_recovery(self):
        executor = self.make_executor(docking_status="on_dock")
        executor.navigation.navigate.side_effect = RuntimeError("move rejected")

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor._perform_undock.assert_not_called()
        executor._return_home.assert_not_called()
        self.assertNotIn("recovering", [event["status"] for event in events])
        self.assertEqual(events[-1]["status"], "failed")
        self.assertNotIn("returned to the dock", events[-1]["message"])

    def test_navigation_failure_after_departure_runs_recovery(self):
        executor = self.make_executor(docking_status="not_on_dock")
        executor.navigation.navigate.side_effect = RuntimeError("path blocked")

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor._return_home.assert_called_once()
        self.assertIn("recovering", [event["status"] for event in events])
        self.assertIn("returned to the dock", events[-1]["message"])

    def test_body_action_and_speech_run_together_after_navigation(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}
        calls = []
        executor.navigation.navigate.side_effect = lambda *args, **kwargs: calls.append("navigate")
        executor.body_actions.prepare.side_effect = lambda *args, **kwargs: calls.append("prepare")
        workers_started = threading.Barrier(2, timeout=1)

        def action(*args, **kwargs):
            calls.append("action")
            workers_started.wait()

        def speech(*args, **kwargs):
            calls.append("speech")
            workers_started.wait()

        executor.body_actions.execute.side_effect = action
        executor.speech.play.side_effect = speech

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        self.assertEqual(calls[:2], ["prepare", "navigate"])
        self.assertCountEqual(calls[2:], ["action", "speech"])
        executor.body_actions.arm.assert_called_once_with(
            ["concierge_welcome"],
            confirmed=True,
        )
        self.assertIn("body_preparing", [event["status"] for event in events])
        self.assertIn("performing_stop", [event["status"] for event in events])
        self.assertEqual(events[-1]["status"], "completed")

    def test_poi_completes_only_after_action_and_speech_both_finish(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}
        action_finished = threading.Event()
        speech_finished = threading.Event()

        def action(*args, **kwargs):
            action_finished.set()
            self.assertFalse(speech_finished.is_set())

        def speech(*args, **kwargs):
            self.assertTrue(action_finished.wait(timeout=1))
            speech_finished.set()

        executor.body_actions.execute.side_effect = action
        executor.speech.play.side_effect = speech

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        completed = next(event for event in events if event["status"] == "stop_completed")
        self.assertEqual(completed["poi_name"], "Welcome")
        self.assertTrue(action_finished.is_set())
        self.assertTrue(speech_finished.is_set())

    def test_multiple_actions_play_in_order_while_speech_runs(self):
        executor = self.make_executor()
        task = self.task_with_multiple_body_actions()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}
        action_calls = []
        speech_started = threading.Event()

        def action(action_id, *args, **kwargs):
            self.assertTrue(speech_started.wait(timeout=1))
            action_calls.append(action_id)

        def speech(*args, **kwargs):
            speech_started.set()

        executor.body_actions.execute.side_effect = action
        executor.speech.play.side_effect = speech

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        self.assertEqual(
            action_calls,
            ["concierge_welcome", "concierge_point"],
        )
        executor.body_actions.arm.assert_called_once_with(
            ["concierge_point", "concierge_welcome"],
            confirmed=True,
        )
        performing = next(event for event in events if event["status"] == "performing_stop")
        self.assertEqual(
            performing["action_ids"],
            ["concierge_welcome", "concierge_point"],
        )

    def test_speech_only_poi_keeps_arms_at_prepared_init_pose(self):
        executor = self.make_executor()
        task = {
            **self.task,
            "stops": [{**self.task["stops"][0], "actions": []}],
        }
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor.body_actions.arm.assert_called_once_with([], confirmed=True)
        executor.body_actions.prepare.assert_called_once_with("arm-token")
        executor.body_actions.execute.assert_not_called()
        executor.speech.play.assert_called_once_with("welcome.mp3")
        performing = next(event for event in events if event["status"] == "performing_stop")
        self.assertEqual(performing["action_ids"], [])
        self.assertIn("Keeping arms at concierge_init", performing["message"])
        self.assertEqual(events[-1]["status"], "completed")

    def test_body_action_requires_run_confirmation(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}

        events = list(executor.run_events("task-1"))

        executor.navigation.navigate.assert_not_called()
        executor.body_actions.arm.assert_not_called()
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("Confirm physical Tianyi arm actions", events[-1]["message"])

    def test_init_pose_failure_prevents_navigation(self):
        executor = self.make_executor(docking_status="on_dock")
        executor.body_actions.prepare.side_effect = RuntimeError("arm status stale")

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor.navigation.navigate.assert_not_called()
        executor._return_home.assert_not_called()
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("arm status stale", events[-1]["message"])

    def test_body_action_failure_keeps_base_at_poi(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}
        executor.body_actions.execute.side_effect = RuntimeError("arm controller failed")

        events = list(executor.run_events("task-1", body_actions_confirmed=True))

        executor._return_home.assert_not_called()
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("remains at its current location", events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
