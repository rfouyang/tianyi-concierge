import threading
import unittest

from component.robot_operation import RobotOperationBusy, RobotOperationRunner


def wait_idle(runner, timeout=2.0):
    finished = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if not runner.is_busy():
            finished.set()
            break
        finished.wait(0.01)
    return runner.snapshot()


class RobotOperationRunnerTests(unittest.TestCase):
    def test_runs_one_operation_at_a_time(self):
        release = threading.Event()
        runner = RobotOperationRunner()
        runner.start("move", "Move", release.wait)

        with self.assertRaises(RobotOperationBusy):
            runner.start("other", "Other", lambda: None)

        release.set()
        snapshot = wait_idle(runner)
        self.assertEqual(snapshot["latest"]["status"], "completed")

    def test_failure_is_recorded_with_its_message(self):
        runner = RobotOperationRunner()

        def fail():
            raise RuntimeError("Robot is not on the charging dock")

        runner.start("load", "Load map", fail)
        latest = wait_idle(runner)["latest"]

        self.assertEqual(latest["status"], "failed")
        self.assertIn("not on the charging dock", latest["error"])

    def test_event_streams_end_with_their_terminal_status(self):
        runner = RobotOperationRunner()
        seen = []

        def events():
            yield {"status": "navigating", "message": "Navigating"}
            yield {"status": "cancelled", "message": "Task cancelled"}

        runner.start_events(
            "task", "Run tour", events, on_event=lambda op, event: seen.append(event["status"])
        )
        latest = wait_idle(runner)["latest"]

        self.assertEqual(latest["status"], "cancelled")
        self.assertEqual(seen, ["navigating", "cancelled"])
        self.assertEqual(len(latest["events"]), 2)

    def test_busy_check_blocks_while_another_subsystem_holds_the_robot(self):
        runner = RobotOperationRunner(busy_check=lambda: "An MRT intervention is running")

        with self.assertRaisesRegex(RobotOperationBusy, "MRT"):
            runner.start("move", "Move", lambda: None)
