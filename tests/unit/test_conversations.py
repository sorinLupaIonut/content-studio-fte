"""The dictated sentences and the verbatim transcript.

The composers are load-bearing in a way ordinary formatting is not: the exact
string a button produces is shown in the chat as the user's message, stored in
the agent's session, and typed back by hand when the behaviour is tested. A
changed word here is a changed conversation everywhere, so the strings are
asserted whole, not by fragment.
"""

from __future__ import annotations

import unittest

from content_studio.harness.conversations import (
    dictated_batch_request,
    dictated_develop,
    dictated_select,
    render_transcript,
    rendered_titles,
    rendered_variants,
)
from content_studio.harness.service import SESSION_ID_PATTERN
from content_studio.mcp_server.conversation_store import new_conversation_session_id


class TestDictation(unittest.TestCase):
    def test_batch_request_full(self) -> None:
        self.assertEqual(
            dictated_batch_request(
                "Reel", "Educație", "Cărți", "limite fără vinovăție"
            ),
            "Vreau 10 idei de postare: format Reel, pilon Educație, sursă Cărți."
            " Focus: limite fără vinovăție.",
        )

    def test_batch_request_minimal(self) -> None:
        # No focus: the sentence ends at the source.
        self.assertEqual(
            dictated_batch_request("Stories", "Conexiune", "Memorie"),
            "Vreau 10 idei de postare: format Stories, pilon Conexiune, "
            "sursă Memorie.",
        )

    def test_develop(self) -> None:
        self.assertEqual(
            dictated_develop(3, "Nu ești leneșă"),
            "Dezvoltă ideea 3: „Nu ești leneșă”.",
        )

    def test_select(self) -> None:
        self.assertEqual(
            dictated_select(3, "CIFRA"),
            "Aleg varianta cu hook CIFRA de la ideea 3.",
        )

    def test_rendered_titles_matches_the_skill_shape(self) -> None:
        # `propune-postari` Pasul 6 fixes the conversational shape so she can
        # say "a treia"; the dictated rendering follows the same shape.
        text = rendered_titles(
            [
                {"ordinal": 1, "title": "Titlu unu", "angle": "Unghi unu."},
                {"ordinal": 2, "title": "Titlu doi", "angle": "Unghi doi."},
            ]
        )
        self.assertIn("1. Titlu unu\n   Unghi unu.", text)
        self.assertIn("2. Titlu doi\n   Unghi doi.", text)
        self.assertTrue(text.endswith("Care propunere o dezvoltăm?"))

    def test_rendered_variants_names_each_hook(self) -> None:
        text = rendered_variants(
            3,
            "Nu ești leneșă",
            [
                {"hook_type": "PROVOCARE", "hook": "Hook unu"},
                {"hook_type": "CIFRA", "hook": "Hook doi"},
            ],
        )
        self.assertIn("ideea 3 — „Nu ești leneșă”", text)
        self.assertIn("1. PROVOCARE: Hook unu", text)
        self.assertIn("2. CIFRA: Hook doi", text)
        self.assertIn("Care variantă alegi?", text)


class TestSessionIds(unittest.TestCase):
    def test_conversation_session_id_is_a_valid_public_id(self) -> None:
        # The id crosses an HTTP header and the harness's own validator; a
        # character outside the pattern would 422 every transcript read.
        for _ in range(5):
            self.assertRegex(new_conversation_session_id(), SESSION_ID_PATTERN)


class TestTranscript(unittest.TestCase):
    def test_dialogue_is_verbatim(self) -> None:
        rows = render_transcript(
            [
                {"role": "user", "content": "Vreau 10 idei."},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Sigur, imediat."}],
                },
            ]
        )
        self.assertEqual(
            rows,
            [
                {"kind": "user", "text": "Vreau 10 idei."},
                {"kind": "assistant", "text": "Sigur, imediat."},
            ],
        )

    def test_structured_reply_shows_the_reply_and_keeps_the_raw(self) -> None:
        # The chat agent answers through `ChatTurnOutput`, so the stored item
        # is JSON. The window shows the reply; the raw document stays in
        # `detail` so nothing is lost — display convenience, not a second truth.
        raw = '{"reply": "Am rescris hook-ul.", "patch": null}'
        rows = render_transcript([{"role": "assistant", "content": raw}])
        self.assertEqual(rows[0]["text"], "Am rescris hook-ul.")
        self.assertEqual(rows[0]["detail"], raw)

    def test_wrapped_chat_turn_shows_her_words_and_keeps_the_wrapper(self) -> None:
        # `chat_prompt` binds the typed message to the verified target before
        # it reaches the session. The window shows what she typed; the whole
        # wrapper stays in `detail`, because the wrapper IS the real input.
        from content_studio.harness.chat import chat_prompt

        raw = chat_prompt("Fă hook-ul mai blând.", None)
        rows = render_transcript([{"role": "user", "content": raw}])
        self.assertEqual(rows[0]["text"], "Fă hook-ul mai blând.")
        self.assertEqual(rows[0]["detail"], raw)

    def test_tool_calls_collapse_to_one_row_with_the_output(self) -> None:
        rows = render_transcript(
            [
                {"role": "user", "content": "Caută în cărți."},
                {
                    "type": "function_call",
                    "name": "search_books",
                    "arguments": '{"description": "limite"}',
                    "call_id": "call_1",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": '{"passages": []}',
                },
            ]
        )
        self.assertEqual(len(rows), 2)
        tool = rows[1]
        self.assertEqual(tool["kind"], "tool")
        self.assertEqual(tool["name"], "search_books")
        self.assertEqual(tool["text"], '{"description": "limite"}')
        self.assertEqual(tool["detail"], '{"passages": []}')

    def test_plumbing_is_absent(self) -> None:
        # Reasoning items and unknown shapes are not dialogue; better absent
        # than mis-shown. An empty message is display noise, also absent.
        rows = render_transcript(
            [
                {"type": "reasoning", "summary": []},
                {"type": "some_future_item", "payload": "?"},
                {"role": "user", "content": "  "},
                "not-a-dict",
            ]
        )
        self.assertEqual(rows, [])

    def test_long_tool_values_are_excerpted(self) -> None:
        rows = render_transcript(
            [
                {
                    "type": "function_call",
                    "name": "search_books",
                    "arguments": "x" * 10_000,
                    "call_id": "call_1",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "y" * 10_000,
                },
            ]
        )
        self.assertEqual(len(rows[0]["text"]), 2_000)
        self.assertEqual(len(rows[0]["detail"]), 2_000)


class TheSameSentenceInEnglish(unittest.TestCase):
    """A button press is dictation, and dictation is in the language she works in.

    These were Romanian only until 2026-08-31, so pressing a button in an English
    studio wrote Romanian into the chat - `Vreau 10 idei de postare` under an
    English interface. The sentences are still contract; there are simply two of
    them per button, held to the same standard as the Romanian ones above.
    """

    def test_the_batch_request(self) -> None:
        self.assertEqual(
            dictated_batch_request("Reel", "Educație", "Memorie", language="en"),
            "I want 10 post ideas: format Reel, pillar Educație, source Memorie.",
        )

    def test_the_focus_rides_along(self) -> None:
        self.assertEqual(
            dictated_batch_request(
                "Carusel", "Conexiune", "Cărți", "burnout", language="en"
            ),
            "I want 10 post ideas: format Carusel, pillar Conexiune, "
            "source Cărți. Focus: burnout.",
        )

    def test_develop_and_select(self) -> None:
        self.assertEqual(
            dictated_develop(3, "You are not lazy", language="en"),
            "Develop idea 3: “You are not lazy”.",
        )
        self.assertEqual(
            dictated_select(3, "CIFRA", language="en"),
            "I pick the CIFRA hook variant from idea 3.",
        )

    def test_the_values_are_not_translated(self) -> None:
        """`Reel`, `Educație`, `Memorie` and the hook types are identifiers the
        tools match on. An English one is rejected by the schema."""
        sentence = dictated_batch_request(
            "Stories", "Poziționare", "Internet", language="en"
        )
        for value in ("Stories", "Poziționare", "Internet"):
            self.assertIn(value, sentence)
        self.assertIn("PROVOCARE", dictated_select(1, "PROVOCARE", language="en"))

    def test_the_readbacks_close_in_english(self) -> None:
        titles = rendered_titles(
            [{"ordinal": 1, "title": "A", "angle": "b"}], language="en"
        )
        self.assertTrue(titles.endswith("Which proposal shall we develop?"))
        variants = rendered_variants(
            2, "T", [{"hook_type": "SECRET", "hook": "h"}], language="en"
        )
        self.assertTrue(variants.startswith("The five variants for idea 2"))
        self.assertTrue(variants.endswith("is in the app."))

    def test_naming_no_language_still_gives_the_romanian_contract(self) -> None:
        """Every caller that predates the switch - the evals, the dataset builder -
        keeps the exact string it asserted before."""
        self.assertEqual(
            dictated_batch_request("Reel", "Educație", "Memorie"),
            dictated_batch_request("Reel", "Educație", "Memorie", language="ro"),
        )
        self.assertTrue(
            dictated_develop(1, "x").startswith("Dezvoltă ideea 1")
        )


if __name__ == "__main__":
    unittest.main()
