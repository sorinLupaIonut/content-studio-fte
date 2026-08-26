"""Are the metrics any good? Score work that is known to be good.

    uv run python -m evals.output.control

THE PROBLEM. `AvatarResonance` scored 0.44 across ten frozen answers and not one
reached its threshold. Two readings fit that number equally well: the model
writes generic content, or the metric cannot recognise the real thing. Nothing
inside the frozen set can tell them apart - every case in it was written by the
same model being judged.

THE CONTROL. `content/posts/` holds twenty-seven posts the client wrote and
published herself, for this avatar, under this method. They are the closest
thing to ground truth this project will ever have. Run the same three judges
over them and the ambiguity resolves:

    her posts score high  ->  the metric works; the model is generic
    her posts score low   ->  the metric is broken, and every conclusion
                              drawn from it so far is worthless

A judge that cannot recognise the work it was built to imitate is measuring
something else. This is the cheapest way to find that out, and it should have
been the first thing run rather than the eleventh.

NOT A GATE, AND NEVER PART OF ONE. Her posts are not frozen model output; they
are her content, and gating CI on them would make the client's own writing a
merge blocker. This prints a table and exits.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepeval.test_case import LLMTestCase

from content_studio import enable_utf8_output
from evals.output.judge import judge_or_none
from evals.output.metrics import (
    avatar_resonance,
    brief_compliance,
    hallucination,
)

ROOT = Path(__file__).resolve().parents[2]
POSTS = ROOT / "content" / "posts"
REPORTS = ROOT / "evals" / "reports"

#: The metadata line every post carries, e.g.
#: "> **Pilon:** Conexiune 🤝 · **Format:** Carusel 7 slide-uri … · **Data:** …"
PILLAR = re.compile(r"\*\*Pilon:\*\*\s*([A-Za-zĂÂÎȘȚăâîșț]+)")
FORMAT = re.compile(r"\*\*Format:\*\*\s*([A-Za-zĂÂÎȘȚăâîșț]+)")
IDEA = re.compile(r"\*\*Ideea:\*\*\s*(.+?)$", re.MULTILINE)

#: Her posts predate the eval stack and carry no source field. Memorie is the
#: honest reading - they came out of her own life and her own profile - and it
#: is also the strictest for `Hallucination`, which is the right way round for a
#: control: if she clears the hard setting, the metric is not merely lenient.
ASSUMED_SOURCE = "Memorie"
NO_PASSAGES = (
    "Sursa a fost memoria clientei — profilul ei și postările anterioare. "
    "Nicio căutare nu a rulat, deci nu există pasaj de verificat: orice "
    "cifră, studiu sau citat este invenție."
)


#: Matched as a PREFIX, and case-blind, because twenty-seven posts written by
#: hand over months carry twenty-seven headings: "## Caption", "## CAPTION",
#: "## Caption (lung — povestea ta, Conexiune)". Exact titles found 21 captions
#: out of 25 and no script at all, which is how the judge came to be shown a
#: hook promising six things and never the six things.
def section(text: str, *titles: str) -> str | None:
    """The first section whose heading starts with any of `titles`."""
    for block in re.finditer(
        r"^##\s+(.+?)\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    ):
        heading = block.group(1).casefold()
        if any(heading.startswith(t.casefold()) for t in titles):
            return block.group(2).strip()
    return None


def as_case(path: Path) -> dict[str, Any] | None:
    """One published post, in the shape the metrics already grade."""
    text = path.read_text(encoding="utf-8")
    caption = section(text, "Caption")
    pillar = PILLAR.search(text)
    format = FORMAT.search(text)
    if not (caption and pillar and format):
        return None

    idea = IDEA.search(text)
    brief = {
        "pilon": pillar.group(1),
        "format": format.group(1),
        "sursa": ASSUMED_SOURCE,
        "focus": (idea.group(1).strip() if idea else ""),
    }
    # Hook, script, caption, CTA - the same four parts, in the same order, that
    # `seed_golden.py` packs into `actual_output` for a generated variant. The
    # script is not optional decoration: a hook that promises "6 lucruri" is
    # grounded by the six slides that follow it, and a judge shown the promise
    # without the delivery is right to call it an invented figure.
    body = "\n\n".join(
        block
        for name in (("Hook ales", "HOOK", "Textul de pe ecran", "Slide 1"),
                     ("Script", "Scriptul", "SCRIPT", "Video"),
                     ("Caption", "CAPTION"),
                     ("CTA",))
        if (block := section(text, *name))
    )
    return {
        "id": path.stem,
        "brief": brief,
        "input": (
            f"Scrie o postare. Pilonul «{brief['pilon']}», formatul "
            f"«{brief['format']}», sursa «{brief['sursa']}». "
            f"Focus: {brief['focus']}"
        ),
        "actual_output": body or caption,
        "caption": caption,
    }


def main() -> int:
    enable_utf8_output()
    parser = argparse.ArgumentParser(description="Score her published posts.")
    parser.add_argument("--limit", type=int, default=10, help="how many posts")
    parser.add_argument("--quiet", action="store_true")
    # Repairing one rubric should cost one rubric's worth of judge calls, not
    # four. Without this, re-running the control after every wording change
    # re-scores three metrics nobody touched.
    parser.add_argument(
        "--metric", action="append", default=None,
        help="run only this metric (repeatable)",
    )
    args = parser.parse_args()

    cases = [c for p in sorted(POSTS.glob("*.md")) if (c := as_case(p))]
    if not cases:
        print("Nicio postare cu secțiune Caption și metadate.", file=sys.stderr)
        return 2
    cases = cases[: args.limit]

    judge = judge_or_none()
    if judge is None:
        print("DEEPSEEK_API_KEY lipsește — controlul are nevoie de judecător.",
              file=sys.stderr)
        return 2

    builders = {
        "BriefCompliance": lambda: brief_compliance(model=judge),
        "Hallucination": lambda: hallucination(model=judge),
        "AvatarResonance": lambda: avatar_resonance(model=judge),
    }
    if args.metric:
        wanted = set(args.metric)
        unknown = wanted - set(builders)
        if unknown:
            print(f"Metrici necunoscute: {sorted(unknown)}", file=sys.stderr)
            return 2
        builders = {k: v for k, v in builders.items() if k in wanted}

    findings: list[dict[str, Any]] = []
    for case in cases:
        test_case = LLMTestCase(
            name=case["id"],
            input=case["input"],
            actual_output=case["actual_output"],
            context=[NO_PASSAGES],
            metadata={"caption": case["caption"], **case["brief"]},
        )
        for name, build in builders.items():
            metric = build()
            try:
                metric.measure(test_case)
            except Exception as exc:  # noqa: BLE001
                findings.append({"case": case["id"], "metric": name, "score": None,
                                 "passed": False, "reason": f"{type(exc).__name__}: {exc}"})
                continue
            if getattr(metric, "skipped", False):
                continue
            score = float(metric.score)
            findings.append({
                "case": case["id"], "metric": name, "score": round(score, 3),
                "threshold": metric.threshold, "passed": score >= metric.threshold,
                "reason": metric.reason,
            })

    print(f"MARTOR POZITIV — {len(cases)} postări scrise de clientă\n")
    print(f"{'metrică':<18}{'trecut':>9}{'medie':>8}{'min':>7}{'max':>7}")
    print("-" * 49)
    for name in builders:
        rows = [f for f in findings if f["metric"] == name]
        scored = [r["score"] for r in rows if r["score"] is not None]
        if not scored:
            print(f"{name:<18}{'—':>9}")
            continue
        passed = sum(1 for r in rows if r["passed"])
        print(
            f"{name:<18}{f'{passed}/{len(rows)}':>9}"
            f"{statistics.mean(scored):>8.2f}{min(scored):>7.2f}{max(scored):>7.2f}"
        )

    if not args.quiet:
        for name in builders:
            low = [r for r in findings if r["metric"] == name and not r["passed"]]
            if not low:
                continue
            print(f"\n=== {name} — {len(low)} sub prag, pe textul EI ===")
            for row in low[:4]:
                score = "eroare" if row["score"] is None else f"{row['score']:.2f}"
                print(f"\n  {row['case']}  ({score})")
                print(f"    {(row['reason'] or '').strip()[:400]}")

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"control-{stamp}.json"
    out.write_text(
        json.dumps({"generated_at": stamp, "posts": len(cases), "findings": findings},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n{out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
