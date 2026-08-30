"""The experiment's dataset and its six scores, checked before any of it runs.

`evals/experiment.py` uploads a dataset and then pays for ten generation runs
and a judge against it. Everything in here is what can go wrong for free:

  · a label that was COPIED rather than composed. The route half belongs to
    `references.json` and `tool-usage-grid.json`; a third copy in `cases.json`
    would go stale in silence and report a fault on every square it touches;
  · a witness that stopped being one. Nine cases that all expect `relevant`
    look identical whether the metric works or the judge says yes to anything;
  · a score that is a zero when it should be a skip. `search_web` not called on
    a `Cărți` run is the CORRECT route, and scoring it 0.0 would make the right
    answer look like a failed search;
  · an optimum taken over the wrong runs — the trap `path/convergence.py` fell
    into on 2026-08-30, where a run that did nothing set the floor.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from content_studio.harness.conversations import (
    dictated_batch_request,
    dictated_develop,
)
from evals.experiment import (
    CASES_FILE,
    convergence_evaluator,
    optimum,
    references,
    relevance_evaluator,
    router,
    rows,
    scores_by_run,
    tools,
)
from evals.route.tool_usage import expectation, grid


def spec() -> dict:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


class Run:
    """The shape `evaluation_runs` arrives in — a dataclass, not a dict."""

    def __init__(self, experiment_run_id: str, name: str, score: float | None) -> None:
        self.experiment_run_id = experiment_run_id
        self.name = name
        self.result = {} if score is None else {"score": score}


def ran(task_runs: list[dict], graded: list[Run]) -> dict:
    return {"task_runs": task_runs, "evaluation_runs": graded}


def passing(run_id: str) -> list[Run]:
    return [Run(run_id, name, 1.0) for name in ("router", "references", "tools")]


class TheDatasetIsTheCaseFile(unittest.TestCase):
    def test_one_row_per_case_in_order(self) -> None:
        self.assertEqual(
            [row["input"]["case"] for row in rows()],
            [case["id"] for case in spec()["cases"]],
        )

    def test_at_most_ten(self) -> None:
        # Sorin's number, 2026-08-30: 24 is the router's grid, and too many here.
        self.assertLessEqual(len(rows()), 10)

    def test_every_row_carries_the_four_axes_and_the_phase(self) -> None:
        for row in rows():
            for key in ("case", "phase", "format", "pillar", "source", "dictated"):
                self.assertTrue(row["input"].get(key), f"{row['input']['case']}: {key}")
            self.assertIn("focus", row["input"])


class TheRouteLabelIsComposedNotCopied(unittest.TestCase):
    """The one rule that keeps three manifests from becoming a fourth."""

    def test_it_matches_the_two_manifests_exactly(self) -> None:
        domain = grid()
        for row in rows():
            case = row["input"]
            wanted = expectation(domain, case["phase"], case["format"], case["source"])
            self.assertEqual(row["output"]["skill"], wanted.skill, case["case"])
            self.assertEqual(
                row["output"]["references_required"],
                list(wanted.references_required),
                case["case"],
            )
            self.assertEqual(
                row["output"]["tools_required"], list(wanted.tools_required), case["case"]
            )
            self.assertEqual(
                row["output"]["tools_forbidden"],
                list(wanted.tools_forbidden),
                case["case"],
            )

    def test_the_case_file_holds_no_route_label_of_its_own(self) -> None:
        for case in spec()["cases"]:
            self.assertEqual(
                set(case) - {"id", "phase", "format", "pillar", "source", "focus", "why"},
                set(case) & {"expects"},
                f"{case['id']} a început să țină eticheta rutei",
            )


class TheDictatedSentenceIsBuilt(unittest.TestCase):
    """AGENTS.md calls those strings contract; a copy here goes stale silently."""

    def test_phase_one_says_what_the_batch_button_says(self) -> None:
        for row in rows():
            case = row["input"]
            if case["phase"] != "titluri":
                continue
            self.assertEqual(
                case["dictated"],
                dictated_batch_request(
                    case["format"], case["pillar"], case["source"], case["focus"]
                ),
            )

    def test_phase_two_says_what_the_develop_button_says(self) -> None:
        idea = spec()["idea"]
        for row in rows():
            if row["input"]["phase"] == "detalii":
                self.assertEqual(
                    row["input"]["dictated"],
                    dictated_develop(idea["ordinal"], idea["title"]),
                )

    def test_the_case_file_holds_no_copy_of_either(self) -> None:
        raw = CASES_FILE.read_text(encoding="utf-8")
        for row in rows():
            self.assertNotIn(row["input"]["dictated"], raw)


class TheWitnessIsStillAWitness(unittest.TestCase):
    def test_exactly_one_case_expects_irrelevant(self) -> None:
        witnesses = [r for r in rows() if r["output"]["relevance"] == "irelevant"]
        self.assertEqual(len(witnesses), 1)

    def test_everything_else_expects_relevant(self) -> None:
        for row in rows():
            self.assertIn(row["output"]["relevance"], ("relevant", "irelevant"))

    def test_the_witness_can_actually_search(self) -> None:
        # A witness whose source forbids both tools would fail for having
        # nothing to judge, which proves nothing about the avatar.
        witness = next(r for r in rows() if r["output"]["relevance"] == "irelevant")
        self.assertTrue(
            witness["output"]["tools_required"] or witness["output"]["tools_any_of"]
        )


class TheRouteScores(unittest.TestCase):
    EXPECTED = {
        "skill": "propune-postari",
        "references_required": ["propune-postari/piloni.md"],
        "references_forbidden": ["dezvolta-postarea/reel.md"],
        "tools_required": ["search_books"],
        "tools_any_of": [],
        "tools_forbidden": ["search_web"],
    }

    def good(self, **over) -> dict:
        return {
            "skills": ["propune-postari"],
            "references": ["propune-postari/piloni.md"],
            "tools": ["search_books"],
            "error": None,
            **over,
        }

    def test_a_correct_route_scores_one_on_all_three(self) -> None:
        for scorer in (router, references, tools):
            self.assertEqual(scorer(output=self.good(), expected=self.EXPECTED)["score"], 1.0)

    def test_the_wrong_skill_fails_the_router(self) -> None:
        wrong = self.good(skills=["dezvolta-postarea"])
        self.assertEqual(router(output=wrong, expected=self.EXPECTED)["score"], 0.0)

    def test_a_forbidden_reference_fails_the_references(self) -> None:
        wrong = self.good(references=["propune-postari/piloni.md", "dezvolta-postarea/reel.md"])
        self.assertEqual(references(output=wrong, expected=self.EXPECTED)["score"], 0.0)

    def test_the_other_sources_tool_fails_the_tools(self) -> None:
        wrong = self.good(tools=["search_books", "search_web"])
        self.assertEqual(tools(output=wrong, expected=self.EXPECTED)["score"], 0.0)

    def test_any_of_needs_at_least_one(self) -> None:
        loose = {**self.EXPECTED, "tools_required": [], "tools_forbidden": [],
                 "tools_any_of": ["search_books", "search_web"]}
        self.assertEqual(tools(output=self.good(tools=[]), expected=loose)["score"], 0.0)
        self.assertEqual(tools(output=self.good(), expected=loose)["score"], 1.0)

    def test_a_failed_run_scores_zero_everywhere_and_says_why(self) -> None:
        dead = self.good(error="TimeoutError: ")
        for scorer in (router, references, tools):
            verdict = scorer(output=dead, expected=self.EXPECTED)
            self.assertEqual(verdict["score"], 0.0)
            self.assertIn("TimeoutError", verdict["explanation"])


class TheUncalledToolIsSkippedNotFailed(unittest.TestCase):
    """The one place a zero would be a lie."""

    def test_no_search_by_this_tool_returns_no_score(self) -> None:
        evaluator = relevance_evaluator("search_web", avatar="—")
        verdict = asyncio.run(
            evaluator(
                output={
                    "searches": [
                        {"tool": "search_books", "description": "x", "material": "y"}
                    ]
                },
                input={"format": "Reel", "pillar": "Educație", "source": "Cărți", "focus": None},
                expected={"relevance": "relevant"},
            )
        )
        # No `score` key at all: Phoenix shows a blank cell, not a failure.
        self.assertNotIn("score", verdict)
        self.assertIn("search_web", verdict["explanation"])


class TheOptimumIsTakenOverCorrectRuns(unittest.TestCase):
    """The 2026-08-30 trap, in the one place it can still be sprung."""

    def test_a_short_run_that_failed_the_route_does_not_set_the_floor(self) -> None:
        experiment = ran(
            [
                {"id": "a", "output": {"turns": 3, "case": "cheat"}},
                {"id": "b", "output": {"turns": 8, "case": "honest"}},
            ],
            # `a` is shorter and wrong; only `b` is allowed to be the optimum.
            [Run("a", "router", 0.0), Run("a", "references", 1.0), Run("a", "tools", 1.0),
             *passing("b")],
        )
        self.assertEqual(optimum(experiment), 8)

    def test_the_shortest_correct_run_wins(self) -> None:
        experiment = ran(
            [
                {"id": "a", "output": {"turns": 7, "case": "x"}},
                {"id": "b", "output": {"turns": 9, "case": "y"}},
            ],
            [*passing("a"), *passing("b")],
        )
        self.assertEqual(optimum(experiment), 7)

    def test_no_correct_run_means_no_optimum(self) -> None:
        experiment = ran(
            [{"id": "a", "output": {"turns": 5, "case": "x"}}],
            [Run("a", "router", 0.0), Run("a", "references", 1.0), Run("a", "tools", 1.0)],
        )
        self.assertIsNone(optimum(experiment))

    def test_a_run_with_no_turns_is_not_an_optimum(self) -> None:
        experiment = ran([{"id": "a", "output": {"turns": 0, "case": "x"}}], passing("a"))
        self.assertIsNone(optimum(experiment))

    def test_scores_are_read_off_the_dataclass_shape(self) -> None:
        self.assertEqual(
            scores_by_run(ran([], [Run("a", "router", 1.0), Run("a", "tools", 0.0)])),
            {"a": {"router": 1.0, "tools": 0.0}},
        )


class TheConvergenceScore(unittest.TestCase):
    def test_the_optimum_scores_one(self) -> None:
        scorer = convergence_evaluator(7)
        self.assertEqual(scorer(output={"turns": 7})["score"], 1.0)

    def test_a_longer_path_scores_below_one(self) -> None:
        scorer = convergence_evaluator(7)
        self.assertEqual(scorer(output={"turns": 14})["score"], 0.5)

    def test_a_shorter_wrong_path_is_capped_at_one(self) -> None:
        # It can only be shorter than the optimum by having failed the route,
        # and 1.200 would print the worst outcome as the best.
        scorer = convergence_evaluator(7)
        self.assertEqual(scorer(output={"turns": 5})["score"], 1.0)

    def test_a_failed_run_scores_zero_and_carries_its_error(self) -> None:
        scorer = convergence_evaluator(7)
        verdict = scorer(output={"turns": 0, "error": "UserError: "})
        self.assertEqual(verdict["score"], 0.0)
        self.assertIn("UserError", verdict["explanation"])


if __name__ == "__main__":
    unittest.main()
