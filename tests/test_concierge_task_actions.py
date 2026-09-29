import unittest
from uuid import uuid4

from component.common.concierge_task import ConciergeTask


class ConciergeTaskActionTests(unittest.TestCase):
    def test_ordered_actions_round_trip_with_stop(self):
        value = {
            "id": str(uuid4()),
            "name": "Concierge tour",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                    "actions": [
                        {
                            "action_id": "concierge_welcome",
                            "phase": "with_speech",
                            "required": True,
                        },
                        {
                            "action_id": "concierge_point",
                            "phase": "with_speech",
                            "required": True,
                        },
                    ],
                }
            ],
        }

        task = ConciergeTask.from_dict(value, require_stops=True)

        self.assertEqual(
            task.to_dict()["stops"][0]["actions"],
            value["stops"][0]["actions"],
        )

    def test_legacy_before_speech_phase_is_normalized(self):
        value = {
            "id": str(uuid4()),
            "name": "Legacy concierge tour",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                    "action": {
                        "action_id": "concierge_welcome",
                        "phase": "before_speech",
                        "required": True,
                    },
                }
            ],
        }

        task = ConciergeTask.from_dict(value, require_stops=True)

        self.assertEqual(task.stops[0].actions[0].phase, "with_speech")
        self.assertNotIn("action", task.to_dict()["stops"][0])

    def test_existing_stop_without_action_remains_valid(self):
        value = {
            "id": str(uuid4()),
            "name": "Speech-only tour",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                }
            ],
        }

        task = ConciergeTask.from_dict(value, require_stops=True)

        self.assertNotIn("action", task.to_dict()["stops"][0])
        self.assertEqual(task.to_dict()["stops"][0]["actions"], [])

    def test_unknown_action_phase_is_rejected(self):
        value = {
            "id": str(uuid4()),
            "name": "Unsafe concurrency",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                    "actions": [
                        {
                            "action_id": "concierge_welcome",
                            "phase": "during_navigation",
                        }
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "Unsupported task arm action phase"):
            ConciergeTask.from_dict(value, require_stops=True)


if __name__ == "__main__":
    unittest.main()
