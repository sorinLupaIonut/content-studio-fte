"""The chat trigger scan: which tool intents a finished run hands the harness.

The scan runs on every chat turn, between the reply and the `completed` event.
What it must get right: only the trigger tools, arguments parsed, and each
call married to its own output — because the output is how a refused call is
told from an accepted one, and executing a refused intent would do exactly
what the refusal prevented.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from content_studio.harness.chat import TRIGGER_TOOLS, trigger_calls


def call(name: str, arguments: str, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_call_item",
        raw_item=SimpleNamespace(name=name, arguments=arguments, call_id=call_id),
    )


def output(call_id: str, text: str) -> SimpleNamespace:
    # Stored outputs are plain dicts on the run item, unlike calls.
    return SimpleNamespace(
        type="tool_call_output_item",
        raw_item={"type": "function_call_output", "call_id": call_id, "output": text},
    )


class TestTriggerCalls(unittest.TestCase):
    def test_the_two_trigger_tools_are_the_contract(self) -> None:
        # `select_variant` is deliberately absent: it executes whole inside the
        # data server, so there is nothing left for the harness to run.
        self.assertEqual(TRIGGER_TOOLS, {"start_generation", "develop_idea"})

    def test_calls_come_back_with_their_own_outputs(self) -> None:
        result = SimpleNamespace(
            new_items=[
                call("start_generation", '{"format": "Reel"}', "c1"),
                output("c1", '{"status": "accepted"}'),
                call("develop_idea", '{"idea": 3}', "c2"),
                output("c2", "Eroare: nu există lot."),
            ]
        )
        self.assertEqual(
            trigger_calls(result),
            [
                ("start_generation", {"format": "Reel"}, '{"status": "accepted"}'),
                ("develop_idea", {"idea": 3}, "Eroare: nu există lot."),
            ],
        )

    def test_other_tools_and_junk_are_ignored(self) -> None:
        result = SimpleNamespace(
            new_items=[
                call("search_books", '{"description": "limite"}', "c1"),
                output("c1", "[]"),
                SimpleNamespace(type="message_output_item", raw_item=None),
                call("start_generation", "not json", "c2"),
            ]
        )
        self.assertEqual(
            trigger_calls(result), [("start_generation", {}, "")]
        )

    def test_a_result_with_no_items_scans_to_nothing(self) -> None:
        self.assertEqual(trigger_calls(SimpleNamespace(new_items=None)), [])


if __name__ == "__main__":
    unittest.main()
