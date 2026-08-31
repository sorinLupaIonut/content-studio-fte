"""A failure explains itself, or admits it cannot.

The bug this holds. `run_like_production.py` printed one hint under every
exception - "is `uv run content-studio-server` running?" - and on 2026-08-28
E2B blocked the team for reaching its billing limit. The MCP server was running,
had answered two requests, and both 200s were on screen directly above the hint
that said to check it. A wrong hint is read as a diagnosis, so it costs more
than no hint: it decides where the next twenty minutes are spent.

Two properties matter and both are tested: the recognised failures name the
thing that has to be fixed, and an unrecognised one says so instead of guessing.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

from agents.exceptions import ModelBehaviorError

from content_studio.config import MissingConfig
from content_studio.harness.generator import safe_generation_error

CHECK = (
    Path(__file__).resolve().parents[2] / "tests" / "checks" / "paid" / "run_like_production.py"
)


def _load():
    """Import the check script by path - `tests/checks` is not a package."""
    spec = importlib.util.spec_from_file_location("run_like_production", CHECK)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SandboxException(Exception):
    """Stands in for E2B's own, which needs the client to construct."""


class DiagnosisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.diagnose = _load().diagnose

    def test_the_billing_block_is_named_as_billing_and_not_as_the_mcp_server(self) -> None:
        lines = self.diagnose(SandboxException("403: team is blocked: Billing limit reached"))
        joined = " ".join(lines)
        self.assertIn("e2b.dev", joined)
        self.assertIn("facturare", joined)
        # The regression itself: the hint that used to be printed here.
        self.assertNotIn("content-studio-server", joined)

    def test_a_refused_connection_still_points_at_the_mcp_server(self) -> None:
        lines = self.diagnose(ConnectionRefusedError("connect to 127.0.0.1:8765 refused"))
        self.assertIn("8765", " ".join(lines))

    def test_a_broken_contract_says_production_would_have_retried(self) -> None:
        lines = self.diagnose(ModelBehaviorError("Invalid JSON when parsing output"))
        self.assertIn("reincearca", " ".join(lines))

    def test_an_unknown_failure_admits_it_rather_than_guessing(self) -> None:
        lines = self.diagnose(ValueError("something nobody has seen before"))
        self.assertEqual(len(lines), 1)
        self.assertIn("nerecunoscuta", lines[0])

    def test_every_diagnosis_is_reachable_by_its_own_needles(self) -> None:
        """A needle that matches nothing is a diagnosis that never prints."""
        module = _load()
        for needles, text in module.DIAGNOSES:
            for needle in needles:
                self.assertIn(text, module.diagnose(ValueError(needle.upper())))


class ClientFacingGenerationErrorTests(unittest.TestCase):
    """The other half: what SHE reads when a batch dies.

    `safe_generation_error` falls back to the exception's class name, which is
    the right default - it is short, it is not a stack trace, and an operator can
    search for it. It was wrong for exactly one case. On 2026-08-31 the deployed
    harness had no E2B_API_KEY and the studio told its client
    `Generarea a eșuat (MissingConfig).`, which names nothing she can act on and
    invites the one thing that cannot help: pressing the button again.

    Since 2026-08-31 it returns a CODE rather than a sentence, because the value
    is stored in `generation_ideas.last_error` and the card prints that column
    verbatim - the one client-facing string with no language net in front of it.
    The wording lives in `Values.GenerationError`, which is why the last test
    here reaches across into the C# and checks that every code has some.
    """

    def test_a_missing_setting_is_named_as_configuration_not_as_a_class(self) -> None:
        code = safe_generation_error(MissingConfig("E2B_API_KEY lipseste"))
        self.assertNotIn("MissingConfig", code)
        self.assertEqual("missing_config", code)

    def test_an_unrecognised_failure_still_falls_back_to_the_class_name(self) -> None:
        self.assertEqual("failed:ValueError", safe_generation_error(ValueError("nobody knows")))

    def test_the_recognised_model_failures_keep_their_own_codes(self) -> None:
        self.assertEqual(
            "rate_limit", safe_generation_error(RuntimeError("Rate limit reached"))
        )
        self.assertEqual(
            "structured_output", safe_generation_error(ModelBehaviorError("Invalid JSON"))
        )

    def test_every_code_has_wording_waiting_for_it_in_the_interface(self) -> None:
        """The one failure splitting the sentence from its words can hide.

        `Values.GenerationError` passes an unrecognised value through unchanged.
        That is right for the rows written before the codes existed, and it is
        exactly wrong for a code added afterwards and never worded: she would
        read `max_turns` on the card and nothing would have raised.
        """
        values = (
            Path(__file__).resolve().parents[2]
            / "ui"
            / "StudioViorela"
            / "Localization"
            / "Values.cs"
        ).read_text("utf-8")
        for code in (
            "rate_limit",
            "structured_output",
            "max_turns",
            "timeout",
            "missing_config",
            "failed:",
        ):
            with self.subTest(code=code):
                self.assertIn(f'"{code}', values, f"{code} has no wording in Values.cs")


if __name__ == "__main__":
    unittest.main()


class TheRecordSaysWhy(unittest.TestCase):
    """A failed run has to carry its own message, not only its family name.

    The bug this holds, found on 2026-08-31 by trying to explain one real
    `ValueError` on a Reel run and being unable to. Every surface behaved as
    designed and the answer was still nowhere: the SDK spans carry no message,
    the audit event carries `type(e).__name__`, `generation_ideas.last_error`
    carries a code on purpose (a stored sentence cannot be reworded in her
    language later) and `runs.output_message` is deliberately NULL, that being
    the half she would read.

    `ValueError` is the family name of two completely different faults here,
    which is what made it unanswerable: pydantic's `ValidationError` is a
    SUBCLASS of `ValueError`, so "the model wrote a different title" and "the
    schema refused a field" arrive under one word.
    """

    def setUp(self) -> None:
        from content_studio.audit import Audit

        self.written: list[tuple[str, tuple]] = []
        self.events: list[str] = []
        trail = Audit.__new__(Audit)

        async def record(sql, *parameters):
            self.written.append((sql, parameters))

        async def event(run_id, kind, subject=None):
            self.events.append(f"{kind}:{subject}")

        trail._write = record
        trail.event = event
        self.trail = trail

    def failure_rows(self) -> list[dict]:
        import json

        from content_studio.audit import TRACE_SQL

        return [
            json.loads(parameters[1])["failure"]
            for sql, parameters in self.written
            if sql == TRACE_SQL and "failure" in parameters[1]
        ]

    def test_the_message_is_stored_beside_the_type(self) -> None:
        asyncio.run(self.trail.failed("run-1", ValueError("detail output changed the identity")))
        rows = self.failure_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "ValueError")
        self.assertIn("changed the identity", rows[0]["message"])

    def test_a_refused_field_is_distinguishable_from_a_changed_title(self) -> None:
        """Both are `ValueError`. Only the message separates them."""
        from pydantic import ValidationError

        from content_studio.harness.generation import IdeaVariant

        try:
            IdeaVariant(hook_type="PROVOCARE", hook="x", caption="ok", hashtags=[], cta="go")
        except ValidationError as exc:
            refused = exc
        self.assertIsInstance(refused, ValueError)
        asyncio.run(self.trail.failed("run-2", refused))
        message = self.failure_rows()[0]["message"]
        self.assertIn("hashtags", message)
        self.assertIn("hook", message)

    def test_the_run_is_still_marked_failed_and_the_event_still_written(self) -> None:
        """The diagnostic is an addition. It must not displace either of them."""
        from content_studio.audit import FAIL_RUN_SQL

        asyncio.run(self.trail.failed("run-3", RuntimeError("boom")))
        self.assertIn(FAIL_RUN_SQL, [sql for sql, _ in self.written])
        self.assertEqual(len(self.events), 1)
        self.assertIn("RuntimeError", self.events[0])

    def test_a_long_validation_error_is_truncated_not_dropped(self) -> None:
        asyncio.run(self.trail.failed("run-4", ValueError("x" * 9_000)))
        self.assertEqual(len(self.failure_rows()[0]["message"]), 4_000)

    def test_a_run_that_was_never_opened_writes_no_row(self) -> None:
        """`run_id` is None when the audit could not open the run at all."""
        asyncio.run(self.trail.failed(None, ValueError("nowhere to hang it")))
        self.assertEqual(self.failure_rows(), [])
