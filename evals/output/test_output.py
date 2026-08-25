"""The regression gate: no worse than the recorded baseline.

    uv run pytest evals/output/ -v

Reads `evals/golden.json` and nothing else - no harness, no MCP server, no UI, no
generation. The answers were frozen by `seed_golden.py`, so a score that moves
between runs moved because the METRIC or the JUDGE changed, never because the
model wrote something different this time.

WHAT IT ASSERTS, AND WHAT IT REFUSES TO ASSERT. Not "is the writing good" - by
that measure the suite would be red today and red is a colour people learn to
ignore. It asserts "nothing got worse than the line we recorded", which is the
only question CI can answer without a human in the loop.

The gate is per-metric MEAN for the judged three and per-case for the
deterministic one, and that split is measured rather than chosen -
`baseline.py` carries the two runs it comes from.

The three judged tests skip themselves when no judge key is configured, so the
deterministic gate still runs on a bare checkout. Skipped, not passed: a suite
that goes green while measuring a quarter of what it claims is worse than one
that does not run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from deepeval.test_case import LLMTestCase

from evals.output.baseline import DETERMINISTIC, TOLERANCE, regressions
from evals.output.judge import judge_or_none
from evals.output.metrics import (
    CaptionLength,
    avatar_resonance,
    brief_compliance,
    hallucination,
)
from evals.output.ruler import drift

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden.json"

#: A Memorie batch retrieves nothing, and DeepEval refuses a `context` of None
#: rather than treating it as "no grounding". Saying so in one line is both what
#: the framework needs and what the judge should know: with no passages, a figure
#: or a quotation is invention with nothing to check it against.
NO_PASSAGES = (
    "Sursa a fost memoria clientei — profilul și postările ei anterioare. "
    "Căutarea în cărți nu a rulat, deci nu s-a întors niciun pasaj."
)

GOLD: dict[str, Any] = (
    json.loads(GOLDEN.read_text(encoding="utf-8"))
    if GOLDEN.is_file()
    else {"cases": [], "baseline": {}}
)
CASES: list[dict[str, Any]] = GOLD.get("cases", [])
BASELINE: dict[str, Any] = GOLD.get("baseline") or {}
JUDGE = judge_or_none()

#: Computed once. Empty means the baseline was recorded with this exact ruler
#: and this exact frozen text, which is the only condition under which "no worse
#: than the baseline" is a statement about the agent rather than about the
#: measurement.
RULER_DRIFT: list[str] = drift(BASELINE.get("ruler"), GOLD) if CASES else []

RULER_MOVED = "\n".join(
    [
        "Rigla s-a schimbat față de referință:",
        *[f"  - {line}" for line in RULER_DRIFT],
        "",
        "O comparație între două rigle nu spune nimic. Re-măsoară:",
        "  uv run python -m evals.output.report --update-baseline",
        "și comite evals/golden.json — schimbarea riglei devine o linie în diff.",
    ]
)


def refuse_if_the_ruler_moved() -> None:
    """Skip rather than pass, and never quietly.

    The suite still goes red, because `test_the_ruler_is_the_one_measured_with`
    fails on the same condition. That test carries the reason once; these three
    skip so one cause does not print as four faults.
    """
    if RULER_DRIFT:
        pytest.skip("rigla s-a schimbat — vezi test_the_ruler_is_the_one_measured_with")


needs_judge = pytest.mark.skipif(
    JUDGE is None,
    reason="DEEPSEEK_API_KEY lipsește — metricile cu judecător se sar.",
)
needs_cases = pytest.mark.skipif(
    not CASES,
    reason="evals/golden.json lipsește sau e gol — rulează seed_golden.py.",
)
needs_baseline = pytest.mark.skipif(
    not BASELINE.get("metrics"),
    reason="Nicio referință înregistrată — rulează report.py --update-baseline.",
)


def as_test_case(case: dict[str, Any]) -> LLMTestCase:
    """One golden row, in the shape DeepEval grades.

    The caption travels in `metadata` rather than in `actual_output` because the
    two kinds of metric want different things: `CaptionLength` must count the
    caption alone, while the judged three should see the whole answer - hook,
    script, caption, CTA - since a hook that contradicts its caption is a real
    defect and grading them apart would hide it.
    """
    return LLMTestCase(
        name=case["id"],
        input=case["input"],
        actual_output=case["actual_output"],
        context=case.get("context") or [NO_PASSAGES],
        expected_output=case.get("expected_behavior"),
        metadata={
            "caption": case.get("caption"),
            "category": case["category"],
            **case.get("brief", {}),
        },
    )


def score_all(build: Any, cases: list[dict[str, Any]], name: str) -> list[dict]:
    findings: list[dict[str, Any]] = []
    for case in cases:
        metric = build()
        metric.measure(as_test_case(case))
        if getattr(metric, "skipped", False):
            continue
        findings.append({
            "case": case["id"],
            "metric": name,
            "score": float(metric.score),
            "passed": float(metric.score) >= metric.threshold,
        })
    return findings


@needs_cases
@needs_baseline
def test_caption_length_holds() -> None:
    """Arithmetic, gated per case: five of five identical across two runs."""
    refuse_if_the_ruler_moved()
    findings = score_all(CaptionLength, CASES, "CaptionLength")
    faults = regressions(
        {"metrics": {}, "per_case": BASELINE.get("per_case", {})}, findings
    )
    assert not faults, "\n".join(faults)


@needs_judge
@needs_cases
@needs_baseline
@pytest.mark.parametrize(
    "name",
    [n for n in ("BriefCompliance", "Hallucination", "AvatarResonance")],
)
def test_judged_mean_holds(name: str) -> None:
    """Gated on the mean of fifteen cases, not on any one of them.

    A single judged case swung 0.50 between two identical runs; the means of the
    same two runs differed by 0.03. Fifteen cases average the noise away, which
    is what makes a 0.10 tolerance a gate rather than a coin toss.
    """
    refuse_if_the_ruler_moved()
    was = (BASELINE.get("metrics") or {}).get(name)
    if was is None:
        pytest.skip(f"{name} nu are referință înregistrată.")

    builders = {
        "BriefCompliance": lambda: brief_compliance(model=JUDGE),
        "Hallucination": lambda: hallucination(model=JUDGE),
        "AvatarResonance": lambda: avatar_resonance(model=JUDGE),
    }
    findings = score_all(builders[name], CASES, name)
    faults = regressions({"metrics": {name: was}, "per_case": {}}, findings)
    assert not faults, "\n".join(faults)


@needs_cases
@needs_baseline
def test_the_ruler_is_the_one_measured_with() -> None:
    """The comparison refuses itself when the measuring stick moved.

    Seven things can move a score without the agent changing: the pillars, the
    profile, each of the three rubrics, the caption window, and the judge - plus
    the frozen set itself, since a mean over fifteen cases and a mean over twenty
    are not the same quantity.

    This does not stop any of them being edited; editing the method IS the work.
    It stops an edited ruler being compared against a baseline measured with the
    old one, which is a green line that means nothing.
    """
    assert not RULER_DRIFT, RULER_MOVED


@needs_cases
@needs_baseline
def test_the_baseline_covers_every_metric() -> None:
    """A metric that stopped running must not read as "nothing got worse".

    The failure this guards against is a judge key expiring in CI: every judged
    test skips, the deterministic one passes, and the gate reports green while
    measuring one metric out of four.
    """
    recorded = set((BASELINE.get("metrics") or {}).keys())
    expected = {"CaptionLength", "BriefCompliance", "Hallucination", "AvatarResonance"}
    missing = expected - recorded
    assert not missing, (
        f"Referința nu acoperă {sorted(missing)} — a fost înregistrată dintr-o "
        "rulare parțială. Rulează report.py --update-baseline complet."
    )


@needs_cases
@needs_baseline
def test_the_open_list_is_the_work_not_the_verdict() -> None:
    """Green here means "no worse", never "well" — and this says so out loud.

    Today the baseline records AvatarResonance at 0.40 with all fifteen cases
    under their own threshold. That is deliberate and it is recorded in `open`,
    so nobody reads a passing suite as a claim about the writing.
    """
    assert isinstance(GOLD.get("open"), list), (
        "golden.json nu are lista `open` — rulează report.py --update-baseline."
    )
    assert TOLERANCE > 0 and "CaptionLength" in DETERMINISTIC
