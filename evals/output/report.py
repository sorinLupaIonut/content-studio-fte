"""The same four metrics, read as numbers instead of as pass/fail.

    uv run python -m evals.output.report
    uv run python -m evals.output.report --only CaptionLength   # gratis
    uv run python -m evals.output.report --case 0e2dbc8c-i05-CIFRA

`pytest` answers "may this merge". This answers "what is the state of the
writing", which is a different question and the one worth asking while the
metrics are still being tuned: a suite that is 45 red lines tells you nothing
about whether the scores are 0.68 or 0.05, and those two mean opposite things
about whether the threshold or the text is wrong.

Writes `evals/reports/output-YYYY-MM-DD-HHMM.json` so two runs can be compared.
The judge's reason travels with every score - a number without the fragment it
came from is not evidence.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepeval.test_case import LLMTestCase

from content_studio import enable_utf8_output
from evals.output.baseline import open_work, summarise
from evals.output.judge import judge_or_none
from evals.output.metrics import (
    CaptionLength,
    avatar_resonance,
    brief_compliance,
    hallucination,
)
from evals.output.ruler import drift, fingerprint
from evals.output.test_output import NO_PASSAGES

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden.json"
REPORTS = ROOT / "evals" / "reports"


def as_test_case(case: dict[str, Any]) -> LLMTestCase:
    return LLMTestCase(
        name=case["id"],
        input=case["input"],
        actual_output=case["actual_output"],
        context=case.get("context") or [NO_PASSAGES],
        metadata={
            "caption": case.get("caption"),
            "category": case["category"],
            **case.get("brief", {}),
        },
    )


def main() -> int:
    enable_utf8_output()
    parser = argparse.ArgumentParser(description="Score evals/golden.json.")
    parser.add_argument("--only", action="append", help="just this metric, repeatable")
    parser.add_argument("--case", help="just this case id")
    parser.add_argument("--quiet", action="store_true", help="table only, no reasons")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record this run as the line CI blocks below",
    )
    args = parser.parse_args()

    if not GOLDEN.is_file():
        print("evals/golden.json lipsește. Rulează seed_golden.py întâi.", file=sys.stderr)
        return 2
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = gold["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"Niciun caz cu id {args.case}.", file=sys.stderr)
            return 2

    # Printed before a single score, because it decides what the scores below
    # mean: measured against a moved ruler they are a fresh measurement, not a
    # comparison, and reading them as the latter is the mistake this catches.
    moved = drift((gold.get("baseline") or {}).get("ruler"), gold)
    if moved:
        print("! rigla s-a schimbat fata de referinta:")
        for line in moved:
            print(f"    {line}")
        print("  notele de mai jos NU sunt comparabile cu referinta.")
        print()

    judge = judge_or_none()
    builders: dict[str, Any] = {"CaptionLength": lambda: CaptionLength()}
    if judge is not None:
        builders["BriefCompliance"] = lambda: brief_compliance(model=judge)
        builders["Hallucination"] = lambda: hallucination(model=judge)
        builders["AvatarResonance"] = lambda: avatar_resonance(model=judge)
    else:
        print("! DEEPSEEK_API_KEY lipsește — doar CaptionLength.\n", file=sys.stderr)
    if args.only:
        builders = {k: v for k, v in builders.items() if k in args.only}

    findings: list[dict[str, Any]] = []
    for case in cases:
        test_case = as_test_case(case)
        for name, build in builders.items():
            metric = build()
            try:
                metric.measure(test_case)
            except Exception as exc:  # noqa: BLE001 - one bad case must not end the run
                findings.append(
                    {"case": case["id"], "metric": name, "score": None,
                     "passed": False, "reason": f"{type(exc).__name__}: {exc}"}
                )
                continue
            if getattr(metric, "skipped", False):
                continue
            score = float(metric.score)
            findings.append({
                "case": case["id"],
                "metric": name,
                "score": round(score, 3),
                "threshold": metric.threshold,
                "passed": score >= metric.threshold,
                "reason": metric.reason,
            })

    by_metric: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        by_metric.setdefault(finding["metric"], []).append(finding)

    print(f"{len(cases)} cazuri · {len(builders)} metrici · {len(findings)} note\n")
    print(f"{'metrică':<18}{'trecut':>10}{'medie':>9}{'min':>8}{'max':>8}")
    print("-" * 53)
    for name in builders:
        rows = by_metric.get(name, [])
        scored = [r["score"] for r in rows if r["score"] is not None]
        if not scored:
            print(f"{name:<18}{'—':>10}")
            continue
        passed = sum(1 for r in rows if r["passed"])
        print(
            f"{name:<18}{f'{passed}/{len(rows)}':>10}"
            f"{statistics.mean(scored):>9.2f}{min(scored):>8.2f}{max(scored):>8.2f}"
        )

    if not args.quiet:
        for name in builders:
            failed = [r for r in by_metric.get(name, []) if not r["passed"]]
            if not failed:
                continue
            print(f"\n=== {name} — {len(failed)} sub prag ===")
            for row in failed[:6]:
                score = "eroare" if row["score"] is None else f"{row['score']:.2f}"
                print(f"\n  {row['case']}  ({score})")
                print(f"    {(row['reason'] or '').strip()[:400]}")
            if len(failed) > 6:
                print(f"\n  … și încă {len(failed) - 6}")

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")

    if args.update_baseline:
        if args.only or args.case:
            print(
                "\n! --update-baseline refuză o rulare parțială: ar înregistra o "
                "referință pentru metricile care n-au rulat.",
                file=sys.stderr,
            )
            return 2
        was = gold.get("baseline") or {}
        gold["baseline"] = {
            "recorded_at": stamp,
            # Recorded WITH the measurement, never separately: a fingerprint
            # written at another moment would vouch for a ruler that did not
            # produce these numbers.
            "ruler": fingerprint(gold),
            **summarise(findings),
        }
        gold["open"] = open_work(findings)
        GOLDEN.write_text(
            json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("\nreferință actualizată în evals/golden.json:")
        for name, now in gold["baseline"]["metrics"].items():
            before = (was.get("metrics") or {}).get(name, {}).get("mean")
            move = "  (nou)" if before is None else f"  ({before:.2f} → {now['mean']:.2f})"
            print(f"  {name:<18}{now['mean']:.2f}{move}")
        print(f"  {len(gold['open'])} perechi (caz, metrică) rămân sub prag")
        print(f"  amprenta riglei: {gold['baseline']['ruler']['id']}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"output-{stamp}.json"
    out.write_text(
        json.dumps(
            {"generated_at": stamp, "golden": str(GOLDEN.relative_to(ROOT)),
             "cases": len(cases), "findings": findings},
            ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n{out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
