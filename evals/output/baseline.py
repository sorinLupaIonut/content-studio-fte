"""What "no worse than last time" means, and why it is not per case.

MEASURED 2026-08-25, two identical runs of the same fifteen frozen answers, same
judge, same prompts, temperature 0:

    metric              identical    largest single-case swing
    CaptionLength           5/5                        0.00
    AvatarResonance        12/15                       0.10
    Hallucination          14/15                       0.50
    BriefCompliance         9/15                       0.30

A per-case gate on those numbers would need a tolerance of 0.5 to stop flaking,
and a gate that tolerates half the scale is not a gate. The same two runs
compared on the MEAN of each metric:

    BriefCompliance      0.63 / 0.64
    Hallucination        0.97 / 1.00
    AvatarResonance      0.40 / 0.42

Drift of 0.03 at the worst. Fifteen cases average the judge's noise away, so the
mean is the stable quantity and the mean is what CI may block on. `TOLERANCE` is
three times the largest drift observed - room for a slower day, not for a real
regression.

CaptionLength is exempt and gated per case, because it is arithmetic: five out of
five identical is not luck, it is what a character count does.

WHAT THIS GATE IS NOT. It does not say the writing is good. Today's baseline
records AvatarResonance at 0.40 with every case below its own threshold - the
gate holds that line so a change cannot quietly make it 0.20, and the `open`
list is what says it should be 0.80. Green here means "no worse", never "well".
"""

from __future__ import annotations

import statistics
from typing import Any

#: Three times the largest mean-drift seen between two identical runs.
TOLERANCE = 0.10

#: Metrics that need no tolerance because they involve no model.
DETERMINISTIC = frozenset({"CaptionLength"})


def summarise(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """One run's findings, in the shape a baseline is stored in.

    Per-metric means for everything, plus per-case scores for the deterministic
    metrics only - storing per-case judge scores would invite someone to gate on
    them later, which is the mistake this module exists to prevent.
    """
    by_metric: dict[str, list[float]] = {}
    per_case: dict[str, dict[str, float]] = {}
    for finding in findings:
        score = finding.get("score")
        if score is None:
            continue
        metric = finding["metric"]
        by_metric.setdefault(metric, []).append(float(score))
        if metric in DETERMINISTIC:
            per_case.setdefault(finding["case"], {})[metric] = float(score)

    metrics = {
        name: {
            "mean": round(statistics.mean(scores), 3),
            "n": len(scores),
            "passed": sum(
                1
                for f in findings
                if f["metric"] == name and f.get("passed")
            ),
        }
        for name, scores in by_metric.items()
    }
    return {"metrics": metrics, "per_case": per_case}


def open_work(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every (case, metric) still under its own threshold.

    Recorded rather than gated on. These are the repairs the set exists to prove
    were made: when the caption floor is raised and the rules re-attached, this
    list is what shrinks, and shrinking it is the only evidence that counts.
    """
    return [
        {"case": f["case"], "metric": f["metric"], "score": f.get("score")}
        for f in findings
        if not f.get("passed")
    ]


def regressions(
    baseline: dict[str, Any], findings: list[dict[str, Any]]
) -> list[str]:
    """What got worse. Empty means the gate opens.

    A metric missing from the run is a regression too - a judged metric that
    silently stopped running would otherwise read as "nothing got worse", which
    is exactly the shape of a green suite measuring nothing.
    """
    current = summarise(findings)
    faults: list[str] = []

    for name, was in (baseline.get("metrics") or {}).items():
        now = current["metrics"].get(name)
        if now is None:
            faults.append(f"{name}: nu a rulat deloc (referință {was['mean']:.2f})")
            continue
        allowed = 0.0 if name in DETERMINISTIC else TOLERANCE
        if now["mean"] < was["mean"] - allowed:
            faults.append(
                f"{name}: media {now['mean']:.2f} sub referința "
                f"{was['mean']:.2f} (toleranță {allowed:.2f})"
            )

    for case, expected in (baseline.get("per_case") or {}).items():
        for name, was_score in expected.items():
            got = current["per_case"].get(case, {}).get(name)
            if got is None:
                faults.append(f"{name} @ {case}: cazul nu a fost notat")
            elif got < was_score:
                faults.append(
                    f"{name} @ {case}: {got:.2f} sub referința {was_score:.2f}"
                )

    return faults
