"""A run that fails still spent the money, and the budget has to see it.

The bug this holds: metering lived only after `Runner.run` returned, so every
run that raised left no `usage_events` row while the provider had already been
paid. Measured on 2026-08-24 against `public.traces`, which records spans
whether or not the run survived - a nano batch consumed $0.0195 and recorded
$0.0061; the mini batch beside it consumed $0.1019 and recorded $0.0770.

The gap scales with the failure rate, which is backwards for a gate meant to
stop runaway spending: the worse an account behaves, the less of it is visible.

The first fix read `exception.run_data` and did NOT work, which is why the test
below fakes a redacted exception rather than a populated one. For a structured
output failure the SDK takes its redaction branch (`agents/run.py`,
`raise redacted_error from None`) and detaches `run_data` before any caller sees
it. The hooks hold the context instead, and the hook runs before anything can
fail.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError

from content_studio.harness import generator as G


def usage(input_tokens: int = 26_000, output_tokens: int = 900) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=20_000),
    )


class RecordingAccounts:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, int | None]] = []

    async def record_run(self, kind, model, result) -> None:
        found = getattr(getattr(result, "context_wrapper", None), "usage", None)
        self.rows.append((kind, model, getattr(found, "input_tokens", None)))


def coordinator(accounts) -> G.GenerationCoordinator:
    coord = G.GenerationCoordinator.__new__(G.GenerationCoordinator)
    coord._accounts = accounts
    return coord


def failing_run(exc: BaseException, context):
    """Stand in for `Runner.run`: call the hooks, then fail like the SDK does."""

    async def run(agent, prompt, *, run_config, max_turns, hooks):  # noqa: ARG001
        await hooks.on_llm_end(context, agent, None)
        raise exc

    return run


class TestFailedRunsAreMetered(unittest.TestCase):
    def _run(self, exc: BaseException) -> RecordingAccounts:
        accounts = RecordingAccounts()
        coord = coordinator(accounts)
        context = SimpleNamespace(usage=usage())
        agent = SimpleNamespace(model="gpt-5-nano")

        async def go() -> None:
            with patch.object(G.Runner, "run", failing_run(exc, context)):
                with self.assertRaises(type(exc)):
                    await coord._run_agent(
                        agent, "p", dict, "lot-idea-3-attempt-1", "lot"
                    )

        asyncio.run(go())
        return accounts

    def test_structured_output_failure_is_metered(self) -> None:
        # `run_data` absent on purpose: this is the redaction branch, and the
        # shape that defeated the first fix.
        exc = ModelBehaviorError("Invalid JSON when parsing model output")
        exc.run_data = None
        rows = self._run(exc).rows
        self.assertEqual(rows, [("lot-idea-3-attempt-1", "gpt-5-nano", 26_000)])

    def test_turn_limit_is_metered(self) -> None:
        exc = MaxTurnsExceeded("Max turns exceeded")
        exc.run_data = None
        self.assertEqual(len(self._run(exc).rows), 1)

    def test_cancellation_is_metered(self) -> None:
        # BaseException, not Exception - a cancelled batch spent its tokens too.
        self.assertEqual(len(self._run(asyncio.CancelledError()).rows), 1)

    def test_nothing_is_charged_when_no_model_call_happened(self) -> None:
        # An exception before the first response has nothing to charge, and
        # inventing a row would be worse than the gap it fills.
        accounts = RecordingAccounts()
        coord = coordinator(accounts)

        async def run(agent, prompt, *, run_config, max_turns, hooks):  # noqa: ARG001
            raise ModelBehaviorError("died before the first call")

        async def go() -> None:
            with patch.object(G.Runner, "run", run):
                with self.assertRaises(ModelBehaviorError):
                    await coord._run_agent(
                        SimpleNamespace(model="gpt-5-nano"), "p", dict, "l", "g"
                    )

        asyncio.run(go())
        self.assertEqual(accounts.rows, [])


if __name__ == "__main__":
    unittest.main()
