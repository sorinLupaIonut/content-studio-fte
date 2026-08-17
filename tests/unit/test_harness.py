"""D1 HTTP contract and approval matching, without model or sandbox calls."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from content_studio.config import MissingConfig
from content_studio.harness.main import create_app
from content_studio.harness.models import (
    ApprovalDecision,
    BackendHealth,
    HealthResponse,
    PendingResponse,
    RunResponse,
    ToolApprovalRequest,
)
from content_studio.harness.service import (
    HarnessError,
    HarnessService,
    match_decisions,
    validate_session_id,
)

REQUEST = ToolApprovalRequest(
    call_id="call-1",
    tool_name="save_post",
    arguments={"title": "Titlu"},
)


class FakeService:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def health(self) -> HealthResponse:
        return HealthResponse(
            status="degraded",
            backends={
                "postgres": BackendHealth(
                    configured=False,
                    active=False,
                    detail="DATABASE_URL lipsește.",
                )
            },
        )

    async def run(self, message: str, session_id: str | None) -> RunResponse:
        return RunResponse(
            run_id="run-1",
            session_id=session_id or "viorela-new",
            status="pending",
            requests=[REQUEST],
        )

    async def pending(self, session_id: str) -> PendingResponse:
        return PendingResponse(
            run_id="run-1",
            session_id=session_id,
            input_message="Salvează postarea",
            requests=[REQUEST],
        )

    async def decide(
        self,
        run_id: str,
        session_id: str,
        decisions: list[ApprovalDecision],
        resolved_by: str,
    ) -> RunResponse:
        return RunResponse(
            run_id=run_id,
            session_id=session_id,
            status="completed",
            output=f"Aprobat de {resolved_by}: {decisions[0].approved}",
        )


class TestHarnessHttp(unittest.TestCase):
    def setUp(self) -> None:
        self._client_context = TestClient(create_app(FakeService))
        self.client = self._client_context.__enter__()

    def tearDown(self) -> None:
        self._client_context.__exit__(None, None, None)

    def test_health_can_report_a_degraded_boot(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")

    def test_interrupted_run_returns_202_and_requests(self) -> None:
        response = self.client.post(
            "/runs", json={"message": "Salvează", "session_id": "s1"}
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["requests"][0]["tool_name"], "save_post")

    def test_pending_run_survives_a_page_refresh(self) -> None:
        response = self.client.get("/sessions/s1/pending")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], "run-1")

    def test_decision_resumes_the_same_run(self) -> None:
        response = self.client.post(
            "/runs/run-1/decisions",
            json={
                "session_id": "s1",
                "resolved_by": "viorela",
                "decisions": [{"call_id": "call-1", "approved": True}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertIn("viorela", response.json()["output"])


class TestDecisionMatching(unittest.TestCase):
    def test_requires_a_decision_for_every_request(self) -> None:
        requests = [
            {"call_id": "a", "tool_name": "save_post", "arguments": {}},
            {"call_id": "b", "tool_name": "update_profile", "arguments": {}},
        ]

        with self.assertRaises(HarnessError) as caught:
            match_decisions(requests, [ApprovalDecision(call_id="a", approved=True)])

        self.assertEqual(caught.exception.status_code, 422)

    def test_session_id_cannot_inject_an_http_header(self) -> None:
        with self.assertRaises(HarnessError) as caught:
            validate_session_id("session\r\nX-Injected: yes")

        self.assertEqual(caught.exception.status_code, 422)


class TestSdkContracts(unittest.TestCase):
    def test_harness_never_passes_a_live_sandbox_session(self) -> None:
        config = HarnessService._run_config("s1")

        self.assertIsNone(config.sandbox.session)
        self.assertIsNotNone(config.sandbox.client)
        self.assertEqual(config.sandbox.options.sandbox_type, "e2b")

    def test_interrupted_state_is_serialized_synchronously(self) -> None:
        class State:
            def to_string(self) -> str:
                return "serialized-state"

        class Trail:
            parked = None

            async def suspend_run(self, run_id, requests, state) -> None:
                self.parked = (run_id, requests, state)

        request = SimpleNamespace(
            tool_name="save_post",
            raw_item=SimpleNamespace(
                name="save_post",
                call_id="call-1",
                arguments='{"title":"Titlu"}',
            ),
        )
        result = SimpleNamespace(interruptions=[request], to_state=State)
        trail = Trail()

        response = asyncio.run(HarnessService._finish("run-1", "s1", result, trail))

        self.assertEqual(response.status, "pending")
        self.assertEqual(trail.parked[2], "serialized-state")

    def test_rejects_duplicate_decisions(self) -> None:
        requests = [{"call_id": "a", "tool_name": "save_post", "arguments": {}}]
        decisions = [
            ApprovalDecision(call_id="a", approved=True),
            ApprovalDecision(call_id="a", approved=False),
        ]

        with self.assertRaises(HarnessError) as caught:
            match_decisions(requests, decisions)

        self.assertEqual(caught.exception.status_code, 422)


class TestDegradedBoot(unittest.IsolatedAsyncioTestCase):
    @patch(
        "content_studio.harness.service.database_url",
        side_effect=MissingConfig("DATABASE_URL lipsește."),
    )
    async def test_missing_database_does_not_stop_the_process(self, _database_url) -> None:
        service = HarnessService()

        await service.start()
        try:
            self.assertIsNone(service.engine)
            self.assertEqual(service.database_error, "DATABASE_URL lipsește.")
        finally:
            await service.close()


if __name__ == "__main__":
    unittest.main()
