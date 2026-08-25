"""The CI trigger and the ruler must name the same files.

WHY THIS TEST EXISTS. `.github/workflows/evals.yml` decides WHEN the output-eval
gate runs, and `evals/output/ruler.py` decides WHAT can move a score. Those are
two hand-maintained lists describing one fact, and the failure they drift into is
silent in the worst direction: a reference moves to a new file, the ruler follows
it because `material.py` names it, and the workflow keeps watching the old path.
The gate then stops running on exactly the change that needed it - and reports
nothing at all, which reads like nothing was wrong.

Both directions are checked. A watched file with no matching path is a gate that
will not fire; a path matching no watched file is a gate that fires to prove
nothing, and a check that always passes is one people stop reading.

No network, no judge, no DeepEval import - `ruler` needs deepeval, so this skips
rather than fails when only the base dependencies are installed. That is the same
rule the gate itself follows: skipped is honest, silently passing is not.
"""

from __future__ import annotations

import fnmatch
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "evals.yml"

try:
    from evals.output.ruler import watched_files
except ImportError:  # deepeval is an optional extra
    watched_files = None  # type: ignore[assignment]


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def triggers(loaded: dict) -> dict:
    # `on:` is YAML 1.1's boolean true, which safe_load duly parses as True.
    return loaded[True] if True in loaded else loaded["on"]


def matches(path: str, pattern: str) -> bool:
    """GitHub's `**` spans directory separators; `fnmatch`'s `*` already does.

    Close enough for these patterns, and deliberately so - reimplementing
    GitHub's matcher would be a second thing to get wrong.
    """
    return fnmatch.fnmatch(path, pattern.replace("**", "*"))


needs_ruler = unittest.skipIf(watched_files is None, "deepeval not installed")


class TheTriggerCoversTheRuler(unittest.TestCase):
    def setUp(self) -> None:
        self.on = triggers(workflow())

    def test_the_workflow_parses_and_has_all_three_triggers(self) -> None:
        self.assertEqual(
            set(self.on), {"pull_request", "push", "workflow_dispatch"}
        )

    def test_no_yaml_anchors(self) -> None:
        """GitHub Actions does not resolve them - it fails to parse instead."""
        text = WORKFLOW.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotIn(" &", f" {stripped}", line)
            self.assertNotIn(" *", f" {stripped}", line)

    def test_the_two_path_lists_are_identical(self) -> None:
        """One is for PRs and one for pushes; two rules would be one bug."""
        self.assertEqual(
            self.on["pull_request"]["paths"], self.on["push"]["paths"]
        )

    @needs_ruler
    def test_every_file_the_ruler_reads_is_watched(self) -> None:
        patterns = self.on["pull_request"]["paths"]
        unwatched = [
            path
            for path in watched_files()
            if not any(matches(path, p) for p in patterns)
        ]
        self.assertEqual(
            unwatched,
            [],
            "fișiere care pot muta o notă și pe care CI nu le urmărește: "
            f"{unwatched}. Adaugă-le în .github/workflows/evals.yml.",
        )

    @needs_ruler
    def test_no_path_watches_something_that_cannot_move_a_score(self) -> None:
        """Over-triggering is cheaper than under-, and still not free.

        Every extra path spends judge calls to prove nothing changed. The
        workflow's own file is exempt: it is not read by the ruler, but a change
        to the gate should re-run the gate.
        """
        watched = watched_files()
        useless = [
            pattern
            for pattern in self.on["pull_request"]["paths"]
            if pattern != ".github/workflows/evals.yml"
            and not any(matches(path, pattern) for path in watched)
        ]
        self.assertEqual(
            useless,
            [],
            f"căi pe care nimic din riglă nu le citește: {useless}",
        )


class TheGateStepIsWiredForBothLayers(unittest.TestCase):
    def setUp(self) -> None:
        self.steps = workflow()["jobs"]["gate"]["steps"]

    def test_the_judge_key_is_passed_but_not_required(self) -> None:
        """An unset secret arrives empty, which `judge_or_none` reads as none."""
        gate = next(s for s in self.steps if s.get("name") == "The gate")
        self.assertIn("DEEPSEEK_API_KEY", gate["env"])
        self.assertNotIn("if", gate)

    def test_the_eval_extra_is_installed(self) -> None:
        run = " ".join(str(s.get("run", "")) for s in self.steps)
        self.assertIn("--extra evals", run)

    def test_romanian_output_cannot_crash_the_runner(self) -> None:
        for step in self.steps:
            if "run" in step and "python" in str(step["run"]):
                self.assertEqual(step.get("env", {}).get("PYTHONIOENCODING"), "utf-8")


if __name__ == "__main__":
    unittest.main()
