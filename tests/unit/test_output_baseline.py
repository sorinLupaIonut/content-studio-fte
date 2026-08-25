"""The output-eval gate's arithmetic, with no judge and no network.

`evals/output/test_output.py` is the gate itself and runs under pytest against
the frozen set; this is the ordinary unit suite, and it holds the two rules that
decide what the gate MEANS:

  - a mean below the recorded line, past tolerance, is a regression;
  - a re-record may not silently swallow one.

The second is the one worth a test. Every real edit to the method moves the
ruler, the gate then refuses to compare and prints "run --update-baseline", and
if that command accepted anything it measured, the instruction printed by a
failure would be the way to make the failure go away.
"""

from __future__ import annotations

import unittest

from evals.output.baseline import (
    DETERMINISTIC,
    TOLERANCE,
    open_work,
    regressions,
    summarise,
    worse_than,
)


def findings(**means: float) -> list[dict]:
    """Two cases per metric, both at the same score, so the mean is that score."""
    rows: list[dict] = []
    for metric, score in means.items():
        for case in ("a", "b"):
            rows.append(
                {
                    "case": case,
                    "metric": metric,
                    "score": score,
                    "passed": score >= 0.7,
                }
            )
    return rows


def baseline_of(**means: float) -> dict:
    return summarise(findings(**means))


class TheSummary(unittest.TestCase):
    def test_it_records_the_mean_and_the_count(self) -> None:
        got = summarise(findings(BriefCompliance=0.6))
        self.assertEqual(got["metrics"]["BriefCompliance"]["mean"], 0.6)
        self.assertEqual(got["metrics"]["BriefCompliance"]["n"], 2)

    def test_per_case_scores_are_kept_only_for_the_deterministic_metric(self) -> None:
        """Storing per-case judge scores would invite gating on them later.

        A single judged case swung 0.50 between two identical runs, so a
        per-case judge gate would need a tolerance of half the scale.
        """
        got = summarise(findings(CaptionLength=1.0, AvatarResonance=0.4))
        for case in got["per_case"].values():
            self.assertEqual(set(case), {"CaptionLength"})
        self.assertIn("CaptionLength", DETERMINISTIC)

    def test_a_score_that_never_arrived_is_not_averaged_in(self) -> None:
        rows = findings(Hallucination=1.0)
        rows.append({"case": "c", "metric": "Hallucination", "score": None})
        self.assertEqual(summarise(rows)["metrics"]["Hallucination"]["n"], 2)


class TheRegressionGate(unittest.TestCase):
    def test_a_drop_inside_tolerance_is_judge_noise_not_a_regression(self) -> None:
        was = baseline_of(BriefCompliance=0.60)
        now = findings(BriefCompliance=0.60 - TOLERANCE + 0.01)
        self.assertEqual(regressions(was, now), [])

    def test_a_drop_past_tolerance_is_a_regression(self) -> None:
        was = baseline_of(BriefCompliance=0.60)
        now = findings(BriefCompliance=0.40)
        self.assertEqual(len(regressions(was, now)), 1)

    def test_the_deterministic_metric_gets_no_tolerance(self) -> None:
        """It involves no model, so any drop at all is a real one."""
        was = baseline_of(CaptionLength=1.0)
        now = findings(CaptionLength=0.5)
        self.assertTrue(regressions(was, now))

    def test_a_metric_that_stopped_running_is_a_regression(self) -> None:
        """An expired judge key must not read as "nothing got worse"."""
        was = baseline_of(AvatarResonance=0.45)
        faults = regressions(was, findings(CaptionLength=1.0))
        self.assertEqual(len(faults), 1)
        self.assertIn("AvatarResonance", faults[0])


class ARerecordMayNotLaunderARegression(unittest.TestCase):
    def test_a_worse_measurement_is_reported(self) -> None:
        was = baseline_of(BriefCompliance=0.62)
        dropped = worse_than(was, findings(BriefCompliance=0.30))
        self.assertEqual(len(dropped), 1)
        self.assertIn("0.62", dropped[0])
        self.assertIn("0.30", dropped[0])

    def test_an_equal_or_better_measurement_is_not(self) -> None:
        was = baseline_of(Hallucination=0.86)
        self.assertEqual(worse_than(was, findings(Hallucination=0.86)), [])
        self.assertEqual(worse_than(was, findings(Hallucination=0.95)), [])

    def test_it_uses_the_same_tolerance_the_gate_blocks_on(self) -> None:
        """Two numbers here would eventually disagree with each other."""
        was = baseline_of(AvatarResonance=0.50)
        inside = findings(AvatarResonance=0.50 - TOLERANCE + 0.01)
        outside = findings(AvatarResonance=0.50 - TOLERANCE - 0.01)
        self.assertEqual(worse_than(was, inside), [])
        self.assertTrue(worse_than(was, outside))

    def test_a_metric_missing_from_the_run_is_not_called_worse(self) -> None:
        """`regressions` calls that a fault; here it would block a re-record.

        The two questions differ: CI must refuse to certify a metric that did
        not run, while a person re-recording without a judge key is doing
        exactly what the suite tells them they may.
        """
        was = baseline_of(Hallucination=0.86)
        self.assertEqual(worse_than(was, findings(CaptionLength=1.0)), [])

    def test_the_first_ever_baseline_has_nothing_to_be_worse_than(self) -> None:
        self.assertEqual(worse_than({}, findings(BriefCompliance=0.10)), [])


class TheOpenList(unittest.TestCase):
    def test_it_records_every_pair_under_threshold(self) -> None:
        rows = findings(AvatarResonance=0.4) + findings(Hallucination=1.0)
        under = open_work(rows)
        self.assertEqual(len(under), 2)
        self.assertEqual({o["metric"] for o in under}, {"AvatarResonance"})


if __name__ == "__main__":
    unittest.main()
