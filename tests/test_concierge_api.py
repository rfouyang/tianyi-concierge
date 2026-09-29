import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from test_speech import FakeTts, robot_wav

from app.concierge_main import create_console_app
from component.common.speech import SpeechService
from component.robot_operation import RobotOperationRunner
from component.task_design.service import TaskDesigner
from config.settings import AppSettings


def wait_idle(runner):
    event = threading.Event()
    for _ in range(200):
        if not runner.is_busy():
            return runner.snapshot()
        event.wait(0.01)
    raise AssertionError("operation did not finish")


class ConciergeApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.poi_id = str(uuid4())
        slam = Mock()
        slam.poi.get_all.return_value = [
            {"id": self.poi_id, "metadata": {"display_name": "Reception", "type": "ROOM"}}
        ]
        self.tts = FakeTts()
        speech = SpeechService(root / "tts", tts=self.tts, player=Mock())
        self.task_design = TaskDesigner(path=root / "task.json", slam=slam, speech=speech)
        self.operations = RobotOperationRunner()
        self.execution = Mock()
        self.execution.get_resume_checkpoint.return_value = None
        self.execution.rehearse.return_value = {"status": "completed"}
        self.localizer = Mock()
        self.status = Mock()
        self.status.snapshot.return_value = {"revision": 3, "connected": True}
        self.navigation = Mock()
        self.navigation.stop.return_value = True
        application = SimpleNamespace(
            settings=AppSettings(mrt_port=8088),
            status=self.status,
            operations=self.operations,
            navigation=self.navigation,
            task_design=self.task_design,
            task_execution=self.execution,
            map_localization=self.localizer,
            map_building=Mock(),
            map_view=Mock(),
            poi_management=Mock(),
            mrt=Mock(active_operation_id=None),
        )
        self.client = TestClient(create_console_app(application))

    def tearDown(self):
        self.temporary.cleanup()

    def stop_payload(self, **extra):
        return {"poi_id": self.poi_id, "poi_name": "Reception", "content": "Welcome", **extra}

    def test_status_returns_robot_and_operation_snapshots(self):
        body = self.client.get("/api/concierge/status").json()

        self.assertEqual(body["robot"]["revision"], 3)
        self.assertIsNone(body["operations"]["active"])

    def test_stop_never_waits_for_the_operation_runner(self):
        release = threading.Event()
        self.operations.start("task", "Run tour", release.wait)

        response = self.client.post("/api/concierge/stop")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["stopped"])
        release.set()
        wait_idle(self.operations)

    def test_hardware_actions_require_confirmation(self):
        cases = [
            ("/api/concierge/maps/load", {"name": "office.stcm"}),
            ("/api/concierge/maps/sync", {}),
            ("/api/concierge/map-building/start", {"filename": "a.stcm", "dock_name": "dock"}),
            ("/api/concierge/execution/run", {"task_id": str(uuid4())}),
            ("/api/concierge/tasks/rehearse", {"actions": [{"action_id": "concierge_wave_left"}]}),
        ]
        for path, body in cases:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json=body).status_code, 403)
        self.assertIsNone(self.operations.snapshot()["latest"])

    def test_second_operation_is_rejected_while_one_runs(self):
        release = threading.Event()
        self.operations.start("navigation_go", "Go to POI", release.wait)

        response = self.client.post("/api/concierge/localization/stop")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Another robot operation", response.json()["detail"])
        release.set()
        wait_idle(self.operations)

    def test_saving_a_task_prepares_its_speech(self):
        created = self.client.post(
            "/api/concierge/tasks", json={"name": "Tour", "stops": [self.stop_payload()]}
        )

        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["speech"]["ready"])
        fetched = self.client.get(f"/api/concierge/tasks/{created.json()['id']}").json()
        self.assertTrue(fetched["speech"]["ready"])
        self.assertEqual(self.tts.calls, ["Welcome"])

    def test_speech_upload_validates_the_robot_format(self):
        accepted = self.client.post(
            "/api/concierge/tasks/speech/upload",
            content=robot_wav(),
            headers={"Content-Type": "audio/wav"},
        )
        rejected = self.client.post(
            "/api/concierge/tasks/speech/upload",
            content=robot_wav(rate=44100),
            headers={"Content-Type": "audio/wav"},
        )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["duration"], 0.1)
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("16000 Hz", rejected.json()["detail"])

    def test_preparing_speech_reports_its_length(self):
        response = self.client.post("/api/concierge/tasks/speech/preview", json={"text": "Hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["duration"], 0.1)

    def test_speech_only_rehearsal_needs_no_arm_confirmation(self):
        response = self.client.post("/api/concierge/tasks/rehearse", json={"content": "Welcome"})

        self.assertEqual(response.status_code, 202)
        latest = wait_idle(self.operations)["latest"]
        self.assertEqual(latest["status"], "completed")
        self.execution.rehearse.assert_called_once_with(
            [], "Welcome", audio=None, arms_confirmed=False
        )

    def test_localize_at_pose_with_rotation_needs_extra_confirmation(self):
        response = self.client.post(
            "/api/concierge/localization/pose",
            json={"x": 1.0, "y": 2.0, "yaw": 0.0, "allow_rotation": True},
        )

        self.assertEqual(response.status_code, 403)

    def test_every_console_page_renders(self):
        for path in (
            "/map-building",
            "/localization",
            "/pois",
            "/navigation",
            "/task-design",
            "/task-execution",
            "/mrt",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Tianyi", response.text)

    def test_root_redirects_to_map_building(self):
        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.headers["location"], "/map-building")


class StaticAssetVersionTests(unittest.TestCase):
    def test_static_urls_change_when_the_file_changes(self):
        from app.ui_concierge.ui_main import STATIC_DIR, static_asset

        url = static_asset("/js/map_view.js")
        version = (STATIC_DIR / "js" / "map_view.js").stat().st_mtime_ns

        self.assertEqual(url, f"/static/concierge/js/map_view.js?v={version}")
