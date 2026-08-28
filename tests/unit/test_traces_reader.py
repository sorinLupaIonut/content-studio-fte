"""The one reader every grader shares, tested on fabricated spans.

No database and no network: `build_runs` is pure on purpose, so the shapes that
actually arrive can be pinned here rather than discovered during a grading run.
Every shape below was taken from a real `public.traces` payload on 2026-08-24.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from evals.runs.traces import (
    RETRIEVAL_TOOL,
    GradedRun,
    ToolCall,
    attach_batches,
    build_runs,
)

NOW = datetime(2026, 8, 24, 17, 0, tzinfo=UTC)


def _run_row(run_id: str = "run-1", **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": run_id,
        "session_id": "sesiune",
        "input_message": "vreau un reel pe educație",
        "output_message": "zece propuneri",
        "status": "completed",
        "created_at": NOW,
    }
    row.update(over)
    return row


def _span(run_id: str = "run-1", **over: object) -> dict[str, object]:
    span = {
        "run_id": run_id,
        "span_type": "function",
        "name": "propune-postari",
        "input": "{}",
        "output": "corpul metodei",
        "response_id": None,
        "usage": None,
        "error": None,
        "created_at": NOW,
    }
    span.update(over)
    return span


class ToolCallsSurvive(unittest.TestCase):
    def test_a_call_keeps_both_ends(self) -> None:
        """The output is the half a trace usually loses, and the half
        `attribution` cannot work without."""
        runs = build_runs([_run_row()], [_span()])
        self.assertEqual(len(runs), 1)
        call = runs[0].tool_calls[0]
        self.assertEqual(call.name, "propune-postari")
        self.assertEqual(call.output, "corpul metodei")

    def test_calls_stay_in_the_order_they_happened(self) -> None:
        spans = [
            _span(name="propune-postari"),
            _span(name="citeste-referinta"),
            _span(name=RETRIEVAL_TOOL, output="[]"),
        ]
        runs = build_runs([_run_row()], spans)
        self.assertEqual(
            runs[0].tool_names,
            ["propune-postari", "citeste-referinta", RETRIEVAL_TOOL],
        )

    def test_arguments_parse_when_they_are_json(self) -> None:
        call = ToolCall(name="x", input='{"cheie": "valoare"}', output="[]")
        self.assertEqual(call.parsed_input(), {"cheie": "valoare"})

    def test_arguments_that_are_not_json_come_back_raw(self) -> None:
        """A tool that takes no arguments records an empty string, and the
        reader must not turn that into a crash."""
        call = ToolCall(name="x", input="", output="")
        self.assertEqual(call.parsed_input(), "")


class Retrieval(unittest.TestCase):
    def test_passages_are_flattened_across_calls(self) -> None:
        spans = [
            _span(name=RETRIEVAL_TOOL, output='["pasaj A", "pasaj B"]'),
            _span(name=RETRIEVAL_TOOL, output='["pasaj C"]'),
        ]
        runs = build_runs([_run_row()], spans)
        self.assertEqual(runs[0].retrieved, ["pasaj A", "pasaj B", "pasaj C"])

    def test_searched_and_found_nothing_is_not_never_searched(self) -> None:
        """Ragas grades one and skips the other; collapsing them would hide a
        shelf that answers every question with silence."""
        runs = build_runs([_run_row()], [_span(name=RETRIEVAL_TOOL, output="[]")])
        self.assertTrue(runs[0].searched)
        self.assertEqual(runs[0].retrieved, [])

    def test_a_run_with_no_search_is_not_a_retrieval_run(self) -> None:
        runs = build_runs([_run_row()], [_span(name="propune-postari")])
        self.assertFalse(runs[0].searched)


class ModelCalls(unittest.TestCase):
    def test_response_ids_are_kept(self) -> None:
        """Neon holds the id, not the messages. The id is how a grader gets
        them back from the provider — the move this session used by hand."""
        spans = [_span(span_type="response", response_id="resp_abc", name=None)]
        runs = build_runs([_run_row()], spans)
        self.assertEqual(runs[0].response_ids, ["resp_abc"])

    def test_usage_adds_up_across_turns(self) -> None:
        spans = [
            _span(
                span_type="response",
                response_id="a",
                usage={"input_tokens": 26248, "output_tokens": 1535},
            ),
            _span(
                span_type="response",
                response_id="b",
                usage={"input_tokens": 26248, "output_tokens": 1565},
            ),
        ]
        runs = build_runs([_run_row()], spans)
        self.assertEqual(runs[0].input_tokens, 52496)
        self.assertEqual(runs[0].output_tokens, 3100)

    def test_usage_arriving_as_a_json_string_still_counts(self) -> None:
        """asyncpg hands back jsonb as a dict, but a fixture or another driver
        may not. Over-charging nothing is better than silently counting zero."""
        spans = [
            _span(
                span_type="response",
                response_id="a",
                usage='{"input_tokens": 10, "output_tokens": 2}',
            )
        ]
        runs = build_runs([_run_row()], spans)
        self.assertEqual(runs[0].input_tokens, 10)

    def test_a_failed_turn_is_counted(self) -> None:
        """19% of ideas needed a second call on 2026-08-24. A report that
        cannot see that is a report about the successes."""
        spans = [
            _span(span_type="response", response_id="a", error='{"message": "x"}'),
            _span(span_type="response", response_id="b"),
        ]
        runs = build_runs([_run_row()], spans)
        self.assertEqual(runs[0].failed_turns, 1)


class ShapesThatMustNotCrashIt(unittest.TestCase):
    def test_a_run_with_no_spans_at_all(self) -> None:
        """`close_run` writes a payload with no `spans` key, and the SQL filters
        it out — so a run can legitimately arrive bare."""
        runs = build_runs([_run_row()], [])
        self.assertEqual(runs[0].tool_calls, [])
        self.assertEqual(runs[0].input_tokens, 0)

    def test_a_span_whose_run_row_is_gone(self) -> None:
        """Possible after a partial cleanup. Dropping it beats failing the read."""
        runs = build_runs([_run_row("run-1")], [_span(run_id="run-orfan")])
        self.assertEqual(runs[0].tool_calls, [])

    def test_a_run_that_never_answered(self) -> None:
        runs = build_runs([_run_row(output_message=None)], [])
        self.assertIsNone(runs[0].output_message)

    def test_several_runs_do_not_mix_their_spans(self) -> None:
        rows = [_run_row("run-1"), _run_row("run-2")]
        spans = [
            _span("run-1", name="propune-postari"),
            _span("run-2", name="dezvolta-postarea"),
        ]
        by_id = {run.run_id: run for run in build_runs(rows, spans)}
        self.assertEqual(by_id["run-1"].tool_names, ["propune-postari"])
        self.assertEqual(by_id["run-2"].tool_names, ["dezvolta-postarea"])


class WhatTheGradersAreHanded(unittest.TestCase):
    def test_as_dict_carries_the_keys_a_report_needs(self) -> None:
        runs = build_runs([_run_row()], [_span()])
        payload = runs[0].as_dict()
        for key in (
            "run_id",
            "status",
            "input_message",
            "output_message",
            "tools",
            "retrieved",
            "searched",
            "response_ids",
        ):
            self.assertIn(key, payload)

    def test_the_reader_decides_nothing(self) -> None:
        """No score, no verdict, no threshold. Two graders disagreeing about a
        run must be disagreeing about the rubric, never about the facts."""
        for name in dir(GradedRun):
            self.assertNotIn("score", name)
            self.assertNotIn("verdict", name)


if __name__ == "__main__":
    unittest.main()


class RetrievalComesFromTheBatch(unittest.TestCase):
    """The passages are NOT a span, and assuming they were cost a rewrite.

    `collect_source_packet` calls `search_books` server-side, once per batch, and
    it runs BEFORE `Audit.open_run` — so there is no run to hang a span on.
    Measured 2026-08-25: a batch with source `Cărți` produced two runs, both with
    no tool calls, while its `source_packet` held eight passages all along.
    """

    @staticmethod
    def _batch(**over: object) -> dict[str, object]:
        row = {
            "id": "62dfb546-79b3-4fdb-8ced-4bf31c6cd2cb",
            "session_id": "generation-abc",
            "source": "Cărți",
            "format": "Reel",
            "pillar": "Conexiune",
            "source_packet": {"books": ["pasaj 1", "pasaj 2"]},
        }
        row.update(over)
        return row

    def test_a_title_run_is_matched_by_session(self) -> None:
        runs = build_runs([_run_row(session_id="generation-abc")], [])
        attach_batches(runs, [self._batch()])
        self.assertEqual(runs[0].retrieved, ["pasaj 1", "pasaj 2"])
        self.assertTrue(runs[0].searched)

    def test_a_detail_run_is_matched_by_the_id_in_its_message(self) -> None:
        """Its session is `generation-detail-...`, a different one, so the batch
        id printed into the message is the only link there is."""
        row = _run_row(
            session_id="generation-detail-zzz",
            input_message="Dezvoltă ideea 1 din lotul 62dfb546",
        )
        runs = build_runs([row], [])
        attach_batches(runs, [self._batch()])
        self.assertEqual(runs[0].batch["id"][:8], "62dfb546")
        self.assertEqual(len(runs[0].retrieved), 2)

    def test_a_memory_batch_is_not_a_retrieval_run(self) -> None:
        runs = build_runs([_run_row(session_id="generation-abc")], [])
        attach_batches(runs, [self._batch(source="Memorie", source_packet={})])
        self.assertFalse(runs[0].searched)
        self.assertEqual(runs[0].retrieved, [])

    def test_books_with_no_passages_still_counts_as_searched(self) -> None:
        """Asked the shelf and it was silent — a different fault from never
        asking, and the one worth seeing."""
        runs = build_runs([_run_row(session_id="generation-abc")], [])
        attach_batches(runs, [self._batch(source_packet={"books": []})])
        self.assertTrue(runs[0].searched)
        self.assertEqual(runs[0].retrieved, [])

    def test_a_run_matching_no_batch_keeps_none(self) -> None:
        runs = build_runs([_run_row(session_id="chat-abc")], [])
        attach_batches(runs, [self._batch()])
        self.assertIsNone(runs[0].batch)
        self.assertFalse(runs[0].searched)

    def test_a_source_packet_arriving_as_a_string_still_parses(self) -> None:
        import json as _json

        runs = build_runs([_run_row(session_id="generation-abc")], [])
        attach_batches(
            runs, [self._batch(source_packet=_json.dumps({"books": ["p"]}))]
        )
        self.assertEqual(runs[0].retrieved, ["p"])

    def test_a_chat_search_span_still_counts(self) -> None:
        """Chat has no batch, so there the span IS the door. Both are read."""
        spans = [_span(name=RETRIEVAL_TOOL, output='["din chat"]')]
        runs = build_runs([_run_row(session_id="chat-abc")], spans)
        attach_batches(runs, [])
        self.assertEqual(runs[0].retrieved, ["din chat"])
        self.assertTrue(runs[0].searched)
