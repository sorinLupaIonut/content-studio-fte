"""Grade what really ran, against `trace-rubric.json`. No schedule anywhere.

    uv run python evals/grade.py --hours 24
    uv run python evals/grade.py --hours 1 --dry-run     # no model call, no cost
    uv run python evals/grade.py --run <run_id>

WHAT THIS IS. Concept 12's second attachment point: read the traces, grade them
against a rubric, write a report. The course calls it a nightly scheduled job.
There is no schedule here on purpose - the studio is not left running, so a cron
would mostly wake up to an empty window. It is the same work, started by a
person, and the window is an argument.

TWO GRADERS, AND THE ORDER MATTERS.

`deterministic` criteria are settled here, in Python, for nothing: a caption is
863 characters or it is not, ten angle types are distinct or two of them are the
same. `judge` criteria go to the OpenAI Evals API as `score_model` testing
criteria - LLM-as-judge, the grader the course names - because "does this sound
like her" has no arithmetic. Deterministic first, always. A rule a number can
settle should never cost a model call, and most of what broke this project was
settleable by a number.

WHERE THE TEXT COMES FROM, AND WHY NOT FROM THE DATABASE. `public.traces` keeps
`response_id` but not the messages, so the answer itself is fetched back from
the provider. That is not a workaround; it is the better source. A rejected
answer never became a `generation_variants` row - and on 2026-08-24, 39 of 44
failed turns died on a single malformed hashtag. Grading only what was stored
would have reported a clean night on the day a quarter of the money burned.
Retrieval by id costs no tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig

# Run as `uv run python evals/grade.py`, the way every other script in this
# folder is run, and `sys.path[0]` is `evals/` - so `evals.traces` is not
# importable unless the project root is put back. The tests import it as
# `evals.traces` from the root, where it already resolves; this line is for the
# command line, and it is a no-op there.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.traces import GradedRun, read  # noqa: E402

HERE = Path(__file__).parent
RUBRIC_FILE = HERE / "trace-rubric.json"
REPORTS_DIR = HERE / "reports"

#: A run whose `session_id` starts with this had its method preloaded, so the
#: tool-correctness question flips. See the rubric's `why_two_branches`.
GENERATION_PREFIX = "generation"

#: The tools that must NOT be called on the preloaded path. A call is not a
#: crime - it is evidence that the preloaded body still tells the model to fetch
#: something it was already given, which is the one failure mode `method.py`
#: exists to prevent.
PRELOADED_FORBIDDEN = ("citeste-referinta", "propune-postari", "dezvolta-postarea")

HASHTAG_OK = re.compile(r"^#\S+$")


@dataclass(slots=True)
class Finding:
    """One criterion's verdict on one run. `score` is 0..1, `detail` is why."""

    criterion: str
    score: float
    detail: str
    sample: int = 1


@dataclass(slots=True)
class RunReport:
    run: GradedRun
    kind: str
    findings: list[Finding] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.run.as_dict(),
            "kind": self.kind,
            "findings": [
                {"criterion": f.criterion, "score": f.score, "detail": f.detail}
                for f in self.findings
            ],
        }


def load_rubric() -> dict[str, Any]:
    return json.loads(RUBRIC_FILE.read_text(encoding="utf-8"))


def run_kind(run: GradedRun) -> str:
    """Which branch of the rubric applies. Read from `session_id`, which the
    harness builds with a stable prefix per phase - not from the message text,
    which is Romanian prose and will be reworded one day."""

    if run.session_id.startswith("generation-detail"):
        return "generation-detail"
    if run.session_id.startswith(GENERATION_PREFIX):
        return "generation-title"
    return "chat"


# ---- deterministic criteria --------------------------------------------------


def grade_tool_correctness(run: GradedRun, kind: str) -> Finding:
    if kind.startswith("generation"):
        offenders = [n for n in run.tool_names if n in PRELOADED_FORBIDDEN]
        if not offenders:
            return Finding(
                "tool_correctness",
                1.0,
                "metoda preîncărcată, niciun apel irosit",
            )
        return Finding(
            "tool_correctness",
            0.0,
            f"a cerut ce avea deja: {', '.join(sorted(set(offenders)))}",
        )

    skills = [n for n in run.tool_names if n in ("propune-postari", "dezvolta-postarea")]
    if skills:
        return Finding("tool_correctness", 1.0, f"skill pornit: {skills[0]}")
    return Finding("tool_correctness", 0.0, "niciun skill nu a pornit")


def _captions(answers: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for answer in answers:
        for variant in answer.get("variants") or []:
            caption = variant.get("caption")
            if isinstance(caption, str):
                out.append(caption)
    return out


def _angle_types(answers: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for answer in answers:
        for idea in answer.get("ideas") or []:
            value = idea.get("angle_type")
            if isinstance(value, str):
                out.append(value)
    return out


def _hashtags(answers: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for answer in answers:
        for variant in answer.get("variants") or []:
            for tag in variant.get("hashtags") or []:
                if isinstance(tag, str):
                    out.append(tag)
    return out


def grade_contract_quality(
    answers: list[dict[str, Any]], rubric: dict[str, Any]
) -> list[Finding]:
    """Everything the schema cannot hold, measured on the model's own answer."""

    checks = {
        check["id"]: check
        for criterion in rubric["criteria"]
        if criterion["id"] == "contract_quality"
        for check in criterion["checks"]
    }
    findings: list[Finding] = []

    captions = _captions(answers)
    if captions:
        low = checks["caption_length"]["min"]
        high = checks["caption_length"]["max"]
        in_range = [c for c in captions if low <= len(c) <= high]
        lengths = [len(c) for c in captions]
        findings.append(
            Finding(
                "caption_length",
                len(in_range) / len(captions),
                f"{len(in_range)}/{len(captions)} în 900–1400; "
                f"medie {statistics.mean(lengths):.0f}, "
                f"min {min(lengths)}, max {max(lengths)}",
                sample=len(captions),
            )
        )

    angles = _angle_types(answers)
    if angles:
        distinct = len(set(angles))
        findings.append(
            Finding(
                "distinct_angles",
                distinct / len(angles),
                f"{distinct} tipare distincte din {len(angles)} propuneri"
                + ("" if distinct == len(angles) else " — repetat"),
                sample=len(angles),
            )
        )

    tags = _hashtags(answers)
    if tags:
        clean = [t for t in tags if HASHTAG_OK.match(t)]
        findings.append(
            Finding(
                "hashtags",
                len(clean) / len(tags),
                f"{len(tags) - len(clean)} din {len(tags)} au avut nevoie de reparație",
                sample=len(tags),
            )
        )

    return findings


# ---- the answers themselves --------------------------------------------------


async def fetch_answers(runs: list[RunReport]) -> int:
    """Trade every `response_id` back for the answer the model actually wrote.

    Free - retrieval is not billed - and it reaches the rejected attempts too,
    which never reached the database. A response the provider has aged out is
    skipped rather than fatal: the window is 30 days and a report over an older
    one should thin out, not fail.
    """

    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    fetched = 0
    for report in runs:
        for response_id in report.run.response_ids:
            try:
                response = await client.responses.retrieve(response_id)
                text = response.output_text
            except Exception:  # noqa: BLE001 - an aged-out id is not a failure
                continue
            try:
                report.answers.append(json.loads(text))
                fetched += 1
            except ValueError:
                # A chat reply is prose, not a contract. Kept as text so the
                # judge can still read it.
                report.answers.append({"text": text})
                fetched += 1
    return fetched


# ---- the judge, through the OpenAI Evals API ---------------------------------


def judge_criteria(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in rubric["criteria"] if c["kind"] == "judge"]


def testing_criteria(
    rubric: dict[str, Any], *, any_retrieval: bool
) -> list[dict[str, Any]]:
    """The rubric's judge criteria, in the shape `client.evals.create` wants.

    `score_model` rather than `label_model`: a threshold you can move is worth
    more than a pass/fail somebody has to re-argue, and the rubric already
    carries the number.

    ATTRIBUTION IS LEFT OUT WHEN NOTHING WAS RETRIEVED, and that is the fix for
    a real false positive: the first live grading run scored attribution 1.0 on
    two batches written from memory, the judge reasoning that with no passages
    there was nothing to contradict. True, and useless - a criterion that always
    passes is a criterion nobody will believe on the day it fails. The rubric
    already says `applies_when`; this is where that sentence is obeyed.
    """

    criteria: list[dict[str, Any]] = []
    for criterion in judge_criteria(rubric):
        if criterion["id"] == "attribution" and not any_retrieval:
            continue
        criteria.append(
            {
                "type": "score_model",
                "name": criterion["id"],
                "model": criterion["model"],
                "pass_threshold": criterion["pass_threshold"],
                "range": [0.0, 1.0],
                "input": [
                    {"role": "system", "content": "\n".join(criterion["prompt"])},
                    {
                        "role": "user",
                        "content": (
                            "Pasajele întoarse de căutare:\n{{item.passages}}\n\n"
                            "Textul de notat:\n{{item.text}}"
                        ),
                    },
                ],
            }
        )
    return criteria


def judge_items(runs: list[RunReport]) -> list[dict[str, Any]]:
    """One item per answer, not per run: a batch of ten ideas is ten things to
    read, and averaging them before the judge sees them hides the bad one."""

    items: list[dict[str, Any]] = []
    for report in runs:
        for answer in report.answers:
            text = json.dumps(answer, ensure_ascii=False, indent=2)
            passages = json.dumps(report.run.retrieved, ensure_ascii=False)
            items.append(
                {
                    "item": {
                        "run_id": report.run.run_id,
                        "kind": report.kind,
                        "text": text[:20_000],
                        "passages": passages[:20_000] if report.run.searched else "—",
                    }
                }
            )
    return items


async def send_to_evals(
    rubric: dict[str, Any], runs: list[RunReport]
) -> dict[str, Any]:
    """Create the eval and one run of it. Returns what the report should keep.

    The eval object is created fresh each time rather than looked up by name.
    An eval is cheap, and one per grading run keeps the rubric that graded a
    report attached to that report - editing the prompt and reusing the id
    would silently re-score history against words nobody kept.
    """

    from openai import AsyncOpenAI

    items = judge_items(runs)
    if not items:
        return {"skipped": "nicio ieșire de notat"}

    any_retrieval = any(report.run.retrieved for report in runs)
    criteria = testing_criteria(rubric, any_retrieval=any_retrieval)
    if not criteria:
        return {"skipped": "niciun criteriu de judecată se aplică"}

    client = AsyncOpenAI()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    evaluation = await client.evals.create(
        name=f"{rubric['name']} · {stamp}",
        data_source_config={
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "text": {"type": "string"},
                    "passages": {"type": "string"},
                },
                "required": ["run_id", "text", "passages"],
            },
            "include_sample_schema": False,
        },
        testing_criteria=criteria,
    )
    run = await client.evals.runs.create(
        eval_id=evaluation.id,
        name=f"trace-grading {stamp}",
        data_source={
            "type": "jsonl",
            "source": {"type": "file_content", "content": items},
        },
    )
    return {
        "eval_id": evaluation.id,
        "run_id": run.id,
        "items": len(items),
        "criteria": [c["name"] for c in criteria],
        "report_url": getattr(run, "report_url", None),
        "status": getattr(run, "status", None),
    }


# ---- putting it together -----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grade the runs in a window against trace-rubric.json."
    )
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--run", dest="run_id", help="one run instead of a window")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="deterministic criteria only; no model, no cost",
    )
    parser.add_argument("--out", type=Path, help="where to write the report")
    return parser


def print_summary(reports: list[RunReport], judged: dict[str, Any]) -> None:
    print(f"\n{len(reports)} rulări notate\n")
    for report in reports:
        print(f"  {report.run.started_at:%H:%M}  {report.run.run_id[:12]}  {report.kind}")
        for finding in report.findings:
            mark = "ok  " if finding.score >= 0.7 else "SLAB"
            print(f"      {mark} {finding.criterion:<18} {finding.score:.2f}  {finding.detail}")
        print()

    by_criterion: dict[str, list[float]] = {}
    for report in reports:
        for finding in report.findings:
            by_criterion.setdefault(finding.criterion, []).append(finding.score)
    if by_criterion:
        print("  medii:")
        for name, scores in sorted(by_criterion.items()):
            print(f"      {name:<20} {statistics.mean(scores):.2f}  ({len(scores)} rulări)")

    if judged.get("skipped"):
        print(f"\n  judecătorul: sărit — {judged['skipped']}")
    elif judged:
        print(f"\n  judecătorul: {judged['items']} bucăți trimise la OpenAI Evals")
        print(f"      criterii: {', '.join(judged.get('criteria', []))}")
        print(f"      eval  {judged['eval_id']}")
        print(f"      run   {judged['run_id']}  ({judged.get('status')})")
        print("      https://platform.openai.com/evals")


async def main() -> int:
    args = build_parser().parse_args()
    rubric = load_rubric()

    try:
        runs = await read(hours=args.hours, run_id=args.run_id)
    except MissingConfig as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    if not runs:
        print(
            "Nicio rulare în interval — nimic de notat.\n"
            "Nu e o defecțiune: setul crește doar din urmele pe care le-a văzut."
        )
        return 0

    reports = [RunReport(run=run, kind=run_kind(run)) for run in runs]

    if not args.dry_run:
        fetched = await fetch_answers(reports)
        print(f"{fetched} răspunsuri răscumpărate după response_id (fără cost)")

    for report in reports:
        report.findings.append(grade_tool_correctness(report.run, report.kind))
        report.findings.extend(grade_contract_quality(report.answers, rubric))

    judged: dict[str, Any] = {}
    if not args.dry_run:
        try:
            judged = await send_to_evals(rubric, reports)
        except Exception as exc:  # noqa: BLE001 - the local half still stands
            judged = {"skipped": f"API-ul de Evals a refuzat: {exc}"}

    print_summary(reports, judged)

    REPORTS_DIR.mkdir(exist_ok=True)
    out = args.out or REPORTS_DIR / f"{datetime.now(UTC):%Y-%m-%d-%H%M}.json"
    out.write_text(
        json.dumps(
            {
                "rubric": rubric["name"],
                "window_hours": args.hours,
                "generated_at": datetime.now(UTC).isoformat(),
                "dry_run": args.dry_run,
                "judge": judged,
                "runs": [report.as_dict() for report in reports],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nraport: {out}")
    return 0


if __name__ == "__main__":
    enable_utf8_output()
    raise SystemExit(asyncio.run(main()))
