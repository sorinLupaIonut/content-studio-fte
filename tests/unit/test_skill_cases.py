"""The ten cases, checked before any of them costs a model call.

`evals/skill/cases.json` decides what the relevance metric is ever asked about,
and three ways of breaking it leave no trace at run time:

  · a `Memorie` case calls no search tool at all, so it would enter the run,
    produce nothing, and quietly shrink the sample without failing;
  · the axes that matter here are phase × source, and a missing pair is not a
    lower score - it is a question nobody asked;
  · the negative control is the only case with a known answer. Delete it and a
    perfect ten reads exactly like a judge that says yes to everything.
"""

from __future__ import annotations

import json
import unittest
from typing import get_args

from content_studio.harness.generation import (
    FormatChoice,
    PillarChoice,
    SourceChoice,
)
from evals.route.tool_usage import GRID_FILE

CASES_PATH = "evals/skill/cases.json"


def load() -> dict:
    with open(CASES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


class CasesCoverTheQuestion(unittest.TestCase):
    """Phase × source, three sources, and nothing that searches nothing."""

    def setUp(self) -> None:
        self.cases = load()["cases"]

    def test_ten_at_most(self) -> None:
        # Sorin's ceiling, 2026-08-30: the route spine is 24 and this is the
        # cheaper question, so it does not get to grow into a second grid.
        self.assertLessEqual(len(self.cases), 10)

    def test_ids_are_unique(self) -> None:
        ids = [c["id"] for c in self.cases]
        self.assertCountEqual(ids, set(ids))

    def test_no_memorie(self) -> None:
        # `Memorie` forbids both search tools, so a case on it yields no span to
        # grade. It is a correct route and an empty measurement.
        self.assertNotIn("Memorie", {c["source"] for c in self.cases})

    def test_every_phase_meets_every_source(self) -> None:
        pairs = {(c["phase"], c["source"]) for c in self.cases}
        for phase in ("titluri", "detalii"):
            for source in ("Cărți", "Internet", "Combinat"):
                self.assertIn((phase, source), pairs, f"{phase} × {source} is unasked")

    def test_phase_one_asks_with_and_without_a_focus(self) -> None:
        # Without a focus the only anchors left are the pillar and the avatar,
        # which is where a search that never read the profile shows itself.
        titles = [c for c in self.cases if c["phase"] == "titluri"]
        self.assertTrue(any(c["focus"] is None for c in titles))
        self.assertTrue(any(c["focus"] for c in titles))

    def test_phase_two_always_has_a_focus(self) -> None:
        # Phase 2 develops an idea; a detail run with nothing to develop is not
        # a case the interface can produce.
        for case in self.cases:
            if case["phase"] == "detalii":
                self.assertTrue(case["focus"], case["id"])


class ValuesAreTheDomainContract(unittest.TestCase):
    """Every axis value is one the interface can actually send."""

    def setUp(self) -> None:
        self.cases = load()["cases"]

    def test_formats_pillars_sources(self) -> None:
        for case in self.cases:
            self.assertIn(case["format"], get_args(FormatChoice), case["id"])
            self.assertIn(case["pillar"], get_args(PillarChoice), case["id"])
            self.assertIn(case["source"], get_args(SourceChoice), case["id"])

    def test_sources_are_the_ones_the_route_grid_knows(self) -> None:
        # Two manifests, and the day they stop agreeing is the day one of the
        # two evals is grading a source the other has never heard of.
        with open(GRID_FILE, encoding="utf-8") as handle:
            known = set(json.load(handle)["sources"])
        self.assertLessEqual({c["source"] for c in self.cases}, known)


class TheControlExists(unittest.TestCase):
    """Exactly one case with a known answer, and it is a failing one."""

    def setUp(self) -> None:
        self.cases = load()["cases"]

    def test_one_control_and_it_expects_a_failure(self) -> None:
        controls = [c for c in self.cases if "expects" in c]
        self.assertEqual(len(controls), 1, "the negative control is the whole floor")
        self.assertEqual(controls[0]["expects"], "irelevant")

    def test_the_control_is_off_avatar_and_says_why(self) -> None:
        control = next(c for c in self.cases if "expects" in c)
        self.assertTrue(control["focus"], "a control with no focus tests nothing")
        self.assertIn("why", control)


if __name__ == "__main__":
    unittest.main()
