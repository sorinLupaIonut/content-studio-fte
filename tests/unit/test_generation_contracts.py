"""Free D1b tests for the structured 10 × 5 and SSE contracts."""

import inspect
import os
import unittest

from pydantic import ValidationError

from content_studio.config import GENERATION_TITLE_MODEL
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
from content_studio.harness.generator import GenerationCoordinator, describe_batch


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
#: A caption that actually clears `SILENT_REEL_CAPTION_FLOOR`. It was 427
#: characters until 2026-08-25 - named LONG and under half of what the method
#: has always asked for, which is the same blindness the floor of 200 had. A
#: fixture that would be rejected in production is not a fixture for the
#: production contract.
LONG_CAPTION = (
    "Ai spus da din nou, deși tot corpul tău spunea altceva. Nu pentru că ești "
    "slabă, ci pentru că ai învățat devreme că e mai sigur să fii de folos "
    "decât să fii tu. Prima limită nu sună a scandal: sună a „am nevoie de o "
    "zi să mă gândesc”. Atât.\n\n"
    "Se întâmplă înainte să apuci să gândești. Cineva întreabă, gura spune da, "
    "iar tu abia pe hol simți nodul. Nu e lipsă de caracter, e viteză: ai "
    "exersat răspunsul ăsta de atâtea ori încât a devenit reflex. Iar un reflex "
    "nu se repară cu hotărâre, se repară cu o secundă de întârziere pusă "
    "deliberat între întrebare și răspuns.\n\n"
    "Nu-ți trebuie un discurs. Îți trebuie o singură propoziție pe care s-o ai "
    "gata dinainte, ca să nu fii nevoită s-o inventezi tocmai când ești prinsă "
    "pe picior greșit. „Îți spun mâine dimineață.” „Verific și revin.” „Acum nu "
    "pot.” Trei cuvinte care nu supără pe nimeni și care îți cumpără exact "
    "timpul de care ai nevoie ca să știi ce vrei.\n\n"
    "Data viitoare când te trezești răspunzând înainte să respiri, oprește-te o "
    "secundă și întreabă-te ce ai fi vrut să spui de fapt. Nu ca să te "
    "pedepsești — ca să afli. Tu ce ai spus ultima oară doar ca să nu superi pe "
    "cineva?"
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

        reel = detail_prompt(
            GenerationBatchRequest(
                format="Reel", pillar="Conexiune", source="Memorie"
            ),
            idea,
        )
        carousel = detail_prompt(
            GenerationBatchRequest(
                format="Carusel", pillar="Conexiune", source="Memorie"
            ),
            idea,
        )

        self.assertIn("SILENT", reel)
        self.assertNotIn("SILENT", carousel)
        self.assertIn("`script`", carousel)

    def test_two_ideas_of_one_batch_share_everything_above_the_idea(self) -> None:
        # THE PROMPT CACHE IS A PREFIX MATCH, so a line that changes per run
        # invalidates everything under it. Until 2026-08-28 the idea sat above
        # the avatar block and the two runs below shared 841 of 11,189
        # characters. This asserts the ordering rather than the saving: the
        # avatar block, identical in all ten runs, has to fall inside the
        # common prefix.
        profile = (
            "## Avatar\n\n### Ce dureri simte?\nSpune da și apoi se simte goală.\n"
        )
        request = GenerationBatchRequest(
            format="Reel", pillar="Conexiune", source="Memorie"
        )
        first = detail_prompt(
            request, IdeaTitle(ordinal=1, title="Un titlu", angle="Un unghi"), profile
        )
        second = detail_prompt(
            request, IdeaTitle(ordinal=7, title="Alt titlu", angle="Alt unghi"), profile
        )

        shared = len(os.path.commonprefix([first, second]))
        self.assertIn("Spune da și apoi se simte goală", first)
        self.assertLess(
            first.index("Spune da și apoi se simte goală"),
            shared,
            "the avatar block must sit above the first line that differs per run",
        )
        # Everything above the idea is shared; the two part at the ordinal,
        # which is as late as this message can diverge.
        self.assertGreaterEqual(shared, first.index("The existing idea, number"))

    def test_the_idea_reaches_the_model_as_prose_and_not_as_json(self) -> None:
        # MEASURED, 2026-08-28, and it cost three runs to find. With the idea
        # serialised as JSON and sitting last - right above "answer only
        # through the structured contract" - gpt-5-mini opened a caption string and never
        # closed it: it wrote the rest of the answer as escaped JSON inside that
        # one field, then filled 200,000 characters of tabs until the 24,000
        # token ceiling. Twice out of twice. Moved back above the avatar block
        # it succeeded first try; kept last but written as prose it succeeded
        # too, which is the arrangement here - the cache keeps its prefix and
        # the model is not handed a JSON blob to mimic.
        prompt = detail_prompt(
            GenerationBatchRequest(
                format="Reel", pillar="Conexiune", source="Memorie"
            ),
            IdeaTitle(ordinal=4, title="Un titlu", angle="Un unghi"),
        )
        self.assertIn("The existing idea, number 4: Un titlu", prompt)
        self.assertIn("Its angle: Un unghi", prompt)
        self.assertNotIn('{"ordinal"', prompt)
        self.assertNotIn("idea_ordinal\":", prompt)


class TestGenerationContracts(unittest.TestCase):
    def test_accepts_exactly_ten_ordered_titles(self) -> None:
        result = IdeaTitles(ideas=titles())
        self.assertEqual(len(result.ideas), 10)

    def test_rejects_nine_titles(self) -> None:
        with self.assertRaises(ValidationError):
            IdeaTitles(ideas=titles(9))

    def test_a_shuffle_is_honoured_not_refused(self) -> None:
        """Ordinals that are a real 1..10 express an order; it is obeyed."""
        values = titles()
        values[0], values[1] = values[1], values[0]
        first, second = values[0].title, values[1].title

        result = IdeaTitles(ideas=values)

        self.assertEqual([idea.ordinal for idea in result.ideas], list(range(1, 11)))
        # Idea 1 was second in the list and goes back to the front.
        self.assertEqual(result.ideas[0].title, second)
        self.assertEqual(result.ideas[1].title, first)

    def test_still_exactly_ten(self) -> None:
        """Relaxing the ORDER must not have relaxed the count."""
        with self.assertRaises(ValidationError):
            IdeaTitles(ideas=titles(11))

    def test_accepts_exactly_the_five_hook_types(self) -> None:
        result = IdeaDetails(
            idea_ordinal=1,
            title="O idee completă",
            variants=[variant(name) for name in HOOK_TYPES],
        )
        self.assertEqual([v.hook_type for v in result.variants], list(HOOK_TYPES))

    def test_rejects_duplicate_hook_type(self) -> None:
        """A repeat is a worse answer, not an untidy one. This still refuses."""
        values = [variant(name) for name in HOOK_TYPES]
        values[-1] = variant("PROVOCARE")
        with self.assertRaises(ValidationError) as caught:
            IdeaDetails(idea_ordinal=1, title="O idee completă", variants=values)
        message = str(caught.exception)
        # The refusal names what went wrong, so a retry is told something.
        self.assertIn("PROVOCARE", message)
        self.assertIn("CONTRAST", message)

    def test_the_five_hooks_in_any_order_are_arranged_not_refused(self) -> None:
        """Tab order is this code's to impose, and it costs a run to demand it.

        All five present, each once, every one of them written and paid for -
        arriving in a different order than the tabs are drawn. Until 2026-08-31
        that raised and the whole idea was lost.
        """
        shuffled = list(reversed(HOOK_TYPES))
        result = IdeaDetails(
            idea_ordinal=1,
            title="O idee completă",
            variants=[variant(name) for name in shuffled],
        )
        self.assertEqual([v.hook_type for v in result.variants], list(HOOK_TYPES))

    def test_a_missing_hook_type_is_still_refused(self) -> None:
        values = [variant(name) for name in HOOK_TYPES]
        values[2] = variant(HOOK_TYPES[0])
        with self.assertRaises(ValidationError):
            IdeaDetails(idea_ordinal=1, title="O idee completă", variants=values)

    def test_sse_has_event_id_type_and_json_data(self) -> None:
        encoded = encode_sse(
            StreamEvent(sequence=7, event="text.delta", payload={"delta": "Bună"})
        )
        self.assertTrue(encoded.startswith("id: 7\nevent: text.delta\ndata: "))
        self.assertTrue(encoded.endswith("\n\n"))
        self.assertIn('"delta":"Bună"', encoded)

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

        # It used to look for the marker lines "MOD UI STRUCTURAT D1B - TITLURI"
        # and "- DETALII". Those went on 2026-08-24: the structured contract
        # already makes their content unviolable, so what is left to check is
        # that each prompt names its own skill and carries its own payload.
        titles = title_prompt(request)
        self.assertIn("propune-postari", titles)
        self.assertNotIn("dezvolta-postarea", titles)
        # The titles run must not receive an idea to develop; that is phase 2.
        self.assertNotIn("O limită blândă", titles)

        details = detail_prompt(request, idea)
        self.assertIn("dezvolta-postarea", details)
        self.assertNotIn("propune-postari", details)
        self.assertIn("O limită blândă", details)


class TestTheBatchAlwaysNamesItsModel(unittest.TestCase):
    """Neither door picks a model any more, so the row must not inherit a None.

    The interface lost its picker on 2026-08-27 and the chat agent never had
    one — `start_generation` has no such parameter, deliberately. What is left
    to guarantee is that `generation_batches.model` still says who wrote the
    batch, which it can only do if the name is resolved before the insert.
    """

    def test_a_request_without_a_model_still_resolves_to_one(self) -> None:
        request = GenerationBatchRequest(
            format="Reel", pillar="Conexiune", source="Memorie"
        )
        self.assertIsNone(request.model)
        self.assertEqual(
            GenerationCoordinator._batch_model(request), GENERATION_TITLE_MODEL
        )

    def test_a_request_that_names_one_keeps_it(self) -> None:
        request = GenerationBatchRequest(
            format="Reel", pillar="Conexiune", source="Memorie", model="gpt-5-mini"
        )
        self.assertEqual(GenerationCoordinator._batch_model(request), "gpt-5-mini")

    def test_the_row_is_written_from_the_resolved_request(self) -> None:
        # A guard on the ordering, not on the value: resolving after the batch
        # exists would store the None and lose the attribution for good.
        source = inspect.getsource(GenerationCoordinator.start)
        resolved = source.index("_batch_model")
        created = source.index("drafts.create")
        self.assertLess(resolved, created)


class DescribeBatchTests(unittest.TestCase):
    """`describe_batch` runs on every batch, one line before `open_run`.

    UNTESTED UNTIL 2026-08-28, AND IT SHIPPED BROKEN. The 2026-08-27 refactor
    took `material_ids` off the request; this function still read it, so every
    batch raised `AttributeError` before the run row existed - no run, no
    traces, no spans in Phoenix, and nothing to read afterwards explaining why.
    It is one line of string building, which is exactly the kind of code that
    gets left out of a suite and then takes a whole feature down.
    """

    @staticmethod
    def _request(**kwargs):
        base = {"format": "Reel", "pillar": "Educație", "source": "Memorie"}
        return GenerationBatchRequest(**{**base, **kwargs})

    def test_it_describes_a_batch_without_a_focus(self) -> None:
        self.assertEqual(
            describe_batch(self._request()), "10 idei · Educație · Memorie · Reel"
        )

    def test_it_appends_the_focus_when_there_is_one(self) -> None:
        line = describe_batch(self._request(focus="limite fără vinovăție"))
        self.assertIn("focus: limite fără vinovăție", line)

    def test_it_reads_only_fields_the_request_actually_has(self) -> None:
        # The regression itself: every name it touches must be a real field.
        for source in ("Memorie", "Cărți", "Internet", "Combinat"):
            describe_batch(self._request(source=source, focus="o temă"))


if __name__ == "__main__":
    unittest.main()
