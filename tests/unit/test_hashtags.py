"""The hashtag rule repairs what is unambiguous instead of refusing it.

WHY THIS FILE EXISTS. On 2026-08-24 every failed generation turn recorded in
`public.traces` was pulled back from the provider by `response_id` and
revalidated. Of 44 turns that died on a contract, 39 died on this one rule, and
none on malformed JSON. The 367 rejected values broke down as 279 missing the
`#`, 67 with a space in the middle, 21 with other whitespace — all repairable.
The refusals cost 24% of everything the project had spent.
"""

from __future__ import annotations

import re
import unittest

from pydantic import ValidationError

from content_studio.harness.generation import (
    HASHTAG_PATTERN,
    SilentReelVariant,
    checked_hashtags,
)


class RepairsTheRealFailures(unittest.TestCase):
    """Every case below was taken from a run that actually died."""

    def test_a_missing_hash_is_added(self) -> None:
        """279 of 367 — by far the commonest."""
        self.assertEqual(
            checked_hashtags(["perfecționism", "mindset", "autenticitate"]),
            ["#perfecționism", "#mindset", "#autenticitate"],
        )

    def test_an_internal_space_is_closed(self) -> None:
        """`#productivitatecu sens` is what cost idea 1 of batch a16a3f94 a
        second call."""
        self.assertEqual(
            checked_hashtags(["#productivitatecu sens", "#a", "#b"])[0],
            "#productivitatecusens",
        )

    def test_both_faults_at_once(self) -> None:
        self.assertEqual(checked_hashtags(["pași mici", "#x", "#y"])[0], "#pașimici")

    def test_other_whitespace_too(self) -> None:
        """21 of 367 were tabs and newlines, not spaces."""
        self.assertEqual(checked_hashtags(["#a\tb", "#c\nd", "#e"])[:2], ["#ab", "#cd"])

    def test_surrounding_space_still_stripped(self) -> None:
        self.assertEqual(checked_hashtags(["  #a  ", "#b", "#c"])[0], "#a")

    def test_diacritics_survive(self) -> None:
        """Instagram takes them, so the repair must not strip them."""
        self.assertEqual(checked_hashtags(["#nu fără vină", "#a", "#b"])[0], "#nufărăvină")

    def test_a_doubled_hash_becomes_one(self) -> None:
        self.assertEqual(checked_hashtags(["##dublu", "#a", "#b"])[0], "#dublu")


class StillRefusesWhatItCannotFix(unittest.TestCase):
    def test_too_few_after_repair(self) -> None:
        """Repair may collapse duplicates. Pydantic's `min_length` runs BEFORE
        this validator, so the floor is re-checked here or not at all."""
        with self.assertRaises(ValueError) as caught:
            checked_hashtags(["#acelasi", "#acela si", "acelasi"])
        self.assertIn("after repair there were 1", str(caught.exception))

    def test_the_message_shows_what_arrived(self) -> None:
        """One useless error message is what sent this session to the provider's
        API to find out why a run failed."""
        with self.assertRaises(ValueError) as caught:
            checked_hashtags(["#a", "#a", "  "])
        self.assertIn("#a", str(caught.exception))

    def test_a_value_that_repairs_to_nothing_is_dropped(self) -> None:
        with self.assertRaises(ValueError):
            checked_hashtags(["#", "   ", "##"])

    def test_more_than_five_is_still_refused(self) -> None:
        with self.assertRaises(ValueError):
            checked_hashtags(["#a", "#b", "#c", "#d", "#e", "#f"])

    def test_duplicates_collapse_rather_than_raise(self) -> None:
        """Uniqueness used to be a second raise. It is a filter now, and the
        floor is what decides whether the result is usable."""
        self.assertEqual(checked_hashtags(["#a", "#a", "#b", "#c"]), ["#a", "#b", "#c"])


class PreventionSitsInTheSchema(unittest.TestCase):
    """Repair is the net. The pattern is what stops the fall.

    Probed against the provider on 2026-08-24: asked outright for hashtags
    containing spaces, with this pattern in the schema, gpt-5-mini returned none.
    """

    def test_the_pattern_matches_what_the_repair_produces(self) -> None:
        for value in checked_hashtags(["grijade tine", "#b", "#c"]):
            self.assertRegex(value, HASHTAG_PATTERN)

    def test_the_pattern_rejects_every_shape_that_failed(self) -> None:
        for bad in ("perfecționism", "#grijade tine", "#a\tb", ""):
            self.assertIsNone(re.match(HASHTAG_PATTERN, bad))

    def test_the_pattern_reaches_the_json_schema(self) -> None:
        items = SilentReelVariant.model_json_schema()["properties"]["hashtags"]["items"]
        self.assertEqual(items["pattern"], HASHTAG_PATTERN)

    def test_it_survives_the_strict_conversion(self) -> None:
        """The SDK rewrites the schema before sending it. A constraint dropped
        there is a constraint that never reaches the provider."""
        import json

        from agents import AgentOutputSchema

        from content_studio.harness.generation import SilentReelDetails

        blob = json.dumps(
            AgentOutputSchema(SilentReelDetails, strict_json_schema=True).json_schema()
        )
        self.assertIn(HASHTAG_PATTERN.replace("\\", "\\\\"), blob)

    def test_the_pattern_is_not_a_field_constraint(self) -> None:
        """On the type it would run BEFORE the validator and refuse the very
        values the repair exists to rescue."""
        value = SilentReelVariant.model_validate(
            {
                "hook_type": "PROVOCARE",
                "hook": "hook",
                "caption": "c" * 250,
                "hashtags": ["perfecționism", "#grijade tine", "#c"],
                "cta": "cta",
                "source": "din memorie",
            }
        )
        self.assertEqual(value.hashtags, ["#perfecționism", "#grijadetine", "#c"])


class TheContractsAllUseIt(unittest.TestCase):
    def test_every_variant_shape_repairs(self) -> None:
        from content_studio.harness.generation import IdeaVariant, ProducedVariant

        for model in (IdeaVariant, ProducedVariant, SilentReelVariant):
            items = model.model_json_schema()["properties"]["hashtags"]["items"]
            self.assertEqual(
                items.get("pattern"), HASHTAG_PATTERN, f"{model.__name__} has no pattern"
            )

    def test_a_bad_hashtag_no_longer_fails_a_whole_idea(self) -> None:
        """The regression this whole file guards: one space, five variants lost."""
        with self.assertRaises(ValidationError):
            SilentReelVariant.model_validate({"hook_type": "PROVOCARE"})


if __name__ == "__main__":
    unittest.main()
