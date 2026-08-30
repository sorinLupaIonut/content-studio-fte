"""The ten phrasings, checked before any of them costs a chat turn.

Convergence compares one request said several ways, and the comparison is only
honest while all of them mean the same thing. Three ways of quietly breaking
that:

  · a phrasing that omits an axis is a DIFFERENT question. The right answer to
    it is to ask her, and asking is a longer path deservedly — so the score
    would drop for a run that behaved correctly;
  · the dictated sentence is the anchor, and it has to be BUILT from
    `dictated_batch_request`. Pasted into the manifest it becomes a second copy
    of a string AGENTS.md calls contract, and it goes stale in silence;
  · the request itself has to be one the interface can produce, or the whole set
    measures fiction.
"""

from __future__ import annotations

import json
import unittest
from typing import get_args

from content_studio.harness.conversations import dictated_batch_request
from content_studio.harness.generation import (
    FormatChoice,
    PillarChoice,
    SourceChoice,
)
from evals.path.convergence import PHRASINGS_FILE, agrees, manifest, survived


def spec() -> dict:
    return json.loads(PHRASINGS_FILE.read_text(encoding="utf-8"))


class TheAnchorIsBuiltNotCopied(unittest.TestCase):
    def test_the_dictated_sentence_comes_first(self) -> None:
        phrasings, _ = manifest()
        self.assertEqual(phrasings[0].id, "dictat")

    def test_it_is_exactly_what_the_button_sends(self) -> None:
        phrasings, request = manifest()
        self.assertEqual(
            phrasings[0].text,
            dictated_batch_request(
                format=request["format"],
                pillar=request["pillar"],
                source=request["source"],
                focus=request["focus"],
            ),
        )

    def test_the_manifest_holds_no_copy_of_it(self) -> None:
        # The whole point: if someone pastes the sentence in, this fails and
        # they are sent back to `conversations.py`.
        _, request = manifest()
        dictated = dictated_batch_request(
            format=request["format"],
            pillar=request["pillar"],
            source=request["source"],
            focus=request["focus"],
        )
        self.assertNotIn(dictated, PHRASINGS_FILE.read_text(encoding="utf-8"))


class EveryPhrasingMeansTheSameThing(unittest.TestCase):
    """All four axes present in all ten, however they are worded."""

    def setUp(self) -> None:
        self.phrasings, self.request = manifest()

    def test_ten_of_them(self) -> None:
        self.assertEqual(len(self.phrasings), 10)

    def test_ids_are_unique(self) -> None:
        ids = [p.id for p in self.phrasings]
        self.assertCountEqual(ids, set(ids))

    def test_each_one_asks_for_ten(self) -> None:
        # The count is part of the request, not decoration: "give me five" is
        # another question.
        for phrasing in self.phrasings:
            lowered = phrasing.text.lower()
            self.assertTrue(
                "10" in lowered or "zece" in lowered,
                f"{phrasing.id} nu cere zece",
            )

    def test_each_one_names_the_format_the_pillar_and_the_shelf(self) -> None:
        # Matched on stems rather than on the exact domain word, because half
        # the set is deliberately written without diacritics and one phrasing
        # describes the pillar instead of naming it.
        stems = {
            "format": ("reel",),
            "pillar": ("educa", "învețe", "invete"),
            "source": ("cărț", "cart", "bibliotec", "raft"),
            "focus": ("vinovăț", "vinovat", "vină", "vina"),
        }
        for phrasing in self.phrasings:
            lowered = phrasing.text.lower()
            for axis, options in stems.items():
                self.assertTrue(
                    any(stem in lowered for stem in options),
                    f"{phrasing.id} nu spune nimic despre {axis}",
                )


class TheRequestIsTheDomainContract(unittest.TestCase):
    def test_axis_values_are_ones_the_interface_can_send(self) -> None:
        _, request = manifest()
        self.assertIn(request["format"], get_args(FormatChoice))
        self.assertIn(request["pillar"], get_args(PillarChoice))
        self.assertIn(request["source"], get_args(SourceChoice))
        self.assertTrue(request["focus"])

    def test_the_manifest_defines_the_request_once(self) -> None:
        # No per-phrasing expectation: one definition, or two that disagree.
        for phrasing in spec()["phrasings"]:
            self.assertLessEqual(set(phrasing), {"id", "text", "why"})


class TheFocusIsJudgedAsFreeText(unittest.TestCase):
    """`survived`, and the four runs of 2026-08-30 that shaped it."""

    WANTED = "limite fără vinovăție"

    def test_her_own_wording_counts(self) -> None:
        # What `cu-voce-tare` actually recorded once. The tool asks the model
        # not to invent a focus, so this is the behaviour being requested.
        self.assertTrue(
            survived("cum să pui limite fără să te simți vinovată", self.WANTED)
        )

    def test_diacritics_do_not_decide(self) -> None:
        self.assertTrue(survived("limite fara vinovatie", self.WANTED))

    def test_a_dropped_focus_fails(self) -> None:
        # Recorded three times out of four on the same phrasing. Ten ideas on
        # Educație with no topic at all is a different batch from the one asked
        # for, so this one has to stay a failure.
        self.assertFalse(survived(None, self.WANTED))
        self.assertFalse(survived("", self.WANTED))

    def test_an_unrelated_topic_fails(self) -> None:
        self.assertFalse(survived("cum alegi anvelope de iarnă", self.WANTED))

    def test_a_stopword_alone_is_not_a_topic(self) -> None:
        # "fără" is in both strings and means nothing; without the stopword list
        # every focus on earth would pass.
        self.assertFalse(survived("fără prea multe detalii", self.WANTED))


class TheEnumAxesStayExact(unittest.TestCase):
    """Free text is judged loosely; a closed vocabulary is not."""

    REQUEST = {
        "format": "Reel",
        "pillar": "Educație",
        "source": "Cărți",
        "focus": "limite fără vinovăție",
    }

    def test_the_right_intent_agrees(self) -> None:
        ok, wrong = agrees(dict(self.REQUEST), self.REQUEST)
        self.assertTrue(ok)
        self.assertEqual(wrong, [])

    def test_a_near_miss_on_an_enum_is_a_miss(self) -> None:
        intent = {**self.REQUEST, "pillar": "Conexiune"}
        ok, wrong = agrees(intent, self.REQUEST)
        self.assertFalse(ok)
        self.assertEqual(len(wrong), 1)

    def test_no_tool_call_at_all(self) -> None:
        ok, wrong = agrees(None, self.REQUEST)
        self.assertFalse(ok)
        self.assertIn("start_generation", wrong[0])


if __name__ == "__main__":
    unittest.main()
