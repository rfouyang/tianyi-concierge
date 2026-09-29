import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from uuid import uuid4

from test_speech import FakeTts, robot_wav

from component.common.speech import SpeechService
from component.task_design.service import TaskDesigner


class TaskDesignerTests(unittest.TestCase):
    def test_task_resolution_allows_legacy_stop_without_action(self):
        poi_id = str(uuid4())
        slam = Mock()
        slam.poi.get_all.return_value = [{"id": poi_id, "metadata": {"display_name": "Reception"}}]
        designer = TaskDesigner(slam=slam)
        task = {
            "id": str(uuid4()),
            "name": "Legacy task",
            "stops": [
                {
                    "poi_id": poi_id,
                    "poi_name": "Reception",
                    "content": "Welcome",
                }
            ],
        }

        resolved = designer.resolve_task(task)

        self.assertEqual(resolved["stops"][0]["actions"], [])

    def test_save_allows_stop_without_action(self):
        poi_id = str(uuid4())
        with TemporaryDirectory() as temporary_directory:
            designer = TaskDesigner(path=Path(temporary_directory) / "task.json")

            saved = designer.save_task(
                "Speech only task",
                [
                    {
                        "poi_id": poi_id,
                        "poi_name": "Reception",
                        "content": "Welcome",
                    }
                ],
            )

            self.assertEqual(saved["stops"][0]["actions"], [])

    def test_save_rejects_unavailable_action(self):
        poi_id = str(uuid4())
        body_actions = Mock()
        body_actions.list_actions.return_value = [
            {"action_id": "concierge_present_left", "ready": True}
        ]
        with TemporaryDirectory() as temporary_directory:
            designer = TaskDesigner(
                path=Path(temporary_directory) / "task.json",
                body_actions=body_actions,
            )

            with self.assertRaisesRegex(ValueError, "missing_action"):
                designer.save_task(
                    "Invalid action task",
                    [
                        {
                            "poi_id": poi_id,
                            "poi_name": "Reception",
                            "content": "Welcome",
                            "actions": [
                                {
                                    "action_id": "missing_action",
                                    "phase": "with_speech",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                )

    def stops(self, **extra):
        return [{"poi_id": str(uuid4()), "poi_name": "Reception", "content": "Welcome", **extra}]

    def test_save_prepares_speech_for_every_stop(self):
        with TemporaryDirectory() as directory:
            tts = FakeTts()
            speech = SpeechService(Path(directory) / "tts", tts=tts, player=Mock())
            designer = TaskDesigner(path=Path(directory) / "task.json", speech=speech)

            saved = designer.save_task("Tour", self.stops())

            self.assertTrue(saved["speech"]["ready"])
            self.assertEqual(tts.calls, ["Welcome"])
            self.assertEqual(saved["speech"]["durations"], [0.1])
            self.assertEqual(saved["speech"]["total_duration"], 0.1)
            self.assertTrue(speech.is_cached("Welcome"))

    def test_save_keeps_the_task_when_offline_and_reports_missing_speech(self):
        with TemporaryDirectory() as directory:
            tts = FakeTts(fail=True)
            speech = SpeechService(Path(directory) / "tts", tts=tts, player=Mock())
            designer = TaskDesigner(path=Path(directory) / "task.json", speech=speech)

            saved = designer.save_task("Tour", self.stops())

            self.assertFalse(saved["speech"]["ready"])
            self.assertEqual(saved["speech"]["missing"][0]["poi_name"], "Reception")
            self.assertEqual(len(designer.list_tasks()), 1)

    def test_uploaded_speech_is_not_synthesized(self):
        with TemporaryDirectory() as directory:
            tts = FakeTts()
            speech = SpeechService(Path(directory) / "tts", tts=tts, player=Mock())
            stored = speech.store_upload(robot_wav())
            designer = TaskDesigner(path=Path(directory) / "task.json", speech=speech)

            saved = designer.save_task(
                "Tour", self.stops(audio=stored["file"], audio_name="studio.wav")
            )

            self.assertTrue(saved["speech"]["ready"])
            self.assertEqual(tts.calls, [])
            self.assertEqual(saved["stops"][0]["audio_name"], "studio.wav")

    def test_invalid_uploaded_speech_name_is_rejected(self):
        with TemporaryDirectory() as directory:
            designer = TaskDesigner(path=Path(directory) / "task.json")

            with self.assertRaisesRegex(ValueError, "invalid file name"):
                designer.save_task("Tour", self.stops(audio="../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
