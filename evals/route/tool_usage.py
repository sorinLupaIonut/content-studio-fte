"""Metric `tool_usage` — the whole domain grid, one real run per square.

    uv run content-studio-server                     # terminal 1
    uv run python evals/route/tool_usage.py --dry-run      # the labels, free, no model
    uv run python evals/route/tool_usage.py                # the spine: 24 real runs
    uv run python evals/route/tool_usage.py --all          # all 240. COSTS MONEY.
    uv run python evals/route/tool_usage.py --format Reel --source Cărți --phase detalii

NOT `tool_use.py`. That file runs six hand-written cases and asks one question
per case: was any required tool missing. This one asks the same question of the
ENTIRE domain — every format × pillar × source × focus the interface can
produce, in both phases — and splits the answer into the three the course's
Skill lab splits it into:

  · **router**    did it open the right SKILL.md? (Faza 1 vs Faza 2)
  · **references** did it open exactly the `references/` its format and source
                   call for — all of them, and none of the others?
  · **tools**     did it call `search_books` / `search_web` when the source says
                  to, and stay off them when it says not to?

THE INPUT IS THE ONE PRODUCTION SENDS, not a re-typing of it. The request goes
through `GenerationBatchRequest`, the agent through `GenerationCoordinator`'s
own `_title_agent` / `_detail_agent`, and the message through `title_prompt` /
`detail_prompt` — the same three builders `tests/checks/paid/run_like_production.py`
uses, for the same reason: a prompt written here would be a fourth copy that
drifts. Each case also prints the sentence the button dictates
(`dictated_batch_request`, `dictated_develop`), so what you READ in the report
is what she types and what is SENT is what the button sends.

WHY THE GRID AND NOT SIX CASES. Both halves of the route are decided by a
choice she makes in a form: the references by the format, the reference and the
tool by the source. Six cases sample that; 240 cover it. And the failures
cluster — a summary per axis at the end says whether it is one format, one
source or one pillar that misbehaves, which is the question a fix starts from.

WHAT COSTS WHAT. One case is one container and one model call — measured
around 60-120s and a few cents. The full grid is 240 of them. The default is
the SPINE: the 24 squares whose LABEL is distinct (phase × format × source),
with the pillar and the focus rotated across them so all five pillars and both
focus states are still exercised. Nothing is capped silently: the run says how
many squares it skipped and why.

WHAT IT DOES NOT DO. It writes no batch, idea or variant — the generation
agents see `GENERATION_VISIBLE_TOOLS`, which is `search_books` and `search_web`
and nothing else, so there is no write to gate and no approval to refuse. The
spans go to Phoenix like any run; no `runs` row is opened, because the record of
an eval is its report file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents import Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig

from content_studio import enable_utf8_output
from content_studio.audit import calls_in
from content_studio.config import CLIENT_SLUG, MCP_TIMEOUT, MCP_URL
from content_studio.harness.conversations import (
    dictated_batch_request,
    dictated_develop,
)
from content_studio.harness.generation import (
    GenerationBatchRequest,
    IdeaTitle,
    detail_prompt,
    title_prompt,
)
from content_studio.harness.generator import (
    GENERATION_MAX_TURNS,
    RUN_TIMEOUT_SECONDS,
    GenerationCoordinator,
    retryable_generation_error,
)
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    GENERATION_VISIBLE_TOOLS,
)
from content_studio.observability import configure_phoenix, shutdown_phoenix
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import read_profile

# `python evals/route/tool_usage.py` puts `evals/route/` on the path, not the
# repo root, so `evals.route.references` is not importable without this. Same
# three lines as `grade.py`, and for the same reason.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.route.references import SHELL_TOOL_NAME, manifest, shell_reads  # noqa: E402

enable_utf8_output()

HERE = Path(__file__).parent
GRID_FILE = HERE / "tool-usage-grid.json"
#: One reports folder for the whole suite, one level up from this group. Every
#: eval writes there whichever subfolder it lives in.
REPORTS = HERE.parent / "reports"
ROOT = HERE.parents[2]

#: The MCP tools a generation run may reach. Anything outside this set is not
#: refused by the eval — it is invisible to the agent, which is the stronger
#: guarantee and the reason this file needs no approval machinery.
DATA_TOOLS = sorted(GENERATION_VISIBLE_TOOLS)

RULE = "─" * 96


def grid() -> dict[str, Any]:
    return json.loads(GRID_FILE.read_text(encoding="utf-8"))


# ---- the labels -------------------------------------------------------------


@dataclass(frozen=True)
class Expectation:
    """What a correct route looks like on one square of the grid."""

    skill: str
    references_required: tuple[str, ...]
    references_forbidden: tuple[str, ...]
    tools_required: tuple[str, ...]
    tools_any_of: tuple[str, ...]
    tools_forbidden: tuple[str, ...]


@dataclass(frozen=True)
class Case:
    id: str
    phase: str
    format: str
    pillar: str
    source: str
    focus: str | None
    dictated: str
    expected: Expectation


def scenario_of(spec: dict[str, Any], phase: str, format: str) -> str:
    """The `references.json` scenario key for one phase and format."""

    phases = spec["phases"]
    if phase == "titluri":
        return phases["titluri"]["scenario"]
    return phases["detalii"]["scenario_by_format"][format]


def references_for(scenario: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(required, forbidden) for this scenario, read out of `references.json`.

    The format half of the method, and it is not copied into the grid file: the
    manifest beside this one already writes it down per scenario, with the
    `forbidden` rows that make a surplus read countable. Anything the manifest
    does not mention for this scenario is optional, which is its own default.
    """

    required: list[str] = []
    forbidden: list[str] = []
    for entry in manifest():
        verdict = (entry.get("expect") or {}).get(scenario)
        if verdict == "required":
            required.append(entry["file"])
        elif verdict == "forbidden":
            forbidden.append(entry["file"])
    return tuple(sorted(required)), tuple(sorted(forbidden))


def expectation(spec: dict[str, Any], phase: str, format: str, source: str) -> Expectation:
    """The two halves of the method, composed: format decides references, source
    decides the shelf and the tool."""

    scenario = scenario_of(spec, phase, format)
    required, forbidden = references_for(scenario)
    rule = spec["sources"][source]
    return Expectation(
        skill=spec["phases"][phase]["skill"],
        references_required=tuple(
            sorted({*required, *rule["references_required"][phase]})
        ),
        references_forbidden=tuple(
            sorted({*forbidden, *rule["references_forbidden"][phase]})
        ),
        tools_required=tuple(rule["tools_required"]),
        tools_any_of=tuple(rule.get("tools_any_of", ())),
        tools_forbidden=tuple(rule["tools_forbidden"]),
    )


def slug(value: str) -> str:
    """A case id a person can type. Diacritics out, spaces to dashes."""

    table = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaissttAAISSTT")
    return "-".join(value.translate(table).lower().split())


def focus_tag(focus: str | None, focuses: list[str | None]) -> str:
    """The focus, as one word in the id.

    The theme itself is too long to sit in a case id and it is the same theme
    every time, so what the id has to carry is whether there was one. Numbered
    rather than named the day a second theme is added to the axis, because two
    squares that differ only in focus must not share an id.
    """

    if focus is None:
        return "fara-focus"
    themes = [f for f in focuses if f is not None]
    return "cu-focus" if len(themes) == 1 else f"focus-{themes.index(focus) + 1}"


def all_cases(spec: dict[str, Any]) -> list[Case]:
    """Every square of the grid: phase × format × pillar × source × focus."""

    idea = spec["idea"]
    cases: list[Case] = []
    for phase in ("titluri", "detalii"):
        for format in spec["axes"]["format"]:
            for pillar in spec["axes"]["pillar"]:
                for source in spec["axes"]["source"]:
                    for focus in spec["axes"]["focus"]:
                        dictated = (
                            dictated_batch_request(format, pillar, source, focus)
                            if phase == "titluri"
                            else dictated_develop(idea["ordinal"], idea["title"])
                        )
                        cases.append(
                            Case(
                                id="-".join(
                                    (
                                        phase,
                                        slug(format),
                                        slug(source),
                                        slug(pillar),
                                        focus_tag(focus, spec["axes"]["focus"]),
                                    )
                                ),
                                phase=phase,
                                format=format,
                                pillar=pillar,
                                source=source,
                                focus=focus,
                                dictated=dictated,
                                expected=expectation(spec, phase, format, source),
                            )
                        )
    return cases


def spine(cases: list[Case]) -> list[Case]:
    """One case per distinct label, with the other two axes rotated through it.

    The label is decided by phase × format × source — twenty-four of them. The
    pillar and the focus change what gets WRITTEN and nothing about which file
    gets opened, so running all five pillars against the same label ten times
    over buys ten identical answers. Rotating them instead keeps every pillar
    and both focus states in the run at a tenth of the bill, and `--all` is
    always there for the day the claim itself is in doubt.
    """

    pillars = sorted({c.pillar for c in cases})
    focuses = sorted({c.focus for c in cases}, key=lambda f: (f is not None, f or ""))
    chosen: list[Case] = []
    seen: set[tuple[str, str, str]] = set()
    for case in cases:
        key = (case.phase, case.format, case.source)
        if key in seen:
            continue
        seen.add(key)
        index = len(chosen)
        wanted_pillar = pillars[index % len(pillars)]
        wanted_focus = focuses[index % len(focuses)]
        chosen.append(
            next(
                c
                for c in cases
                if (c.phase, c.format, c.source) == key
                and c.pillar == wanted_pillar
                and c.focus == wanted_focus
            )
        )
    return chosen


# ---- the run ----------------------------------------------------------------


@dataclass
class Route:
    """What one run actually did, in the three terms the label is written in."""

    skills: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    turns: int = 0
    error: str | None = None


def route_from(result) -> Route:
    """The route of a finished run, out of its own items.

    `calls_in` rather than `RunHooks`: the hooks name the tool but not the
    arguments, and since the method moved into a container the argument IS the
    evidence — a shell call says nothing until you read which file it opened.
    Same source `generator._warn_if_the_method_was_never_opened` reads.
    """

    calls = calls_in(result)
    commands = [
        json.dumps(call.get("arguments") or {}, ensure_ascii=False)
        for call in calls
        if call["name"] == SHELL_TOOL_NAME
    ]
    return Route(
        skills=sorted(
            {
                name
                for command in commands
                for name in ("propune-postari", "dezvolta-postarea")
                if f"{name}/SKILL.md" in command
            }
        ),
        # Counted once per command, exactly as `references.py` counts it off the
        # traces, so a number read here and a number read there mean the same.
        references=sorted(shell_reads(commands)),
        tools=[call["name"] for call in calls if call["name"] in DATA_TOOLS],
        commands=commands,
        turns=len(result.to_input_list()),
    )


async def run_case(
    coordinator: GenerationCoordinator,
    profile_md: str,
    data_mcp: MCPServerStreamableHttp,
    case: Case,
    idea: dict[str, Any],
) -> Route:
    """One real run: production's agent, production's prompt, one container.

    The one thing not taken from production is the return: `_run_agent` hands
    back `final_output_as(...)`, and this file needs the RunResult the route
    lives in. Everything up to that point — builders, container, turn limit,
    run timeout — is the same call a click makes.

    Retried once, and only for what production retries: a broken structured
    contract costs the route without saying anything about the tools, which is
    the eval measuring itself rather than the agent.
    """

    request = GenerationBatchRequest(
        format=case.format, pillar=case.pillar, source=case.source, focus=case.focus
    )
    request = request.model_copy(update={"model": coordinator._batch_model(request)})
    label = f"tool-usage-{case.id}"

    if case.phase == "titluri":
        agent = coordinator._title_agent(profile_md, data_mcp, request, "ro", label)
        prompt = title_prompt(request, profile_md, "ro")
    else:
        agent = coordinator._detail_agent(profile_md, data_mcp, request, "ro", label)
        prompt = detail_prompt(
            request,
            IdeaTitle(
                ordinal=idea["ordinal"], title=idea["title"], angle=idea["angle"]
            ),
            profile_md,
            "ro",
        )

    last: BaseException | None = None
    for attempt in (1, 2):
        try:
            async with sandbox_run_config(label) as sandbox:
                result = await asyncio.wait_for(
                    Runner.run(
                        agent,
                        prompt,
                        run_config=RunConfig(
                            # Our own name, not `workflow_name`: that one is
                            # built for a batch id and truncates to eight
                            # characters, which would put every square of the
                            # grid in Phoenix under "tool-usa".
                            workflow_name=f"Tool usage {case.id}",
                            group_id=label,
                            sandbox=sandbox,
                        ),
                        max_turns=GENERATION_MAX_TURNS,
                    ),
                    timeout=RUN_TIMEOUT_SECONDS,
                )
            return route_from(result)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - one square must not stop the grid
            last = exc
            if attempt == 1 and retryable_generation_error(exc):
                continue
            break
    return Route(error=f"{type(last).__name__}: {last}")


# ---- the verdict ------------------------------------------------------------


def verdict(route: Route, expected: Expectation) -> dict[str, Any]:
    """Three questions, three answers, and the reasons under each.

    Split rather than summed, because they fail for different reasons and get
    fixed in different files: the router is the frontmatter `description`, the
    references are the skill body, and the tools are the source table inside it.
    One number would say a square is wrong without saying where to go.
    """

    missing: list[str] = []
    surplus: list[str] = []

    router_ok = expected.skill in route.skills
    if not router_ok:
        missing.append(f"skill: n-a deschis {expected.skill}/SKILL.md")

    absent = [r for r in expected.references_required if r not in route.references]
    extra = [r for r in expected.references_forbidden if r in route.references]
    if absent:
        missing.append(f"referințe cerute, nedeschise: {absent}")
    if extra:
        surplus.append(f"referințe deschise degeaba: {extra}")

    tools_missing = [t for t in expected.tools_required if t not in route.tools]
    tools_extra = [t for t in expected.tools_forbidden if t in route.tools]
    none_of_any = bool(expected.tools_any_of) and not any(
        t in route.tools for t in expected.tools_any_of
    )
    if tools_missing:
        missing.append(f"unelte cerute, nechemate: {tools_missing}")
    if tools_extra:
        surplus.append(f"unelte din altă sursă: {tools_extra}")
    if none_of_any:
        missing.append(f"niciuna din uneltele sursei: {list(expected.tools_any_of)}")

    if route.error:
        missing.append(f"rularea a eșuat: {route.error}")

    failed = bool(route.error)
    return {
        "router": 0.0 if failed or not router_ok else 1.0,
        "references": 0.0 if failed or absent or extra else 1.0,
        "tools": 0.0 if failed or tools_missing or tools_extra or none_of_any else 1.0,
        "score": 0.0 if missing or surplus else 1.0,
        "missing": missing,
        "surplus": surplus,
    }


# ---- printing ---------------------------------------------------------------


def show_labels(cases: list[Case]) -> None:
    # References last, and unbounded: at Reel there are four of them, and a
    # column that truncates the label is a table that hides the expectation.
    print(f"{'caz':<46}{'skill':<19}{'unelte':<38}referințe cerute")
    print(RULE)
    for case in cases:
        expected = case.expected
        refs = ", ".join(r.split("/")[-1] for r in expected.references_required) or "—"
        tools = ", ".join(expected.tools_required or expected.tools_any_of) or "—"
        if expected.tools_any_of:
            tools = f"oricare din: {tools}"
        print(f"{case.id:<46}{expected.skill:<19}{tools:<38}{refs}")
    print(f"\n{len(cases)} cazuri. Niciun model, niciun container, niciun cost.")


def by_axis(findings: list[dict[str, Any]]) -> None:
    """Where the failures cluster. The whole reason a grid beats six cases."""

    print("\nPe axe:")
    for axis in ("phase", "format", "source", "pillar", "focus"):
        values = sorted({str(f[axis]) for f in findings})
        cells = []
        for value in values:
            rows = [f for f in findings if str(f[axis]) == value]
            passed = sum(1 for f in rows if f["score"] == 1.0)
            cells.append(f"{value}: {passed}/{len(rows)}")
        print(f"  {axis:<8} {'  ·  '.join(cells)}")


# ---- the driver -------------------------------------------------------------


def select(cases: list[Case], args) -> list[Case]:
    if args.ids:
        wanted = set(args.ids)
        unknown = wanted - {c.id for c in cases}
        if unknown:
            raise SystemExit(f"Cazuri necunoscute: {sorted(unknown)}")
        return [c for c in cases if c.id in wanted]
    for axis, chosen in (
        ("phase", args.phase),
        ("format", args.format),
        ("source", args.source),
        ("pillar", args.pillar),
    ):
        if chosen:
            cases = [c for c in cases if getattr(c, axis) in chosen]
    if args.focus == "yes":
        cases = [c for c in cases if c.focus]
    elif args.focus == "no":
        cases = [c for c in cases if not c.focus]
    return cases


async def run_grid(cases: list[Case], spec: dict[str, Any], concurrency: int) -> int:
    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {
                CONVERSATION_HEADER: "tool-usage-grid",
                CLIENT_HEADER: CLIENT_SLUG,
            },
        },
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": DATA_TOOLS},
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    try:
        await data_mcp.connect()
        _, profile_md = await read_profile(data_mcp)
    except Exception as e:  # noqa: BLE001
        print(f"Serverul MCP nu răspunde la {MCP_URL}: {type(e).__name__}: {e}", file=sys.stderr)
        print("  Pornește `uv run content-studio-server` în alt terminal.", file=sys.stderr)
        return 2

    # Built without `__init__` for the same reason `run_like_production.py` does
    # it: a coordinator owns background tasks and MCP factories nothing here
    # wants. The agent builders depend on these two attributes and no more.
    coordinator = GenerationCoordinator.__new__(GenerationCoordinator)
    coordinator._accounts = None
    coordinator._conversations = None

    findings: list[dict[str, Any]] = []
    gate = asyncio.Semaphore(concurrency)
    printed = 0

    async def one(case: Case) -> None:
        nonlocal printed
        async with gate:
            started = time.monotonic()
            route = await run_case(coordinator, profile_md, data_mcp, case, spec["idea"])
        scored = verdict(route, case.expected)
        printed += 1
        mark = "✓" if scored["score"] == 1.0 else "✗"
        print(
            f"{mark} [{printed:>3}/{len(cases)}] {case.id:<46}"
            f"{time.monotonic() - started:>5.0f}s  "
            f"R{scored['router']:.0f} F{scored['references']:.0f} T{scored['tools']:.0f}"
        )
        for reason in scored["missing"] + scored["surplus"]:
            print(f"      {reason}")
        findings.append(
            {
                "case": case.id,
                "phase": case.phase,
                "format": case.format,
                "pillar": case.pillar,
                "source": case.source,
                "focus": case.focus,
                "dictated": case.dictated,
                "expected": {
                    "skill": case.expected.skill,
                    "references_required": list(case.expected.references_required),
                    "references_forbidden": list(case.expected.references_forbidden),
                    "tools_required": list(case.expected.tools_required),
                    "tools_any_of": list(case.expected.tools_any_of),
                    "tools_forbidden": list(case.expected.tools_forbidden),
                },
                "route": {
                    "skills": route.skills,
                    "references": route.references,
                    "tools": route.tools,
                    "turns": route.turns,
                    "commands": route.commands,
                    "error": route.error,
                },
                **{k: scored[k] for k in ("router", "references", "tools", "score")},
                "missing": scored["missing"],
                "surplus": scored["surplus"],
            }
        )

    try:
        await asyncio.gather(*(one(case) for case in cases))
    finally:
        await data_mcp.cleanup()

    findings.sort(key=lambda f: f["case"])
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"tool-usage-{stamp}.json"
    out.write_text(
        json.dumps(
            {"generated_at": stamp, "cases": len(findings), "findings": findings},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    by_axis(findings)
    passed = sum(1 for f in findings if f["score"] == 1.0)

    def rate(key: str) -> str:
        return f"{sum(1 for f in findings if f[key] == 1.0)}/{len(findings)}"

    print(
        f"\ntool_usage: {passed}/{len(findings)}"
        f"  ·  router {rate('router')}  referințe {rate('references')}"
        f"  unelte {rate('tools')}"
        f"  ·  {out.relative_to(ROOT)}"
    )
    return 1 if passed < len(findings) else 0


def main() -> int:
    spec = grid()
    parser = argparse.ArgumentParser(description="tool_usage on the whole domain grid")
    parser.add_argument("--all", action="store_true", help="every square, not the spine")
    parser.add_argument("--dry-run", action="store_true", help="the labels only, free")
    parser.add_argument("--id", dest="ids", action="append", help="one case; repeatable")
    parser.add_argument("--phase", action="append", choices=["titluri", "detalii"])
    parser.add_argument("--format", action="append", choices=spec["axes"]["format"])
    parser.add_argument("--source", action="append", choices=spec["axes"]["source"])
    parser.add_argument("--pillar", action="append", choices=spec["axes"]["pillar"])
    parser.add_argument("--focus", choices=["yes", "no"], help="only with / only without")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="how many containers at once (default 2)",
    )
    args = parser.parse_args()

    everything = all_cases(spec)
    cases = select(everything, args)
    if not (args.all or args.ids):
        full, cases = cases, spine(cases)
        # NO SILENT CAPS. A run that quietly dropped 90% of the grid reads
        # exactly like a run that covered it.
        print(
            f"Coloana vertebrală: {len(cases)} din {len(full)} pătrate — câte unul"
            f" pentru fiecare etichetă distinctă (fază × format × sursă), cu"
            f" pilonul și focusul rotite prin ele.\n"
            f"Restul de {len(full) - len(cases)} au aceeași etichetă ca unul de"
            f" mai jos; `--all` le rulează pe toate.\n"
        )
    if args.dry_run:
        show_labels(cases)
        return 0
    if not cases:
        print("Niciun caz nu se potrivește filtrelor.", file=sys.stderr)
        return 2

    # The spans go to Phoenix like any run's — Neon is the record of what
    # production did, Phoenix the sample the evaluators read, and this is an
    # evaluator. No `runs` row is opened: the record of an eval is its report.
    phoenix = configure_phoenix()
    print(f"phoenix   {phoenix['detail']}")
    try:
        return asyncio.run(run_grid(cases, spec, max(1, args.concurrency)))
    finally:
        shutdown_phoenix()


if __name__ == "__main__":
    raise SystemExit(main())
