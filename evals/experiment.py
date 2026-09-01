"""One dataset, one experiment, eight scores — the whole suite on the button door.

    uv run content-studio-server                       # terminal 1
    uv run python evals/experiment.py --dry-run        # the dataset and its labels, free
    uv run python evals/experiment.py                  # 10 runs + the judge. COSTS MONEY.
    uv run python evals/experiment.py --id d-carti     # one case; repeatable

THE COURSE'S STRUCTURE LAB, ON THIS PROJECT. Until now every group here ran its
own loop and wrote its own report file, and two of them were joined only by a
time window: `run_cases.py` made spans, `relevance.py` read whatever spans the
last few minutes happened to hold. This file replaces the window with a dataset.
The cases are uploaded once, the runs are one Phoenix experiment against them,
and every score lands on the run it belongs to — so two experiments a week apart
are a comparison instead of two reports somebody has to read side by side.

ONE DOOR, AND IT IS THE BUTTON. `route/` has always measured the generation
path; `path/convergence.py` measured the chat path. Mixing them in one number
would compare a structured `GenerationBatchRequest` with a sentence she typed.
Everything here is the button: `GenerationBatchRequest`, the coordinator's own
`_title_agent` / `_detail_agent`, `title_prompt` / `detail_prompt` — `run_case`
is imported from `route/tool_usage.py` rather than rewritten, so what runs here
is what runs on a click.

THE EIGHT SCORES, and where each one already lived:

  · **router**          did it open the right `SKILL.md`?            `route/`
  · **references**      exactly the `references/` its format needs?  `route/`
  · **tools**           the right search tool for the source?        `route/`
  · **relevance_books** was what the shelf returned any good?        `skill/`
  · **relevance_web**   was what the web returned any good?          `skill/`
  · **convergence**     how long was the path, against the shortest correct one?
  · **voice**           does what it WROTE sound like her?           `output/`
  · **human**           does it sound like a Romanian wrote it?      `output/`

THE LAST TWO ARE THE ONLY ONES THAT READ THE TEXT. The other six grade the route
to the writing, and all six were green on the day the client's wife read a hook
and a caption and said neither sounded like Viorela, nor like a person. They
skip a `titluri` case, which has no hook to read, and they carry their own
control set — her own published writing has to pass and planted violations have
to fail, or the score is not printed.

THE LABELS ARE COMPOSED, NEVER COPIED. The cases are `evals/skill/cases.json`
— ten of them, and its own header says why ten and why those. The route half of
the label is not written there: it is computed at build time by
`tool_usage.expectation()` from `references.json` (the format half) and
`tool-usage-grid.json` (the source half). Three manifests would be two too many.

RELEVANCE IS TWO EVALUATORS, NOT ONE, and that is what makes it cheap. A
`Combinat` run makes two searches and a `Cărți` run makes one; each evaluator
judges only its own tool's searches and returns a scoreless skip when the run
never called it. So every search is judged exactly once, the per-tool rate is a
column in Phoenix rather than something to be recomputed, and the rubric is
`relevance.JUDGE_PROMPT` — imported, so there is still one rubric in the repo.

CONVERGENCE MEANS SOMETHING DIFFERENT ON THIS DOOR, AND THE DIFFERENCE MATTERS.
`path/convergence.py` asks whether ten phrasings of one request walk the same
path; that question needs free text, and a button has none. Here the same
arithmetic — `optimal / turns` — asks whether a run got there without wandering,
against the shortest path any run took that ALSO passed the route. Path economy,
not stability under rephrasing. The two numbers are not comparable and neither
replaces the other.

WHY THE OPTIMUM IS TAKEN OVER CORRECT RUNS. `Trajectory.py` takes `min(turns)`
outright and can: every path in it ends at the same SQL answer. This project's
named failure mode — a model that never opens the method and writes something
plausible — produces a SHORTER path, and it would set the floor and score every
honest run below a run that did nothing. Measured on 2026-08-30, on the chat
door, and it is the same trap here.

WHAT IT DOES NOT DO. It writes no batch, idea or variant: the generation agents
see `GENERATION_VISIBLE_TOOLS`, two read-only searches and nothing else, so
there is no write to gate. No `runs` row is opened — the record of an eval is
its experiment and its report file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.mcp import MCPServerStreamableHttp
from phoenix.client import AsyncClient
from phoenix.client.experiments import (
    async_evaluate_experiment,
    async_run_experiment,
    create_evaluator,
)
from phoenix.evals import LLM, create_classifier

from content_studio import enable_utf8_output
from content_studio.avatar import excerpt as avatar_excerpt
from content_studio.config import (
    CLIENT_SLUG,
    EVAL_JUDGE_MODEL,
    MCP_TIMEOUT,
    MCP_URL,
    PHOENIX_API_KEY,
    PHOENIX_COLLECTOR_ENDPOINT,
)
from content_studio.harness.conversations import (
    dictated_batch_request,
    dictated_develop,
)
from content_studio.harness.generator import (
    RUN_TIMEOUT_SECONDS,
    GenerationCoordinator,
)
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    GENERATION_VISIBLE_TOOLS,
)
from content_studio.observability import (
    configure_phoenix,
    phoenix_api_base,
    shutdown_phoenix,
)
from content_studio.voice import excerpt as voice_excerpt
from content_studio.worker import read_profile

# Running this file as a script puts `evals/` on the path, not the repo root.
# Same three lines, same reason, as `route/tool_usage.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The two output rubrics are IMPORTED, never restated: a score printed here and
# a score printed by `evals/output/voice.py` have to be the same question, or
# two numbers will be compared under one name. Same rule this file already
# follows for `run_case` and `relevance.JUDGE_PROMPT`.
from evals.output.cases import judge_llm  # noqa: E402
from evals.output.human import JUDGE_PROMPT as HUMAN_PROMPT  # noqa: E402
from evals.output.voice import JUDGE_PROMPT as VOICE_PROMPT  # noqa: E402
from evals.route.tool_usage import Case, expectation, grid, run_case  # noqa: E402
from evals.skill.relevance import (  # noqa: E402
    JUDGE_PROMPT,
    MATERIAL_CHARS,
    PROFILE,
    as_text,
)

enable_utf8_output()

HERE = Path(__file__).parent
CASES_FILE = HERE / "skill" / "cases.json"
REPORTS = HERE / "reports"

#: One dataset, reused. `create_dataset` uploads with `action="update"`, so a
#: second call under the same name writes a NEW VERSION of this dataset rather
#: than a second dataset — which is the whole point of naming it: every
#: experiment in Phoenix hangs off this one row and they compare.
DATASET_NAME = "content-studio-generare"

#: The two tools that get a relevance column each.
TOOLS = ("search_books", "search_web")

#: Phoenix's own per-task timeout, and its default is 60 SECONDS. A generation
#: run takes 60-190s, so the default would kill every task in this file before
#: the model finished. Given room above the coordinator's own ceiling: the run
#: has to be allowed to time out on its own terms, where the error says so.
TASK_TIMEOUT = RUN_TIMEOUT_SECONDS + 120

#: Phoenix retries a failed task three times by default. `run_case` already
#: retries once, and only for what production retries; a second layer here would
#: pay for a run three more times to learn the same thing.
RETRIES = 0

RULE = "─" * 96


# ---- the dataset ------------------------------------------------------------


def rows() -> list[dict[str, Any]]:
    """The ten cases, each with the label a correct run has to satisfy.

    Three fields per row, in Phoenix's own terms: `input` is what the button
    sends, `output` is the expectation, `metadata` is why the case exists. The
    route half of the expectation is COMPOSED here, off the two manifests that
    already own it, so this file adds no third copy of the method.
    """

    spec = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    domain = grid()
    idea = spec["idea"]
    built: list[dict[str, Any]] = []
    for case in spec["cases"]:
        expected = expectation(domain, case["phase"], case["format"], case["source"])
        dictated = (
            dictated_batch_request(
                case["format"], case["pillar"], case["source"], case["focus"]
            )
            if case["phase"] == "titluri"
            else dictated_develop(idea["ordinal"], idea["title"])
        )
        built.append(
            {
                "input": {
                    "case": case["id"],
                    "phase": case["phase"],
                    "format": case["format"],
                    "pillar": case["pillar"],
                    "source": case["source"],
                    "focus": case["focus"],
                    "dictated": dictated,
                },
                "output": {
                    "skill": expected.skill,
                    "references_required": list(expected.references_required),
                    "references_forbidden": list(expected.references_forbidden),
                    "tools_required": list(expected.tools_required),
                    "tools_any_of": list(expected.tools_any_of),
                    "tools_forbidden": list(expected.tools_forbidden),
                    # The witness expects the opposite verdict, and that is what
                    # makes it a witness: nine cases that all come out
                    # `relevant` look the same whether the metric works or the
                    # judge says yes to everything.
                    "relevance": case.get("expects", "relevant"),
                },
                "metadata": {"why": case.get("why", "")},
            }
        )
    return built


def cases_of(chosen: list[dict[str, Any]]) -> list[Case]:
    """The rows as the `Case` shape `run_case` runs."""

    return [
        Case(
            id=row["input"]["case"],
            phase=row["input"]["phase"],
            format=row["input"]["format"],
            pillar=row["input"]["pillar"],
            source=row["input"]["source"],
            focus=row["input"]["focus"],
            dictated=row["input"]["dictated"],
            expected=None,
        )
        for row in chosen
    ]


# ---- the task ---------------------------------------------------------------


def task_output(case: Case, route) -> dict[str, Any]:
    """One run, as the JSON the evaluators read and Phoenix stores."""

    return {
        "case": case.id,
        "turns": route.turns,
        "skills": route.skills,
        "references": route.references,
        "tools": route.tools,
        "commands": route.commands,
        "error": route.error,
        # What the run WROTE. Empty on a `titluri` case, and the two output
        # evaluators skip rather than score zero on that — the same rule
        # `relevance_*` follows for a tool the source told it not to call.
        "written": route.written,
        "searches": [
            {
                "tool": search["tool"],
                "description": str(
                    (search.get("arguments") or {}).get("description", "")
                ).strip(),
                # Truncated to exactly what the judge is shown. Whole passages
                # would put the size of the shelf into every experiment row.
                "material": as_text(search.get("result"))[:MATERIAL_CHARS],
                "returned_chars": len(as_text(search.get("result"))),
            }
            for search in route.searches
        ],
    }


# ---- the evaluators ---------------------------------------------------------


@create_evaluator(kind="CODE", name="router")
def router(output: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Did it open the right `SKILL.md`? A failure here is the frontmatter."""

    if output.get("error"):
        return {"score": 0.0, "label": "failed", "explanation": output["error"]}
    wanted = expected["skill"]
    ok = wanted in (output.get("skills") or [])
    return {
        "score": 1.0 if ok else 0.0,
        "label": "correct" if ok else "wrong",
        "explanation": (
            f"opened {output.get('skills') or '—'}; asked for {wanted}/SKILL.md"
        ),
    }


@create_evaluator(kind="CODE", name="references")
def references(output: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """All the `references/` its format calls for, and none of the others."""

    if output.get("error"):
        return {"score": 0.0, "label": "failed", "explanation": output["error"]}
    opened = output.get("references") or []
    absent = [r for r in expected["references_required"] if r not in opened]
    extra = [r for r in expected["references_forbidden"] if r in opened]
    reasons = []
    if absent:
        reasons.append(f"asked for, not opened: {absent}")
    if extra:
        reasons.append(f"opened for nothing: {extra}")
    return {
        "score": 0.0 if reasons else 1.0,
        "label": "wrong" if reasons else "correct",
        "explanation": "; ".join(reasons) or f"opened {opened or '—'}",
    }


@create_evaluator(kind="CODE", name="tools")
def tools(output: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """The search tool the source asks for, and no tool from another source."""

    if output.get("error"):
        return {"score": 0.0, "label": "failed", "explanation": output["error"]}
    called = output.get("tools") or []
    missing = [t for t in expected["tools_required"] if t not in called]
    extra = [t for t in expected["tools_forbidden"] if t in called]
    any_of = expected["tools_any_of"]
    none_of_any = bool(any_of) and not any(t in called for t in any_of)
    reasons = []
    if missing:
        reasons.append(f"asked for, not called: {missing}")
    if extra:
        reasons.append(f"from another source: {extra}")
    if none_of_any:
        reasons.append(f"none of: {any_of}")
    return {
        "score": 0.0 if reasons else 1.0,
        "label": "wrong" if reasons else "correct",
        "explanation": "; ".join(reasons) or f"called {called or '—'}",
    }


#: One classifier for both tools, built on first use. Lazy because a run that
#: never called a tool never needs its judge - and because building it reaches
#: for an OpenAI key, which is the one thing a unit test must not need.
_CLASSIFIER: Any = None


def judge() -> Any:
    """The rubric, `relevance.JUDGE_PROMPT` — imported, so there is one of it."""

    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = create_classifier(
            name="relevance",
            prompt_template=JUDGE_PROMPT,
            llm=LLM(provider="openai", model=EVAL_JUDGE_MODEL),
            choices={"relevant": 1.0, "irelevant": 0.0},
        )
    return _CLASSIFIER


def relevance_evaluator(tool: str, avatar: str):
    """One judged column per tool, over only that tool's searches.

    Scored against what the case EXPECTS, not against `relevant` — so the
    witness passes by being refused, which is the only way a witness can prove
    the metric works rather than drag its rate down while working perfectly. The
    label carries the judge's own verdict, so Phoenix shows both.
    """

    @create_evaluator(kind="LLM", name=f"relevance_{tool.removeprefix('search_')}")
    async def relevance(
        output: dict[str, Any], input: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any]:
        searches = [s for s in (output.get("searches") or []) if s["tool"] == tool]
        if not searches:
            # NO SCORE, not a zero. A `Cărți` run is not supposed to call
            # `search_web`, and scoring it zero would make the correct route
            # look like a failed search.
            return {
                "label": "—",
                "explanation": f"The run did not call {tool}; nothing to judge.",
            }

        verdicts: list[str] = []
        why: list[str] = []
        for search in searches:
            scores = await judge().async_evaluate(
                {
                    "format": input["format"],
                    "pillar": input["pillar"],
                    "source": input["source"],
                    "focus": input["focus"] or "— (no focus; the pillar and the avatar)",
                    "avatar": avatar,
                    "description": search["description"],
                    "material": search["material"],
                }
            )
            first = scores[0] if scores else None
            verdicts.append(getattr(first, "label", None) or "unread")
            why.append(f"«{search['description'][:70]}» → {verdicts[-1]}")

        # "relevant" only if every search this tool made was. One good passage
        # does not excuse a second call that came back with noise.
        got = "relevant" if all(v == "relevant" for v in verdicts) else "irelevant"
        wanted = expected.get("relevance", "relevant")
        return {
            "score": 1.0 if got == wanted else 0.0,
            "label": got,
            "explanation": f"expected {wanted}. " + " | ".join(why),
        }

    return relevance


def convergence_evaluator(optimal: int):
    """`optimal / turns`, with the optimum handed in from the first pass.

    A second pass because the optimum is a fact about the whole experiment and
    an evaluator only ever sees one run. Capped at 1.0: a run that wandered
    cannot beat the floor, but a run that FAILED the route can be shorter than
    it, and letting that print 1.200 would make the worst outcome look best.
    """

    @create_evaluator(kind="CODE", name="convergence")
    def convergence(output: dict[str, Any]) -> dict[str, Any]:
        turns = output.get("turns") or 0
        if not turns:
            return {
                "score": 0.0,
                "label": "failed",
                "explanation": output.get("error") or "no steps",
            }
        return {
            "score": round(min(optimal / turns, 1.0), 3),
            "label": f"{turns} steps",
            "explanation": f"shortest correct path: {optimal} steps",
        }

    return convergence


# ---- the two that read what was WRITTEN -------------------------------------
#
# The other five grade the route to the writing. These grade the writing, and
# they exist because the client's wife read a hook and a caption in Romanian on
# 2026-09-01 and said neither sounded like Viorela, nor like a person — while
# every route score was green.
#
# THREE THINGS SET THEM APART FROM THE FIVE ABOVE, all deliberate:
#
#   · They SKIP on a `titluri` case. Phase 1 writes titles and angles; there is
#     no hook and no caption to read. A zero there would be a metric punishing a
#     run for doing exactly what it was asked.
#   · They judge with `EVAL_JUDGE_MODEL`, like the rest — but only after the
#     alternative was tried and measured. A grader from the author's own lineage
#     marks its own work, so `config.py`'s DeepSeek address was wired in and run
#     against both control sets on 2026-09-01: DeepSeek judges her voice better
#     (16/16 against 15/16) and cannot judge `human` at all (2/4 planted caught
#     against 4/4), passing a caption taken verbatim from a real run. What buys
#     the independence back is the controls, which run every time.
#
#   · The rubrics are IMPORTED from `evals/output/`, never restated. That is the
#     same rule this file already follows for `run_case` and `JUDGE_PROMPT`: a
#     score printed here and a score printed by the standalone script have to be
#     the same question, or two numbers wearing one name will be compared.
#
# COST: one judge call per variant per field, so a five-variant detail case
# costs ten calls per metric. `--dry-run` prints the count before anything is
# spent.

_OUTPUT_CLASSIFIERS: dict[str, Any] = {}


def output_judge(metric: str, prompt: str, choices: dict[str, float]):
    """One classifier per output metric, built once and reused.

    `judge_llm` is imported rather than rebuilt so this file and the standalone
    scripts cannot end up asking two different models the same question.
    """

    if metric not in _OUTPUT_CLASSIFIERS:
        llm, _ = judge_llm()
        _OUTPUT_CLASSIFIERS[metric] = create_classifier(
            name=metric,
            prompt_template=prompt,
            llm=llm,
            choices=choices,
        )
    return _OUTPUT_CLASSIFIERS[metric]


def written_evaluator(metric: str, prompt: str, choices: dict[str, float], **fixed):
    """A judged column over every hook and caption one run produced.

    `fixed` is whatever the rubric needs beyond the text itself — `voice` wants
    her voice block, `human` wants nothing. Aggregated the way `relevance` is:
    the run passes only if every piece of writing in it did, because one good
    caption does not excuse four that read as translated.
    """

    @create_evaluator(kind="LLM", name=metric)
    async def evaluate(output: dict[str, Any]) -> dict[str, Any]:
        written = output.get("written") or []
        if not written:
            # NO SCORE, not a zero — see the block comment above.
            return {
                "label": "—",
                "explanation": "The run wrote no hook or caption; nothing to judge.",
            }

        verdicts: list[str] = []
        why: list[str] = []
        for variant in written:
            for field_name in ("hook", "caption"):
                text = (variant.get(field_name) or "").strip()
                if not text:
                    continue
                scores = await output_judge(metric, prompt, choices).async_evaluate(
                    {"field": field_name, "text": text, **fixed}
                )
                first = scores[0] if scores else None
                label = getattr(first, "label", None) or "unread"
                verdicts.append(label)
                if choices.get(label, 0.0) < 1.0:
                    # Only the failures are worth the width: a run where
                    # everything passed says so in its score.
                    why.append(
                        f"{variant.get('hook_type', '?')}/{field_name}: "
                        f"{(getattr(first, 'explanation', '') or '')[:120]}"
                    )

        if not verdicts:
            return {"label": "—", "explanation": "Nothing readable to judge."}

        good = sum(1 for label in verdicts if choices.get(label, 0.0) == 1.0)
        passed = good == len(verdicts)
        return {
            "score": 1.0 if passed else 0.0,
            "label": f"{good}/{len(verdicts)}",
            "explanation": " | ".join(why) if why else "every piece passed",
        }

    return evaluate


def voice_evaluator(voice_block: str):
    """`voice` — does what it wrote sound like HER?

    The block is her own four profile sections, read once by the caller and
    handed in, exactly as `relevance_evaluator` takes the avatar.
    """

    return written_evaluator(
        "voice",
        VOICE_PROMPT,
        {"hers": 1.0, "generic": 0.0},
        voice=voice_block,
    )


def human_evaluator():
    """`human` — does it read as Romanian a person wrote, not translated into?"""

    return written_evaluator("human", HUMAN_PROMPT, {"human": 1.0, "translated": 0.0})


# ---- reading the results ----------------------------------------------------


def scores_by_run(ran: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`{experiment_run_id: {evaluator: score}}`, off the evaluation runs."""

    out: dict[str, dict[str, Any]] = {}
    for run in ran.get("evaluation_runs") or []:
        result = getattr(run, "result", None) or {}
        out.setdefault(getattr(run, "experiment_run_id", ""), {})[
            getattr(run, "name", "?")
        ] = result.get("score")
    return out


def optimum(ran: dict[str, Any]) -> int | None:
    """The shortest path among the runs that passed all three route scores."""

    graded = scores_by_run(ran)
    lengths = [
        run["output"]["turns"]
        for run in ran.get("task_runs") or []
        if isinstance(run.get("output"), dict)
        and run["output"].get("turns")
        and all(
            graded.get(run.get("id", ""), {}).get(name) == 1.0
            for name in ("router", "references", "tools")
        )
    ]
    return min(lengths) if lengths else None


def summarise(ran: dict[str, Any], rows_by_case: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per case, with every score that landed on it."""

    graded = scores_by_run(ran)
    findings = []
    for run in ran.get("task_runs") or []:
        output = run.get("output") if isinstance(run.get("output"), dict) else {}
        case = output.get("case", "?")
        findings.append(
            {
                "case": case,
                "turns": output.get("turns"),
                "error": output.get("error"),
                # The route as it actually was, not only its verdict. A
                # `references` of 0.0 with no list beside it is a report that
                # cannot be acted on - found the first full run, 2026-08-30.
                "skills": output.get("skills"),
                "references": output.get("references"),
                "tools": output.get("tools"),
                "searches": [
                    {k: v for k, v in s.items() if k != "material"}
                    for s in output.get("searches") or []
                ],
                "expected": rows_by_case.get(case, {}).get("output"),
                "scores": graded.get(run.get("id", ""), {}),
            }
        )
    findings.sort(key=lambda f: f["case"])
    return findings


NAMES = (
    "router",
    "references",
    "tools",
    "relevance_books",
    "relevance_web",
    "convergence",
    # The two that read the text. Last on purpose: the report reads left to
    # right as "did it reach the method, was the material any good, how long did
    # it take, and is what came out worth reading".
    "voice",
    "human",
)


def show(findings: list[dict[str, Any]], url: str) -> None:
    """The report, in Romanian — the terminal is read by the client too."""

    print(f"\n{RULE}")
    header = f"{'case':<24}{'steps':>5}"
    for name in NAMES:
        header += f"{name.replace('relevance_', 'rel.'):>13}"
    print(header)
    print("-" * len(header))
    for finding in findings:
        line = f"{finding['case']:<24}{finding['turns'] or '—':>5}"
        for name in NAMES:
            score = finding["scores"].get(name)
            line += f"{'—' if score is None else f'{score:.3f}':>13}"
        print(line)

    print(f"\n{RULE}")
    print(f"{'evaluator':<20}{'passed':>12}{'rate':>9}   what it says")
    print("-" * 96)
    meaning = {
        "router": "opened the phase's SKILL.md",
        "references": "exactly the format's references",
        "tools": "the tool the source asks for",
        "relevance_books": "what the shelf returned, judged",
        "relevance_web": "what the web returned, judged",
        "convergence": "short path / the shortest correct one",
        "voice": "the hook and caption sound like her",
        "human": "the Romanian reads as a person's",
    }
    for name in NAMES:
        scored = [f["scores"][name] for f in findings if f["scores"].get(name) is not None]
        if not scored:
            print(f"{name:<20}{'—':>12}{'—':>9}   {meaning[name]} (no cases)")
            continue
        if name == "convergence":
            # A mean, not a pass count: every run has a length and none of them
            # is a pass or a fail on its own.
            print(
                f"{name:<20}{len(scored):>12}{sum(scored) / len(scored):>9.3f}"
                f"   {meaning[name]} (medie)"
            )
            continue
        passed = sum(1 for s in scored if s == 1.0)
        print(
            f"{name:<20}{f'{passed}/{len(scored)}':>12}"
            f"{passed / len(scored):>9.3f}   {meaning[name]}"
        )

    # NO SILENT GAPS. `Memorie` is the source whose rule is "call nothing", and
    # it is not in this dataset — `cases.json` leaves it out because a run that
    # searches nothing leaves the judge nothing to read. So the forbidden half
    # of `tools` is exercised here only where a source forbids the OTHER tool.
    print(
        "\nWhat this set does NOT cover: the `Memorie` source (the «call nothing» rule)."
        "\n  uv run python evals/route/tool_usage.py --source Memorie"
    )
    if url:
        print(f"\nIn Phoenix: {url}")


def report(findings: list[dict[str, Any]], meta: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = REPORTS / f"experiment-{stamp}.json"
    path.write_text(
        json.dumps(
            {"generated_at": datetime.now(UTC).isoformat(), **meta, "findings": findings},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


# ---- the driver -------------------------------------------------------------


async def run(
    chosen: list[dict[str, Any]], name: str, concurrency: int, repetitions: int
) -> int:
    domain = grid()
    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {
                CONVERSATION_HEADER: "experiment",
                CLIENT_HEADER: CLIENT_SLUG,
            },
        },
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(GENERATION_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    try:
        await data_mcp.connect()
        _, profile_md = await read_profile(data_mcp)
    except Exception as e:  # noqa: BLE001
        print(
            f"The MCP server does not answer at {MCP_URL}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        print("  Start `uv run content-studio-server` in another terminal.", file=sys.stderr)
        return 2

    # Built without `__init__` for the same reason `tool_usage.run_grid` does it:
    # a coordinator owns background tasks and MCP factories nothing here wants.
    coordinator = GenerationCoordinator.__new__(GenerationCoordinator)
    coordinator._accounts = None
    coordinator._conversations = None

    by_case = {case.id: case for case in cases_of(chosen)}
    rows_by_case = {row["input"]["case"]: row for row in chosen}

    async def task(input: dict[str, Any]) -> dict[str, Any]:
        case = by_case[input["case"]]
        route = await run_case(coordinator, profile_md, data_mcp, case, domain["idea"])
        return task_output(case, route)

    client = AsyncClient(
        base_url=phoenix_api_base(PHOENIX_COLLECTOR_ENDPOINT), api_key=PHOENIX_API_KEY
    )
    profile_text = PROFILE.read_text(encoding="utf-8")
    avatar = avatar_excerpt(profile_text)
    # Her voice, read once and handed to the judge — the same four sections the
    # WRITER is shown, from the same module, so the two cannot drift.
    voice_block = voice_excerpt(profile_text)
    _, output_judge_name = judge_llm()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")

    try:
        dataset = await client.datasets.create_dataset(
            name=name,
            inputs=[row["input"] for row in chosen],
            outputs=[row["output"] for row in chosen],
            metadata=[row["metadata"] for row in chosen],
            dataset_description=(
                "Generation cases for the button door: route label composed from"
                " references.json + tool-usage-grid.json, relevance expectation"
                " from skill/cases.json."
            ),
        )
        print(f"Dataset: {name} — {len(chosen)} cases")

        ran = await async_run_experiment(
            client=client,
            dataset=dataset,
            task=task,
            evaluators=[
                router,
                references,
                tools,
                relevance_evaluator("search_books", avatar),
                relevance_evaluator("search_web", avatar),
                # The two that read what was WRITTEN, not the route to it.
                # They skip on a `titluri` case, which has no hook or caption.
                voice_evaluator(voice_block),
                human_evaluator(),
            ],
            experiment_name=f"generare-{stamp}",
            experiment_description="route + relevance + output, one run per case",
            experiment_metadata={
                "judge": EVAL_JUDGE_MODEL,
                # Named separately because it IS separate, on purpose: the
                # output metrics are graded outside the family that writes.
                "output_judge": output_judge_name,
            },
            concurrency=concurrency,
            timeout=TASK_TIMEOUT,
            repetitions=repetitions,
            retries=RETRIES,
            print_summary=False,
        )

        optimal = optimum(ran)
        if optimal is None:
            # NEVER PRINT A SCORE THAT COULD NOT BE COMPUTED. With no correct
            # run there is no floor, and dividing by the shortest path outright
            # would score every honest run against one that did nothing.
            print(
                "\nNo run walked the whole route — there is no optimum to"
                " divide by. Convergence is not computed.",
                file=sys.stderr,
            )
        else:
            ran = await async_evaluate_experiment(
                client=client,
                experiment=ran,
                evaluators=[convergence_evaluator(optimal)],
                concurrency=concurrency,
                timeout=TASK_TIMEOUT,
                retries=RETRIES,
                print_summary=False,
            )
    finally:
        await data_mcp.cleanup()

    findings = summarise(ran, rows_by_case)
    url = client.experiments.get_experiment_url(
        dataset_id=ran["dataset_id"], experiment_id=ran["experiment_id"]
    )
    show(findings, url)
    path = report(
        findings,
        {
            "dataset": name,
            "experiment": ran["experiment_id"],
            "judge": EVAL_JUDGE_MODEL,
            "optimal_turns": optimal,
            "url": url,
        },
    )
    print(f"Raport: {path}")
    return 0


def show_labels(chosen: list[dict[str, Any]]) -> None:
    print(f"{'case':<24}{'phase':<9}{'skill':<19}{'tools':<38}references asked for")
    print(RULE)
    for row in chosen:
        wanted = row["output"]
        refs = ", ".join(r.split("/")[-1] for r in wanted["references_required"]) or "—"
        tools_ = ", ".join(wanted["tools_required"]) or ""
        if wanted["tools_any_of"]:
            tools_ = f"any of: {', '.join(wanted['tools_any_of'])}"
        print(
            f"{row['input']['case']:<24}{row['input']['phase']:<9}"
            f"{wanted['skill']:<19}{tools_ or '—':<38}{refs}"
        )
    witness = [r["input"]["case"] for r in chosen if r["output"]["relevance"] != "relevant"]
    # Only a `detalii` case writes a hook and a caption, so only those reach the
    # two output metrics — and how many judge calls that is, is worth knowing
    # before anything is spent rather than after.
    writing = [r["input"]["case"] for r in chosen if r["input"]["phase"] == "detalii"]
    _, output_judge_name = judge_llm()
    print(
        f"\n{len(chosen)} cases. No model, no container, no cost."
        f"\nNegative witness (`irelevant` expected): {', '.join(witness) or '—'}"
        f"\n\n`voice` and `human` read only what was written, so they judge the"
        f" {len(writing)} `detalii` case(s): {', '.join(writing) or '—'}."
        f"\nThe other {len(chosen) - len(writing)} return a scoreless skip."
        f"\nJudge: {output_judge_name}. At five variants x two fields that is"
        f" {len(writing) * 5 * 2} calls per metric."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="one dataset, one experiment, six scores")
    parser.add_argument("--dry-run", action="store_true", help="the dataset and labels, free")
    parser.add_argument("--id", dest="ids", action="append", help="one case; repeatable")
    parser.add_argument(
        "--concurrency", type=int, default=2, help="how many containers at once (default 2)"
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="run each case N times; N>1 also shows the spread of path lengths",
    )
    args = parser.parse_args()

    chosen = rows()
    name = DATASET_NAME
    if args.ids:
        unknown = set(args.ids) - {row["input"]["case"] for row in chosen}
        if unknown:
            raise SystemExit(f"Unknown cases: {sorted(unknown)}")
        chosen = [row for row in chosen if row["input"]["case"] in args.ids]
        # A DIFFERENT DATASET, and the smoke test of 2026-08-30 is why. An
        # experiment runs against every example the dataset holds, so filtering
        # meant uploading only the chosen ones - and `create_dataset` writes a
        # new VERSION under the same name, which quietly left the shared dataset
        # holding one case. A one-case probe must not be able to shrink the
        # thing every other experiment is compared against.
        name = f"{DATASET_NAME}-proba"

    if args.dry_run:
        show_labels(chosen)
        return 0

    if not (PHOENIX_COLLECTOR_ENDPOINT and PHOENIX_API_KEY):
        print("Phoenix is not configured: PHOENIX_COLLECTOR_ENDPOINT or the key is missing.")
        return 1

    # The agent's own spans go to Phoenix like any run's. Inside an experiment
    # task they are re-labelled into the EXPERIMENT'S project — Phoenix merges
    # its resource into every span opened in the task's context — so a search
    # made here will not show up in the ordinary project, and
    # `skill/relevance.py --minutes N` will not find it. That is the trade for
    # having the spans hang off the experiment run they belong to.
    phoenix = configure_phoenix()
    print(f"phoenix   {phoenix['detail']}")
    print(f"judge {EVAL_JUDGE_MODEL}")
    try:
        return asyncio.run(
            run(chosen, name, max(1, args.concurrency), max(1, args.repetitions))
        )
    finally:
        shutdown_phoenix()


if __name__ == "__main__":
    raise SystemExit(main())
