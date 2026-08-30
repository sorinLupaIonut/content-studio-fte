"""`calls_in` reads a turn's tool calls — and, since 2026-08-30, their results.

The two halves of one call arrive in two different shapes. The call is an object
with a `.call_id` attribute; its output is a `FunctionCallOutput`, which the SDK
declares as a TypedDict and hands over as a plain dict. Matching them by
attribute alone pairs nothing, and the failure is silent: every `result` comes
back None while every `name` and `arguments` looks right.

It stayed invisible because both readers in `src/` want the arguments —
`Audit.turn` for which post was chosen, `generator` for whether the method was
opened — and neither ever asked for the result. The first caller that did was
`evals/skill/run_cases.py`, which needs to tell a search that returned nothing
from a search that was never answered.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from content_studio.audit import calls_in


def call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    """A tool call as the SDK yields it: an object carrying `call_id`."""

    return SimpleNamespace(
        type="tool_call_item",
        raw_item=SimpleNamespace(call_id=call_id, name=name, arguments=arguments),
    )


def output(call_id: str, value: object) -> SimpleNamespace:
    """Its output, as the SDK yields it: `raw_item` is a dict, not an object."""

    return SimpleNamespace(
        type="tool_call_output_item",
        raw_item={"call_id": call_id, "type": "function_call_output", "output": str(value)},
        output=value,
    )


class ResultsComeBack(unittest.TestCase):
    def test_a_call_is_paired_with_its_output(self) -> None:
        result = SimpleNamespace(
            new_items=[
                call("c1", "search_books", '{"description": "limite"}'),
                output("c1", "[{'title': 'Set Boundaries'}]"),
            ]
        )
        (found,) = calls_in(result)
        self.assertEqual(found["name"], "search_books")
        self.assertEqual(found["arguments"], {"description": "limite"})
        self.assertEqual(found["result"], "[{'title': 'Set Boundaries'}]")

    def test_two_calls_do_not_swap_results(self) -> None:
        # Interleaved on purpose: pairing by order rather than by id would pass
        # the previous test and fail this one.
        result = SimpleNamespace(
            new_items=[
                call("c1", "search_books", "{}"),
                call("c2", "search_web", "{}"),
                output("c2", "web"),
                output("c1", "books"),
            ]
        )
        by_name = {c["name"]: c["result"] for c in calls_in(result)}
        self.assertEqual(by_name, {"search_books": "books", "search_web": "web"})

    def test_an_unanswered_call_keeps_a_none_result(self) -> None:
        # A tool that never returned is the case this whole reader exists for;
        # it must stay distinguishable from one that returned nothing useful.
        result = SimpleNamespace(new_items=[call("c1", "search_web", "{}")])
        (found,) = calls_in(result)
        self.assertIsNone(found["result"])

    def test_an_output_with_no_matching_call_is_ignored(self) -> None:
        result = SimpleNamespace(new_items=[output("ghost", "orphan")])
        self.assertEqual(calls_in(result), [])

    def test_order_is_the_order_of_the_calls(self) -> None:
        result = SimpleNamespace(
            new_items=[
                call("c1", "search_web", "{}"),
                output("c1", "a"),
                call("c2", "search_books", "{}"),
                output("c2", "b"),
            ]
        )
        self.assertEqual([c["name"] for c in calls_in(result)], ["search_web", "search_books"])


if __name__ == "__main__":
    unittest.main()
