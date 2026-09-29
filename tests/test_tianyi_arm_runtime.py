import unittest

from component.common.tianyi_arm_runtime import TianyiArmRuntime
from util.tianyi_arm_mapping import (
    RECORDER_NAME_BY_MOTOR_ID,
    TIANYI_ARM_MOTOR_IDS,
)
from util.tianyi_arm_status import (
    TianyiArmMotorStatus,
    TianyiArmStatusSnapshot,
)


class FakeArtifacts:
    def __init__(self, *, valid=True):
        self.valid = valid

    def list_action_names(self):
        return ("concierge_present_left",)

    def validate_action(self, name):
        if not self.valid:
            raise ValueError("invalid trajectory")
        return type("Trajectory", (), {"duration_seconds": 5.0})()


class FakeStatusSubscriber:
    def __init__(self, *, error=None):
        self.error = error
        self.closed = False
        self.positions = {motor_id: 0.0 for motor_id in TIANYI_ARM_MOTOR_IDS}

    def require_ready(self):
        if self.error:
            raise RuntimeError(self.error)
        return TianyiArmStatusSnapshot(
            motors=tuple(
                TianyiArmMotorStatus(
                    motor_id=motor_id,
                    position=self.positions[motor_id],
                    speed=0.0,
                    current=0.0,
                    temperature=25.0,
                    error=0,
                    received_at=0.0,
                )
                for motor_id in TIANYI_ARM_MOTOR_IDS
            )
        )

    def close(self):
        self.closed = True


class FakeCommandPublisher:
    def __init__(self, *, error=None):
        self.error = error
        self.checked = False
        self.published = []
        self.closed = False

    def require_subscriber(self):
        self.checked = True
        if self.error:
            raise RuntimeError(self.error)

    def publish(self, batch):
        self.published.append(batch)

    def close(self):
        self.closed = True


class FakeMotionService:
    def __init__(self, status):
        self.status = status
        self.move_count = 0
        self.executed_actions = []

    def move_to_concierge_init(self, cancel_event):
        self.move_count += 1
        self.status.positions = {
            motor_id: 0.2 for motor_id in TIANYI_ARM_MOTOR_IDS
        }

    def execute(self, action_name, cancel_event):
        self.executed_actions.append(action_name)
        self.status.positions = {
            motor_id: 0.2 for motor_id in TIANYI_ARM_MOTOR_IDS
        }


class TianyiArmRuntimeTests(unittest.TestCase):
    def make_runtime(self, *, artifacts=None, status=None, publisher=None):
        return TianyiArmRuntime(
            artifact_loader=artifacts or FakeArtifacts(),
            status_subscriber=status or FakeStatusSubscriber(),
            command_publisher=publisher or FakeCommandPublisher(),
            motion_service=object(),
        )

    def test_physical_init_move_requires_explicit_confirmation(self):
        runtime = self.make_runtime()

        with self.assertRaisesRegex(PermissionError, "confirmation"):
            runtime.move_to_concierge_init(confirmed=False)

    def test_confirmed_init_move_runs_preflight_and_reports_final_error(self):
        artifacts = FakeArtifacts()
        artifacts.load_pose = lambda **_: {
            RECORDER_NAME_BY_MOTOR_ID[motor_id]: 0.2
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }
        status = FakeStatusSubscriber()
        motion = FakeMotionService(status)
        publisher = FakeCommandPublisher()
        runtime = TianyiArmRuntime(
            artifact_loader=artifacts,
            status_subscriber=status,
            command_publisher=publisher,
            motion_service=motion,
        )

        result = runtime.move_to_concierge_init(confirmed=True)

        self.assertEqual(motion.move_count, 1)
        self.assertTrue(publisher.checked)
        self.assertEqual(result["maximum_error_rad"], 0.0)
        self.assertEqual(result["motor_ids"], list(TIANYI_ARM_MOTOR_IDS))

    def test_confirmed_action_prepares_executes_and_reports_home_error(self):
        artifacts = FakeArtifacts()
        artifacts.load_pose = lambda **_: {
            RECORDER_NAME_BY_MOTOR_ID[motor_id]: 0.2
            for motor_id in TIANYI_ARM_MOTOR_IDS
        }
        status = FakeStatusSubscriber()
        motion = FakeMotionService(status)
        publisher = FakeCommandPublisher()
        runtime = TianyiArmRuntime(
            artifact_loader=artifacts,
            status_subscriber=status,
            command_publisher=publisher,
            motion_service=motion,
        )

        result = runtime.execute_action(
            "concierge_present_left",
            confirmed=True,
        )

        self.assertEqual(motion.executed_actions, ["concierge_present_left"])
        self.assertEqual(result["action_name"], "concierge_present_left")
        self.assertEqual(result["maximum_final_error_rad"], 0.0)

    def test_action_requires_explicit_confirmation(self):
        runtime = self.make_runtime()

        with self.assertRaisesRegex(PermissionError, "confirmation"):
            runtime.execute_action("concierge_present_left", confirmed=False)

    def test_read_only_preflight_checks_artifacts_status_and_command_subscriber(self):
        publisher = FakeCommandPublisher()
        runtime = self.make_runtime(publisher=publisher)

        health = runtime.preflight()

        self.assertTrue(health.ready)
        self.assertEqual(health.motor_count, 14)
        self.assertEqual(health.action_names, ("concierge_present_left",))
        self.assertTrue(publisher.checked)
        self.assertEqual(publisher.published, [])

    def test_preflight_reports_stale_or_missing_arm_status(self):
        runtime = self.make_runtime(
            status=FakeStatusSubscriber(error="arm status is stale")
        )

        health = runtime.preflight()

        self.assertFalse(health.ready)
        self.assertEqual(health.error, "arm status is stale")

    def test_preflight_rejects_missing_vendor_command_subscriber(self):
        runtime = self.make_runtime(
            publisher=FakeCommandPublisher(error="no /arm/cmd_pos subscriber")
        )

        health = runtime.preflight()

        self.assertFalse(health.ready)
        self.assertIn("/arm/cmd_pos", health.error)

    def test_invalid_local_action_blocks_preflight_before_ros_status(self):
        status = FakeStatusSubscriber()
        runtime = self.make_runtime(
            artifacts=FakeArtifacts(valid=False),
            status=status,
        )

        health = runtime.preflight()

        self.assertFalse(health.ready)
        self.assertIn("No valid", health.error)

    def test_close_releases_both_ros_boundaries(self):
        status = FakeStatusSubscriber()
        publisher = FakeCommandPublisher()
        runtime = self.make_runtime(status=status, publisher=publisher)

        runtime.close()

        self.assertTrue(status.closed)
        self.assertTrue(publisher.closed)


if __name__ == "__main__":
    unittest.main()
