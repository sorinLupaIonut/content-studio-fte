"""Free tests for the streamed chat envelope and target guardrails."""

import unittest
from uuid import UUID

from pydantic import ValidationError

from content_studio.harness.chat import (
    ChatTarget,
    ChatTurnOutput,
    GenerationVariantPatch,
    ReplyJsonStream,
    chat_prompt,
)
from content_studio.harness.generation import FormatDetails, IdeaVariant

VARIANT_ID = UUID("33333333-3333-3333-3333-333333333333")


def content() -> IdeaVariant:
    return IdeaVariant(
        hook_type="PROVOCARE",
        hook="Un hook complet",
        script="Un script complet.",
        caption="Un caption complet.",
        hashtags=["#unu", "#doi", "#trei"],
        cta="Salvează.",
        source="din memorie",
        format_details=FormatDetails(
            content_blocks=["Cadru"],
            visual_direction="Cadru apropiat.",
            duration_or_count="30 secunde",
        ),
    )


class TestReplyJsonStream(unittest.TestCase):
    def test_streams_only_reply_characters_across_json_chunks(self) -> None:
        stream = ReplyJsonStream()
        chunks = [
            '{"reply":"Bună',
            '\\nViorela",',
            '"patch":{"target_id":"secret"}}',
        ]

        visible = "".join(stream.feed(chunk) for chunk in chunks)

        self.assertEqual(visible, "Bună\nViorela")
        self.assertNotIn("target_id", visible)

    def test_waits_for_a_complete_unicode_escape(self) -> None:
        stream = ReplyJsonStream()
        self.assertEqual(stream.feed('{"reply":"A\\u0'), "A")
        self.assertEqual(stream.feed("21B"), "ț")


class TestChatContracts(unittest.TestCase):
    def test_general_target_rejects_an_id(self) -> None:
        with self.assertRaises(ValidationError):
            ChatTarget(kind="general", id=str(VARIANT_ID))

    def test_variant_target_requires_an_id(self) -> None:
        with self.assertRaises(ValidationError):
            ChatTarget(kind="generation_variant")

    def test_complete_patch_validates(self) -> None:
        output = ChatTurnOutput(
            reply="Am rescris varianta.",
            patch=GenerationVariantPatch(target_id=VARIANT_ID, content=content()),
        )
        self.assertEqual(output.patch.target_id, VARIANT_ID)

    def test_general_rewrite_prompt_forbids_guessing(self) -> None:
        prompt = chat_prompt("Rescrie-l", None)
        self.assertIn("do not guess", prompt)
        self.assertIn("`patch` is null", prompt)

    def test_target_prompt_contains_only_server_context(self) -> None:
        prompt = chat_prompt(
            "Fă hook-ul mai scurt",
            {"target_id": str(VARIANT_ID), "hook_type": "PROVOCARE"},
        )
        self.assertIn(str(VARIANT_ID), prompt)
        self.assertIn("COMPLET", prompt)


if __name__ == "__main__":
    unittest.main()
