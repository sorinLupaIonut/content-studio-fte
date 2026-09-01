"""The picker is offered and enforced by the server, over HTTP.

`test_model_choice.py` holds the four lists to each other. This holds the two
ROUTES to each other, because the picker is one rule asked in two places and the
whole design rests on the second one:

    GET  /api/me                 → which models to DRAW a select for
    POST /api/generation-batches → whether to HONOUR the name that comes back

A control that is not drawn is not a permission. If only the first route knew
the rule, any account could post `"model": "gpt-5"` with curl and be served at
five times the token price its allowance was sized for — and nothing would
refuse it, because `ModelChoice` would say the name is real.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from content_studio.config import GENERATION_MODELS, MODEL_CHOICE_CLIENTS
from content_studio.harness.main import create_app

# `unittest discover -s tests/unit` — the command AGENTS.md documents — imports
# each module as TOP-LEVEL, so a relative import raises before a single test
# runs, and the suite reports one error rather than a failure anyone can read.
# This works under both that and `-m unittest tests.unit.test_model_picker_http`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_harness import TEST_AUTH, FakeAccounts, FakeService  # noqa: E402

ALLOWED = MODEL_CHOICE_CLIENTS[0]
DEFAULT_MODEL = GENERATION_MODELS[0]
#: The one that has to be refused. Skips the whole module if the picker is ever
#: reduced to a single model again, rather than passing vacuously.
UPGRADED = GENERATION_MODELS[1] if len(GENERATION_MODELS) > 1 else None

BRIEF = {
    "format": "Reel",
    "pillar": "Educație",
    "source": "Memorie",
}


def app_for(slug: str | None) -> TestClient:
    """The harness, with one account bound to `slug`."""

    class Accounts(FakeAccounts):
        async def account_for(self, principal_id):
            if slug is None:
                return None
            return type(
                "Account",
                (),
                {
                    "client_slug": slug,
                    "client_name": slug,
                    "is_admin": False,
                },
            )()

    class Service(FakeService):
        def __init__(self) -> None:
            super().__init__()
            self.accounts = Accounts()
            self.started: list[dict] = []

        async def start_generation(self, principal_id, body):
            self.started.append(body.model_dump(mode="json"))
            return {"id": "batch-1", "model": body.model}

    return TestClient(create_app(Service, identity_resolver=TEST_AUTH))


@unittest.skipIf(UPGRADED is None, "only one model is offered; nothing to refuse")
class ThePickerIsOffered(unittest.TestCase):
    def test_the_client_is_offered_every_model(self) -> None:
        with app_for(ALLOWED) as client:
            models = client.get("/api/me").json()["models"]
        self.assertEqual(models, list(GENERATION_MODELS))

    def test_anybody_else_is_offered_one(self) -> None:
        with app_for("some-tester") as client:
            models = client.get("/api/me").json()["models"]
        self.assertEqual(models, [DEFAULT_MODEL])

    def test_an_unprovisioned_principal_is_offered_one(self) -> None:
        # `account_for` returns None before anyone is provisioned, and the
        # interface must not read that as "no restriction".
        with app_for(None) as client:
            models = client.get("/api/me").json()["models"]
        self.assertEqual(models, [DEFAULT_MODEL])


@unittest.skipIf(UPGRADED is None, "only one model is offered; nothing to refuse")
class ThePickerIsEnforced(unittest.TestCase):
    def test_the_client_may_ask_for_the_upgraded_model(self) -> None:
        with app_for(ALLOWED) as client:
            response = client.post(
                "/api/generation-batches", json={**BRIEF, "model": UPGRADED}
            )
        self.assertEqual(response.status_code, 202)

    def test_anybody_else_is_refused_with_a_code_the_interface_can_word(self) -> None:
        with app_for("some-tester") as client:
            response = client.post(
                "/api/generation-batches", json={**BRIEF, "model": UPGRADED}
            )
        self.assertEqual(response.status_code, 403)
        # A code, not a sentence: the client reads this page in her own
        # language, and `Copy.cs` owns the wording. See harness/errors.py.
        self.assertEqual(response.json().get("code"), "model_not_allowed")

    def test_anybody_else_may_still_ask_for_the_default(self) -> None:
        with app_for("some-tester") as client:
            response = client.post(
                "/api/generation-batches", json={**BRIEF, "model": DEFAULT_MODEL}
            )
        self.assertEqual(response.status_code, 202)

    def test_sending_no_model_is_never_refused(self) -> None:
        # What every account without a picker sends, and what the interface
        # sends when it draws no select. It must stay the quiet path.
        with app_for("some-tester") as client:
            response = client.post("/api/generation-batches", json=BRIEF)
        self.assertEqual(response.status_code, 202)

    def test_a_model_nobody_prices_is_refused_by_the_contract(self) -> None:
        # 422 rather than 403: `ModelChoice` rejects the shape before any
        # account is consulted, which is what keeps an unpriced name away from
        # `pricing.FALLBACK`.
        with app_for(ALLOWED) as client:
            response = client.post(
                "/api/generation-batches", json={**BRIEF, "model": "gpt-4o-mini"}
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
