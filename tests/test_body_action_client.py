import threading
import unittest
from types import SimpleNamespace

from component.common.body_action import BodyActionClient


class FakeMotionService:
    def __init__(self):
        self.prepared = 0
        self.executed = []

    def move_to_concierge_init(self, cancel_event):
        self.prepared += 1

    def execute(self, action_id, cancel_event):
        self.executed.append((action_id, cancel_event))


class FakeRuntime:
    def __init__(self):
        self.motion_service = FakeMotionService()
        self.preflight_count = 0
        self.closed = False

    def list_actions(self):
        return [
            {
                "action_id": "concierge_present_left",
                "label": "Concierge Present Left",
                "ready": True,
                "duration": 5.0,
            }
        ]

    def preflight(self):
        return SimpleNamespace(
            to_dict=lambda: {
                "ready": True,
                "error": None,
                "motor_count": 14,
                "action_names": ["concierge_present_left"],
            }
        )

    def require_preflight(self):
        self.preflight_count += 1

    def close(self):
        self.closed = True


class BodyActionClientTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.client = BodyActionClient(runtime=self.runtime)

    def test_lists_valid_local_recorder_actions(self):
        actions = self.client.list_actions()

        self.assertEqual(
            [action["action_id"] for action in actions],
            ["concierge_present_left"],
        )

    def test_prepare_moves_to_concierge_init_after_authorization(self):
        token = self.client.arm(["concierge_present_left"], confirmed=True)

        result = self.client.prepare(token)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.runtime.preflight_count, 1)
        self.assertEqual(self.runtime.motion_service.prepared, 1)

    def test_prepare_allows_init_only_authorization(self):
        token = self.client.arm([], confirmed=True)

        result = self.client.prepare(token)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.runtime.motion_service.prepared, 1)

    def test_execute_uses_same_cancel_event_and_authorized_action(self):
        token = self.client.arm(["concierge_present_left"], confirmed=True)
        cancel_event = threading.Event()

        result = self.client.execute(
            "concierge_present_left",
            token,
            cancel_event,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            self.runtime.motion_service.executed,
            [("concierge_present_left", cancel_event)],
        )

    def test_arm_rejects_missing_confirmation(self):
        with self.assertRaisesRegex(PermissionError, "confirmation"):
            self.client.arm(["concierge_present_left"], confirmed=False)

    def test_execute_rejects_action_outside_authorized_set(self):
        token = self.client.arm(["concierge_present_left"], confirmed=True)

        with self.assertRaisesRegex(PermissionError, "not authorized"):
            self.client.execute("another_action", token, threading.Event())


if __name__ == "__main__":
    unittest.main()
