"""Free D1b tests for the structured 10 × 5 and SSE contracts."""

import unittest
from uuid import UUID

from pydantic import ValidationError

from content_studio.harness.generation import (
    HOOK_TYPES,
    FormatDetails,
    GenerationBatchRequest,
    IdeaDetails,
    IdeaTitle,
    IdeaTitles,
    IdeaVariant,
    StreamEvent,
    detail_prompt,
    encode_sse,
    public_batch,
    title_prompt,
)


def titles(count: int = 10) -> list[IdeaTitle]:
    return [
        IdeaTitle(ordinal=i, title=f"Ideea numărul {i}", angle=f"Unghiul numărul {i}")
        for i in range(1, count + 1)
    ]


def variant(hook_type: str) -> IdeaVariant:
    return IdeaVariant(
        hook_type=hook_type,
        hook=f"Hook {hook_type}",
        script="Un script complet.",
        caption="Un caption complet.",
        hashtags=["#limite", "#burnout", "#coaching"],
        cta="Salvează postarea.",
        source="din memorie",
        format_details=FormatDetails(
            content_blocks=["Cadru unic"],
            visual_direction="Lumină caldă, cadru apropiat.",
            duration_or_count="9 secunde",
        ),
    )


class TestGenerationContracts(unittest.TestCase):
    def test_accepts_exactly_ten_ordered_titles(self) -> None:
        result = IdeaTitles(ideas=titles())
        self.assertEqual(len(result.ideas), 10)

    def test_rejects_nine_titles(self) -> None:
        with self.assertRaises(ValidationError):
            IdeaTitles(ideas=titles(9))

    def test_rejects_out_of_order_titles(self) -> None:
        values = titles()
        values[0], values[1] = values[1], values[0]
        with self.assertRaises(ValidationError):
            IdeaTitles(ideas=values)

    def test_accepts_exactly_the_five_hook_types(self) -> None:
        result = IdeaDetails(
            idea_ordinal=1,
            title="O idee completă",
            variants=[variant(name) for name in HOOK_TYPES],
        )
        self.assertEqual([v.hook_type for v in result.variants], list(HOOK_TYPES))

    def test_rejects_duplicate_hook_type(self) -> None:
        values = [variant(name) for name in HOOK_TYPES]
        values[-1] = variant("PROVOCARE")
        with self.assertRaises(ValidationError):
            IdeaDetails(idea_ordinal=1, title="O idee completă", variants=values)

    def test_sse_has_event_id_type_and_json_data(self) -> None:
        encoded = encode_sse(
            StreamEvent(sequence=7, event="text.delta", payload={"delta": "Bună"})
        )
        self.assertTrue(encoded.startswith("id: 7\nevent: text.delta\ndata: "))
        self.assertTrue(encoded.endswith("\n\n"))
        self.assertIn('"delta":"Bună"', encoded)

    def test_material_filter_is_restricted_to_book_sources(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationBatchRequest(
                format="Reel",
                pillar="Conexiune",
                source="Memorie",
                material_ids=[UUID("11111111-1111-1111-1111-111111111111")],
            )

    def test_public_batch_hides_internal_source_and_identity(self) -> None:
        result = public_batch(
            {
                "id": "batch-1",
                "owner_principal_id": "secret-owner",
                "session_id": "secret-session",
                "source_packet": {"books": ["copyrighted excerpt"]},
                "ideas": [],
            }
        )
        self.assertEqual(result, {"id": "batch-1", "ideas": []})

    def test_prompts_keep_titles_separate_from_complete_details(self) -> None:
        request = GenerationBatchRequest(
            format="Reel", pillar="Conexiune", source="Memorie"
        )
        idea = IdeaTitle(ordinal=1, title="O limită blândă", angle="Un exemplu")
        packet = {"source": "Memorie"}

        self.assertIn("TITLURI", title_prompt(request, packet))
        details = detail_prompt(request, idea, packet)
        self.assertIn("DETALII", details)
        self.assertIn("O limită blândă", details)


if __name__ == "__main__":
    unittest.main()
