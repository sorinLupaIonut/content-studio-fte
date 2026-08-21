"""D1 HTTP contract and approval matching, without model or sandbox calls."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from content_studio.config import CLIENT_SLUG, MissingConfig
from content_studio.harness.auth import AuthSettings, IdentityResolver
from content_studio.harness.chat import ChatRunAccepted
from content_studio.harness.generation import StreamEvent
from content_studio.harness.main import create_app
from content_studio.harness.models import (
    ApprovalDecision,
    BackendHealth,
    HealthResponse,
    PendingResponse,
    ProfileBlock,
    ProfileSection,
    ProfileSectionsResponse,
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


SAVED_POST_ID = "33333333-3333-3333-3333-333333333333"

SAVED_POST_CONTENT = {
    "title": "Când te alegi și pe tine",
    "pillar": "Conexiune",
    "format": "Reel",
    "hook": "Ai grijă de toți, dar de tine cine are?",
    "hook_type": "INTREBARE",
    "script": "Prima linie.",
    "caption": "Un caption scurt.",
    "hashtags": ["#burnout", "#limite", "#peoplepleasing"],
    "cta": "Scrie-mi „limite” în DM.",
    "source": "din memorie 🧠",
    "format_details": {
        "content_blocks": ["Cadru 1"],
        "visual_direction": "Lumină naturală.",
        "duration_or_count": "35–45 secunde",
    },
}


class FakeAccounts:
    """Just the surface `main.py` touches, with nobody provisioned.

    That is the honest default for these tests: with `app_users` empty, every
    request binds to the configured client and no route behaves differently from
    the way it did before accounts existed.
    """

    bound: list[str | None] = []

    async def bind(self, principal_id):
        FakeAccounts.bound.append(principal_id)
        return CLIENT_SLUG

    async def account_for(self, principal_id):
        return None

    async def budget_for(self, client_slug=None):
        return None


class FakeService:
    last_generation_principal = None
    last_chat_principal = None
    last_save_principal = None

    def __init__(self) -> None:
        self.accounts = FakeAccounts()

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

    async def run(
        self, message: str, session_id: str | None, language: str = "ro"
    ) -> RunResponse:
        self.language_seen = language
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
        language: str = "ro",
    ) -> RunResponse:
        self.language_seen = language
        return RunResponse(
            run_id=run_id,
            session_id=session_id,
            status="completed",
            output=f"Aprobat de {resolved_by}: {decisions[0].approved}",
        )

    async def profile_sections(self, principal_id: str) -> ProfileSectionsResponse:
        return ProfileSectionsResponse(
            sections=[
                ProfileSection(
                    key="brand--voice",
                    title="Vocea ta",
                    group="voice",
                    update_name="Vocea ta",
                    blocks=[ProfileBlock(kind="paragraph", text=principal_id)],
                )
            ]
        )

    async def prepare_profile_update(
        self, principal_id: str, section_key: str, blocks: list[ProfileBlock]
    ) -> RunResponse:
        return RunResponse(
            run_id="profile-run",
            session_id=f"profile-{principal_id}",
            status="pending",
            requests=[
                ToolApprovalRequest(
                    call_id="profile-call",
                    tool_name="update_profile",
                    arguments={"section": section_key, "new_text": blocks[0].text},
                )
            ],
        )

    async def library(self, principal_id: str) -> list[dict]:
        return [{"id": "11111111-1111-1111-1111-111111111111", "title": "Carte"}]

    async def start_generation(self, principal_id: str, request) -> dict:
        self.last_generation_principal = principal_id
        return {
            "id": "22222222-2222-2222-2222-222222222222",
            "status": "gathering",
            "format": request.format,
            "pillar": request.pillar,
            "source": request.source,
            "ideas": [],
        }

    async def current_generation(self, principal_id: str) -> dict:
        return {
            "id": "22222222-2222-2222-2222-222222222222",
            "status": "titles_ready",
            "ideas": [],
        }

    async def generation_batch(self, principal_id: str, batch_id: UUID) -> dict:
        return {"id": str(batch_id), "status": "ready", "ideas": []}

    async def cancel_generation(self, principal_id: str, batch_id: UUID) -> dict:
        return {"batch_id": str(batch_id), "status": "cancelled"}

    async def select_generation_variant(
        self, principal_id: str, variant_id: UUID
    ) -> dict:
        return {"variant_id": str(variant_id)}

    async def generation_events(
        self, principal_id: str, batch_id: UUID, sequence: int
    ):
        async def events():
            yield StreamEvent(
                sequence=sequence + 1,
                event="completed",
                batch_id=batch_id,
                payload={"status": "ready"},
            )

        return events()

    async def start_chat(self, principal_id: str, request) -> ChatRunAccepted:
        self.last_chat_principal = principal_id
        return ChatRunAccepted(
            run_id="chat-run-1",
            session_id="chat-session-1",
            target=request.target,
        )

    async def chat_events(self, principal_id: str, run_id: str, sequence: int):
        async def events():
            yield StreamEvent(
                sequence=sequence + 1,
                event="text.delta",
                run_id=run_id,
                payload={"delta": "Bună"},
            )
            yield StreamEvent(
                sequence=sequence + 2,
                event="completed",
                run_id=run_id,
                payload={"output": "Bună"},
            )

        return events()

    async def cancel_chat(self, principal_id: str, run_id: str) -> dict[str, str]:
        return {"run_id": run_id, "status": "stopping"}

    async def saved_posts(self, principal_id: str) -> list[dict]:
        return [{"id": SAVED_POST_ID, "title": "Postare salvată"}]

    async def saved_post(self, principal_id: str, post_id: UUID) -> dict:
        return {"id": str(post_id), "title": "Postare salvată"}

    async def prepare_batch_save(self, principal_id: str, request) -> RunResponse:
        self.last_save_principal = principal_id
        return RunResponse(
            run_id="save-run",
            session_id="posts-save-1",
            status="pending",
            requests=[
                ToolApprovalRequest(
                    call_id="save-call",
                    tool_name="save_posts_batch",
                    arguments={
                        "variant_ids": [str(value) for value in request.variant_ids]
                    },
                )
            ],
        )

    async def prepare_post_update(
        self, principal_id: str, post_id: UUID, content
    ) -> RunResponse:
        return RunResponse(
            run_id="update-run",
            session_id="posts-update-1",
            status="pending",
            requests=[
                ToolApprovalRequest(
                    call_id="update-call",
                    tool_name="update_post",
                    arguments={"post_id": str(post_id), "title": content.title},
                )
            ],
        )


TEST_AUTH = IdentityResolver(
    AuthSettings(
        mode="development",
        harness_host="127.0.0.1",
        running_in_azure=False,
        allowed_emails=(),
        allowed_principal_ids=(),
        dev_principal_id="test-principal",
        dev_email="tester@example.com",
    )
)


class TestHarnessHttp(unittest.TestCase):
    def setUp(self) -> None:
        self._client_context = TestClient(
            create_app(FakeService, identity_resolver=TEST_AUTH)
        )
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
        self.assertIn("test-principal", response.json()["output"])

    def test_me_comes_from_the_trusted_resolver(self) -> None:
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "tester@example.com")

    def test_profile_is_structured_and_hides_update_name(self) -> None:
        response = self.client.get("/api/profile/sections")
        self.assertEqual(response.status_code, 200)
        section = response.json()["sections"][0]
        self.assertEqual(section["blocks"][0]["text"], "test-principal")
        self.assertNotIn("update_name", section)

    def test_profile_update_stops_at_the_existing_gate(self) -> None:
        response = self.client.post(
            "/api/profile/sections/brand--voice/runs",
            json={"blocks": [{"kind": "paragraph", "text": "Text nou"}]},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["requests"][0]["tool_name"], "update_profile")

    def test_generation_start_uses_trusted_identity(self) -> None:
        response = self.client.post(
            "/api/generation-batches",
            json={"format": "Reel", "pillar": "Conexiune", "source": "Memorie"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["batch"]["status"], "gathering")
        self.assertEqual(
            self.client.app.state.harness.last_generation_principal,
            "test-principal",
        )

    def test_library_and_current_batch_are_authenticated_reads(self) -> None:
        library = self.client.get("/api/library")
        current = self.client.get("/api/generation-batches/current")
        self.assertEqual(library.status_code, 200)
        self.assertEqual(library.json()["items"][0]["title"], "Carte")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["batch"]["status"], "titles_ready")

    def test_saved_posts_are_authenticated_reads(self) -> None:
        listing = self.client.get("/api/posts")
        one = self.client.get(f"/api/posts/{SAVED_POST_ID}")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["items"][0]["id"], SAVED_POST_ID)
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.json()["post"]["id"], SAVED_POST_ID)

    def test_batch_save_stops_at_the_gate_with_trusted_identity(self) -> None:
        variants = [
            "44444444-4444-4444-4444-444444444444",
            "55555555-5555-5555-5555-555555555555",
        ]

        response = self.client.post(
            "/api/posts/save-runs", json={"variant_ids": variants}
        )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["requests"][0]["tool_name"], "save_posts_batch")
        self.assertEqual(body["requests"][0]["arguments"]["variant_ids"], variants)
        self.assertEqual(
            self.client.app.state.harness.last_save_principal, "test-principal"
        )

    def test_the_same_variant_twice_never_reaches_the_service(self) -> None:
        variant = "44444444-4444-4444-4444-444444444444"

        response = self.client.post(
            "/api/posts/save-runs", json={"variant_ids": [variant, variant]}
        )

        self.assertEqual(response.status_code, 422)

    def test_a_post_rewrite_stops_at_the_gate(self) -> None:
        response = self.client.post(
            f"/api/posts/{SAVED_POST_ID}/runs", json=SAVED_POST_CONTENT
        )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["requests"][0]["tool_name"], "update_post")
        self.assertEqual(body["requests"][0]["arguments"]["post_id"], SAVED_POST_ID)

    def test_an_incomplete_rewrite_is_refused_before_any_run(self) -> None:
        incomplete = {key: value for key, value in SAVED_POST_CONTENT.items()}
        del incomplete["caption"]

        response = self.client.post(
            f"/api/posts/{SAVED_POST_ID}/runs", json=incomplete
        )

        self.assertEqual(response.status_code, 422)

    def test_a_silent_reel_rewrite_needs_no_script_or_production(self) -> None:
        """The two fields a silent reel does not have are not missing fields."""

        silent = {key: value for key, value in SAVED_POST_CONTENT.items()}
        del silent["script"]
        del silent["format_details"]

        response = self.client.post(f"/api/posts/{SAVED_POST_ID}/runs", json=silent)

        self.assertEqual(response.status_code, 202)

    def test_generation_events_use_the_sse_wire_contract(self) -> None:
        batch_id = "22222222-2222-2222-2222-222222222222"
        response = self.client.get(
            f"/api/generation-batches/{batch_id}/events",
            headers={"Last-Event-ID": "4"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
        self.assertIn("id: 5\nevent: completed\n", response.text)

    def test_chat_start_binds_the_trusted_identity_and_typed_target(self) -> None:
        response = self.client.post(
            "/api/chat/runs",
            json={
                "message": "Scurtează hook-ul",
                "target": {
                    "kind": "generation_variant",
                    "id": "33333333-3333-3333-3333-333333333333",
                },
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["run_id"], "chat-run-1")
        self.assertEqual(
            self.client.app.state.harness.last_chat_principal,
            "test-principal",
        )

    def test_chat_stream_replays_from_last_event_id(self) -> None:
        response = self.client.get(
            "/api/runs/chat-run-1/events", headers={"Last-Event-ID": "8"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("id: 9\nevent: text.delta\n", response.text)
        self.assertIn('"delta":"Bună"', response.text)

    def test_chat_cancel_is_authenticated(self) -> None:
        response = self.client.post("/api/runs/chat-run-1/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "stopping")


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
