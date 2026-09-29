import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.concierge_main import create_mrt_app


class StubMrtService:
    def __init__(self):
        self.started = []
        self.created = True

    def health(self):
        return {"ready": True, "motor_count": 14}

    def list_actions(self):
        return [{"action_id": "urs_mrt_stop_left", "ready": True}]

    def start(self, **kwargs):
        self.started.append(kwargs)
        return (
            {"operation_id": "operation-1", "status": "accepted", "action_id": kwargs["action_id"]},
            self.created,
        )

    def get(self, operation_id):
        if operation_id != "operation-1":
            raise KeyError(operation_id)
        return {"operation_id": operation_id, "status": "completed"}

    def cancel(self, operation_id):
        if operation_id != "operation-1":
            raise KeyError(operation_id)
        return {"operation_id": operation_id, "status": "cancelling"}


class MrtApiTests(unittest.TestCase):
    """The FastAPI port keeps the original Flask contract."""

    def setUp(self):
        self.service = StubMrtService()
        application = SimpleNamespace(
            mrt=self.service,
            settings=SimpleNamespace(mrt_api_key="test-key"),
        )
        self.client = TestClient(create_mrt_app(application))
        self.authorization = {"Authorization": "Bearer test-key"}

    def test_requires_bearer_authentication(self):
        response = self.client.get("/api/mrt/v1/health")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"status": "failed", "message": "Unauthorized"})

    def test_rejects_wrong_key(self):
        response = self.client.get("/api/mrt/v1/health", headers={"Authorization": "Bearer nope"})

        self.assertEqual(response.status_code, 401)

    def test_action_numbers_start_the_four_confirmed_interventions(self):
        expected = (
            "urs_mrt_stop_left",
            "urs_mrt_stop_left_2",
            "urs_mrt_stop_right",
            "urs_mrt_stop_right_2",
        )
        for number, action_id in enumerate(expected, start=1):
            with self.subTest(number=number):
                response = self.client.get(
                    f"/api/mrt/v1/interventions?action={number}&request_id=gate-{number}",
                    headers=self.authorization,
                )

                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["operation_id"], "operation-1")
                self.assertEqual(
                    self.service.started[-1],
                    {
                        "request_id": f"gate-{number}",
                        "action_id": action_id,
                        "arm_motion_confirmed": True,
                    },
                )

    def test_idempotent_retry_returns_existing_operation(self):
        self.service.created = False

        response = self.client.get(
            "/api/mrt/v1/interventions?action=1&request_id=gate-a-1", headers=self.authorization
        )

        self.assertEqual(response.status_code, 200)

    def test_rejects_invalid_action_number(self):
        response = self.client.get("/api/mrt/v1/interventions?action=5", headers=self.authorization)

        self.assertEqual(response.status_code, 400)
        self.assertIn("1, 2, 3, or 4", response.json()["message"])

    def test_unknown_operation_returns_not_found(self):
        response = self.client.get("/api/mrt/v1/interventions/missing", headers=self.authorization)

        self.assertEqual(response.status_code, 404)

    def test_busy_robot_returns_conflict(self):
        def busy(**kwargs):
            raise RuntimeError("Tianyi is busy with a tour or manual operation")

        self.service.start = busy
        response = self.client.get("/api/mrt/v1/interventions?action=1", headers=self.authorization)

        self.assertEqual(response.status_code, 409)
        self.assertIn("busy", response.json()["message"])

    def test_console_routes_are_not_exposed_on_the_public_port(self):
        response = self.client.get("/api/concierge/status")

        self.assertEqual(response.status_code, 404)
