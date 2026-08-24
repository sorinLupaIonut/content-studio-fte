"""The ten proposals sit on ten different archetypes.

WHY THIS FILE EXISTS. `propune-postari/SKILL.md` asks for ten angles that are
"realmente diferite intre ele" and admits no schema can check it. Measured on
2026-08-24, that sentence sat 3,800 tokens above the schema and batch a16a3f94
proposed delegation twice and boundaries twice. `ProposedIdeas` moves the rule
next to the field; these tests hold the shape that makes it work.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from content_studio.harness.generation import (
    ANGLE_TYPES,
    IdeaTitle,
    ProposedIdea,
    ProposedIdeas,
)


def _idea(ordinal: int, angle_type: str) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "angle_type": angle_type,
        "title": f"Titlul {ordinal}",
        "angle": f"Unghiul propunerii {ordinal}, in una-doua fraze.",
    }


def _ten(types: tuple[str, ...] | list[str]) -> dict[str, object]:
    return {"ideas": [_idea(i, t) for i, t in enumerate(types, start=1)]}


class AngleVocabulary(unittest.TestCase):
    def test_exactly_ten_archetypes(self) -> None:
        """Ten slots, ten archetypes. The count IS the mechanism.

        Eleven and two proposals may share one; nine and no valid answer exists.
        """
        self.assertEqual(len(ANGLE_TYPES), 10)
        self.assertEqual(len(set(ANGLE_TYPES)), 10)

    def test_no_archetype_collides_with_a_hook_type(self) -> None:
        """Faza 2's vocabulary and Faza 1's must not share a word."""
        from content_studio.harness.generation import HOOK_TYPES

        self.assertEqual(set(ANGLE_TYPES) & set(HOOK_TYPES), set())

    def test_the_literal_and_the_tuple_agree(self) -> None:
        """A value the schema accepts that the tuple does not know is a value
        no test covers."""
        from typing import get_args

        from content_studio.harness.generation import AngleType

        self.assertEqual(set(get_args(AngleType)), set(ANGLE_TYPES))


class TheTenAreDifferent(unittest.TestCase):
    def test_a_permutation_is_accepted(self) -> None:
        value = ProposedIdeas.model_validate(_ten(ANGLE_TYPES))
        self.assertEqual(len(value.ideas), 10)

    def test_order_of_archetypes_is_free(self) -> None:
        """The rule is one each, not one each in a fixed order."""
        shuffled = tuple(reversed(ANGLE_TYPES))
        ProposedIdeas.model_validate(_ten(shuffled))

    def test_a_repeated_archetype_is_refused(self) -> None:
        types = list(ANGLE_TYPES)
        types[7] = types[1]
        with self.assertRaises(ValidationError) as caught:
            ProposedIdeas.model_validate(_ten(types))
        self.assertIn("different angle_type", str(caught.exception))
        self.assertIn(types[1], str(caught.exception))

    def test_the_message_names_every_repeat(self) -> None:
        """One useless error message is what sent this session to the OpenAI
        API to find out why a run failed. Name the value."""
        types = list(ANGLE_TYPES)
        types[3] = types[0]
        types[8] = types[2]
        with self.assertRaises(ValidationError) as caught:
            ProposedIdeas.model_validate(_ten(types))
        message = str(caught.exception)
        self.assertIn(types[0], message)
        self.assertIn(types[2], message)

    def test_an_unknown_archetype_is_refused(self) -> None:
        types = list(ANGLE_TYPES)
        types[0] = "INVENTAT"
        with self.assertRaises(ValidationError):
            ProposedIdeas.model_validate(_ten(types))

    def test_still_exactly_ten_and_in_order(self) -> None:
        payload = _ten(ANGLE_TYPES)
        payload["ideas"][4]["ordinal"] = 9  # type: ignore[index]
        with self.assertRaises(ValidationError) as caught:
            ProposedIdeas.model_validate(payload)
        self.assertIn("exactly from 1 to 10", str(caught.exception))


class WhatReachesTheStore(unittest.TestCase):
    def test_to_titles_drops_the_archetype(self) -> None:
        """Nothing downstream reads it, so nothing downstream is given it."""
        titles = ProposedIdeas.model_validate(_ten(ANGLE_TYPES)).to_titles()
        self.assertEqual(len(titles.ideas), 10)
        for source, stored in zip(
            ProposedIdeas.model_validate(_ten(ANGLE_TYPES)).ideas,
            titles.ideas,
            strict=True,
        ):
            self.assertEqual(stored.ordinal, source.ordinal)
            self.assertEqual(stored.title, source.title)
            self.assertEqual(stored.angle, source.angle)
        self.assertFalse(hasattr(titles.ideas[0], "angle_type"))

    def test_idea_title_still_refuses_the_extra_field(self) -> None:
        """`IdeaTitle` is what Faza 2 rebuilds from the database, where no
        archetype was ever stored."""
        with self.assertRaises(ValidationError):
            IdeaTitle.model_validate(
                {"ordinal": 1, "title": "T", "angle": "U", "angle_type": "MIT"}
            )


class WhatTheModelSees(unittest.TestCase):
    def test_the_archetype_is_written_before_the_title(self) -> None:
        """Field order is writing order. Labelling after the fact is the
        behaviour this contract exists to stop."""
        fields = list(ProposedIdea.model_fields)
        self.assertLess(fields.index("angle_type"), fields.index("title"))

    def test_the_glossary_rides_on_the_field(self) -> None:
        """Attached to the property, not left in prose far above it."""
        schema = ProposedIdea.model_json_schema()
        described = schema["properties"]["angle_type"].get("description", "")
        for archetype in ANGLE_TYPES:
            self.assertIn(archetype, described)


if __name__ == "__main__":
    unittest.main()


class TheAgentAndTheCastAgree(unittest.TestCase):
    """The schema the model is given and the type it is read back as.

    `_run_agent`'s `output_type` argument only casts the result; the schema the
    provider enforces comes from the Agent's own `output_type`. Caught during
    this change: the title agent still declared `IdeaTitles` while the run
    demanded `ProposedIdeas` back — a schema with no `angle_type`, then a cast
    that requires one.
    """

    def test_the_title_agent_declares_the_proposal_contract(self) -> None:
        import inspect

        from content_studio.harness import generator

        source = inspect.getsource(generator.GenerationCoordinator._title_agent)
        self.assertIn("output_type=ProposedIdeas", source)
        self.assertNotIn("output_type=IdeaTitles", source)

    def test_the_batch_runs_the_same_contract_it_builds(self) -> None:
        import inspect

        from content_studio.harness import generator

        source = inspect.getsource(generator.GenerationCoordinator._generate)
        self.assertIn("ProposedIdeas,", source)
        self.assertIn("proposed.to_titles()", source)
