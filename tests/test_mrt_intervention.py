import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from component.mrt_intervention import MRT_ACTIONS, MrtInterventionService


class FakeBodyActions:
    def __init__(self):
        self.armed = []
        self.prepared = []
        self.executed = []
        self.cancelled = 0
        self.closed = False

    def list_actions(self):
        return [
            {
                "action_id": action_id,
                "label": action.label,
                "ready": True,
                "duration": 8.0,
            }
            for action_id, action in MRT_ACTIONS.items()
        ]

    def health(self):
        return {"ready": True, "error": None, "motor_count": 14}

    def arm(self, action_ids, *, confirmed):
        self.armed.append((list(action_ids), confirmed))
        return "arm-token"

    def prepare(self, token):
        self.prepared.append(token)

    def execute(self, action_id, token, cancel_event):
        self.executed.append((action_id, token, cancel_event))
        return {"status": "completed"}

    def cancel_current(self):
        self.cancelled += 1
        return True

    def close(self):
        self.closed = True


class FakePlayer:
    def __init__(self):
        self.played = []

    def play(self, path):
        self.played.append(path)


class BlockingPlayer(FakePlayer):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def play(self, path):
        self.started.set()
        self.release.wait(timeout=2)
        super().play(path)


class MrtInterventionServiceTests(unittest.TestCase):
    def setUp(self):
        self.body_actions = FakeBodyActions()
        self.player = FakePlayer()
        self.temp_dir = TemporaryDirectory()
        self.audio_dir = Path(self.temp_dir.name)
        for action in MRT_ACTIONS.values():
            (self.audio_dir / action.audio_file).write_bytes(b"RIFF")
        self.service = MrtInterventionService(
            body_actions=self.body_actions,
            player=self.player,
            audio_dir=self.audio_dir,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def wait_for_terminal(self, operation_id):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            operation = self.service.get(operation_id)
            if operation["status"] in {"completed", "cancelled", "failed"}:
                return operation
            time.sleep(0.01)
        self.fail("MRT intervention did not reach a terminal status")

    def test_runs_selected_action_with_fixed_audio(self):
        operation, created = self.service.start(
            request_id="gate-a-1",
            action_id="urs_mrt_stop_left",
            arm_motion_confirmed=True,
        )

        completed = self.wait_for_terminal(operation["operation_id"])

        self.assertTrue(created)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            self.body_actions.armed,
            [(["urs_mrt_stop_left"], True)],
        )
        self.assertEqual(self.body_actions.prepared, ["arm-token"])
        self.assertEqual(self.body_actions.executed[0][:2], ("urs_mrt_stop_left", "arm-token"))
        self.assertEqual(
            self.player.played,
            [self.audio_dir / "mrt_stop_left.wav"],
        )
        self.assertEqual(
            completed["text"],
            MRT_ACTIONS["urs_mrt_stop_left"].message,
        )

    def test_repeated_request_id_does_not_repeat_the_action(self):
        first, _ = self.service.start(
            request_id="gate-a-2",
            action_id="urs_mrt_stop_right",
            arm_motion_confirmed=True,
        )
        self.wait_for_terminal(first["operation_id"])

        repeated, created = self.service.start(
            request_id="gate-a-2",
            action_id="urs_mrt_stop_right",
            arm_motion_confirmed=True,
        )

        self.assertFalse(created)
        self.assertEqual(repeated["operation_id"], first["operation_id"])
        self.assertEqual(len(self.body_actions.executed), 1)

    def test_rejects_missing_motion_confirmation(self):
        with self.assertRaisesRegex(PermissionError, "confirmation"):
            self.service.start(
                request_id="gate-a-3",
                action_id="urs_mrt_stop_left",
                arm_motion_confirmed=False,
            )

        self.assertEqual(self.body_actions.armed, [])

    def test_missing_fixed_audio_blocks_arm_motion(self):
        (self.audio_dir / "mrt_stop_left.wav").unlink()

        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.service.start(
                request_id="gate-a-4",
                action_id="urs_mrt_stop_left_2",
                arm_motion_confirmed=True,
            )

        self.assertEqual(self.body_actions.armed, [])

    def test_rejects_second_intervention_while_busy(self):
        blocking_player = BlockingPlayer()
        self.service = MrtInterventionService(
            body_actions=self.body_actions,
            player=blocking_player,
            audio_dir=self.audio_dir,
        )
        first, _ = self.service.start(
            request_id="gate-a-5",
            action_id="urs_mrt_stop_left",
            arm_motion_confirmed=True,
        )
        self.assertTrue(blocking_player.started.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.service.start(
                request_id="gate-a-6",
                action_id="urs_mrt_stop_right",
                arm_motion_confirmed=True,
            )

        blocking_player.release.set()
        self.wait_for_terminal(first["operation_id"])


if __name__ == "__main__":
    unittest.main()
