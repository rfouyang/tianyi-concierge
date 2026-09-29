import unittest
from types import SimpleNamespace

from util.tianyi_arm_mapping import TIANYI_ARM_MOTOR_IDS
from util.tianyi_arm_status import TianyiArmStatusMonitor


class TianyiArmStatusMonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.monitor = TianyiArmStatusMonitor(monotonic=lambda: self.now)

    @staticmethod
    def message(*, missing=(), error_by_id=None, temperature_by_id=None):
        error_by_id = error_by_id or {}
        temperature_by_id = temperature_by_id or {}
        statuses = [
            SimpleNamespace(
                name=motor_id,
                pos=motor_id / 100.0,
                speed=0.0,
                current=0.1,
                temperature=temperature_by_id.get(motor_id, 30.0),
                error=error_by_id.get(motor_id, 0),
            )
            for motor_id in TIANYI_ARM_MOTOR_IDS
            if motor_id not in missing
        ]
        return SimpleNamespace(status=statuses)

    def test_returns_all_arm_positions_in_canonical_motor_order(self):
        self.monitor.update(self.message())

        snapshot = self.monitor.require_ready()

        self.assertEqual(
            tuple(snapshot.positions_by_motor_id()),
            TIANYI_ARM_MOTOR_IDS,
        )
        self.assertEqual(snapshot.positions_by_motor_id()[11], 0.11)
        self.assertEqual(snapshot.positions_by_motor_id()[27], 0.27)

    def test_rejects_missing_arm_motor(self):
        self.monitor.update(self.message(missing={17}))

        with self.assertRaisesRegex(RuntimeError, "missing motor IDs: 17"):
            self.monitor.require_ready()

    def test_rejects_stale_arm_status(self):
        self.monitor.update(self.message())
        self.now += 1.01

        with self.assertRaisesRegex(RuntimeError, "status is stale"):
            self.monitor.require_ready()

    def test_rejects_motor_error(self):
        self.monitor.update(self.message(error_by_id={24: 33073}))

        with self.assertRaisesRegex(RuntimeError, "motor 24 reports error 33073"):
            self.monitor.require_ready()

    def test_rejects_overheated_motor(self):
        self.monitor.update(self.message(temperature_by_id={13: 76.0}))

        with self.assertRaisesRegex(RuntimeError, "motor 13 temperature"):
            self.monitor.require_ready()

    def test_ignores_non_arm_motor_status(self):
        message = self.message()
        message.status.append(
            SimpleNamespace(
                name=3,
                pos=1.0,
                speed=0.0,
                current=0.0,
                temperature=20.0,
                error=99,
            )
        )

        self.monitor.update(message)

        self.assertTrue(self.monitor.health()["ready"])


if __name__ == "__main__":
    unittest.main()
