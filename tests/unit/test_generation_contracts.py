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
    ProducedIdeaDetails,
    ProducedVariant,
    SilentReelDetails,
    SilentReelVariant,
    StreamEvent,
    detail_output_type,
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


#: Long enough to clear the silent-reel floor, because that is the point of it.
LONG_CAPTION = (
    "Ai spus da din nou, deși tot corpul tău spunea altceva. Nu pentru că ești "
    "slabă, ci pentru că ai învățat devreme că e mai sigur să fii de folos "
    "decât să fii tu. Prima limită nu sună a scandal: sună a „am nevoie de o "
    "zi să mă gândesc”. Atât. Data viitoare când te trezești răspunzând înainte "
    "să respiri, oprește-te o secundă și întreabă-te ce ai fi vrut să spui de "
    "fapt. Tu ce ai spus ultima oară doar ca să nu superi pe cineva?"
)


def silent_variant(hook_type: str) -> SilentReelVariant:
    return SilentReelVariant(
        hook_type=hook_type,
        hook=f"Hook {hook_type}",
        caption=LONG_CAPTION,
        hashtags=["#limite", "#burnout", "#coaching"],
        cta="Salvează postarea.",
        source="din memorie",
    )


class TestSilentReelContract(unittest.TestCase):
    """A Reel is filmed mute, so it has no script and no production block."""

    def test_the_reel_contract_has_no_script_or_production_fields(self) -> None:
        fields = set(SilentReelVariant.model_fields)
        self.assertNotIn("script", fields)
        self.assertNotIn("format_details", fields)

    def test_the_reel_contract_refuses_a_script_it_was_handed(self) -> None:
        with self.assertRaises(ValidationError):
            SilentReelVariant(
                hook_type="PROVOCARE",
                hook="Hook",
                script="Un script care nu are ce căuta aici.",
                caption=LONG_CAPTION,
                hashtags=["#limite", "#burnout", "#coaching"],
                cta="Salvează postarea.",
                source="din memorie",
            )

    def test_a_two_line_caption_is_not_enough_for_a_silent_reel(self) -> None:
        with self.assertRaises(ValidationError):
            SilentReelVariant(
                hook_type="PROVOCARE",
                hook="Hook",
                caption="Două fraze. Atât.",
                hashtags=["#limite", "#burnout", "#coaching"],
                cta="Salvează postarea.",
                source="din memorie",
            )

    def test_five_silent_variants_still_cover_the_five_hooks(self) -> None:
        result = SilentReelDetails(
            idea_ordinal=1,
            title="O idee mută",
            variants=[silent_variant(name) for name in HOOK_TYPES],
        )
        self.assertEqual([v.hook_type for v in result.variants], list(HOOK_TYPES))

    def test_each_format_gets_exactly_one_contract(self) -> None:
        self.assertIs(detail_output_type("Reel"), SilentReelDetails)
        self.assertIs(detail_output_type("Carusel"), ProducedIdeaDetails)
        self.assertIs(detail_output_type("Stories"), ProducedIdeaDetails)

    def test_the_produced_contract_still_demands_both(self) -> None:
        self.assertIn("script", ProducedVariant.model_fields)
        with self.assertRaises(ValidationError):
            ProducedVariant(
                hook_type="PROVOCARE",
                hook="Hook",
                caption="Un caption scurt.",
                hashtags=["#limite", "#burnout", "#coaching"],
                cta="Salvează postarea.",
                source="din memorie",
            )

    def test_the_stored_shape_keeps_script_and_production_together(self) -> None:
        """Half a production block is the one state that means nothing."""

        stored = IdeaVariant(
            hook_type="PROVOCARE",
            hook="Hook",
            caption=LONG_CAPTION,
            hashtags=["#limite", "#burnout", "#coaching"],
            cta="Salvează postarea.",
            source="din memorie",
        )
        self.assertIsNone(stored.script)
        self.assertIsNone(stored.format_details)

        with self.assertRaises(ValidationError):
            IdeaVariant(
                hook_type="PROVOCARE",
                hook="Hook",
                script="Un script fără bloc de producție.",
                caption=LONG_CAPTION,
                hashtags=["#limite", "#burnout", "#coaching"],
                cta="Salvează postarea.",
                source="din memorie",
            )

    def test_the_reel_prompt_says_mute_and_the_carousel_prompt_does_not(self) -> None:
        idea = IdeaTitle(ordinal=1, title="O limită blândă", angle="Un exemplu")
        packet = {"source": "Memorie"}

        reel = detail_prompt(
            GenerationBatchRequest(
                format="Reel", pillar="Conexiune", source="Memorie"
            ),
            idea,
            packet,
        )
        carousel = detail_prompt(
            GenerationBatchRequest(
                format="Carusel", pillar="Conexiune", source="Memorie"
            ),
            idea,
            packet,
        )

        self.assertIn("MUTE", reel)
        self.assertNotIn("MUTE", carousel)
        self.assertIn("`script`", carousel)


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
