"""The ten cases, run for real, so the two search tools can be watched working.

    uv run content-studio-server                            # terminal 1
    uv run python evals/skill/run_cases.py --dry-run        # what would run, free
    uv run python evals/skill/run_cases.py                  # ten real runs. COSTS MONEY.
    uv run python evals/skill/run_cases.py --id d-carti     # one case; repeatable

STEP ONE OF TWO, and the order is the lab's. `Skill.py` runs the agent over a
list of questions first and only then queries the spans it produced; until now
this repository had only the second half, so `relevance.py` graded whatever
traffic happened to exist. This file is the first half: it takes `cases.json`,
runs each case through production's own pipeline, and leaves the spans behind
for `relevance.py` to judge.

WHAT IT ANSWERS BY ITSELF, before any judge is paid: did the two tools work.
For every case it prints each search with what was asked and what came back —
how many characters, or the error. A tool that times out and a tool that returns
nothing relevant are two different faults with two different fixes, and on
2026-08-30 ten of eighteen failures turned out to be the first kind while being
counted as the second.

IT RUNS PRODUCTION'S RUN. `run_case` is imported from `evals/route/tool_usage.py`
rather than rewritten: builders, container, turn limit and run timeout all come
from `GenerationCoordinator`, so what happens here is what happens on a click.
The route verdict is not computed — that question belongs to the other group.

IT WRITES NOTHING. The generation agents see `GENERATION_VISIBLE_TOOLS`, which
is the two search tools and nothing else. No batch, no idea, no `runs` row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.mcp import MCPServerStreamableHttp

from content_studio import enable_utf8_output
from content_studio.config import CLIENT_SLUG, MCP_TIMEOUT, MCP_URL
from content_studio.harness.generator import GenerationCoordinator
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    GENERATION_VISIBLE_TOOLS,
)
from content_studio.observability import configure_phoenix, shutdown_phoenix
from content_studio.worker import read_profile

# Same three lines, same reason, as `tool_usage.py`: running this file as a
# script puts `evals/skill/` on the path and not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.route.tool_usage import Case, Route, run_case  # noqa: E402

enable_utf8_output()

HERE = Path(__file__).parent
CASES_FILE = HERE / "cases.json"
#: One reports folder for the whole suite, one level up from this group — the
#: same one `tool_usage.py` writes to.
REPORTS = HERE.parent / "reports"

#: The MCP tools a generation run may reach, exactly as the route grid defines
#: them. Anything outside this set is invisible to the agent.
DATA_TOOLS = sorted(GENERATION_VISIBLE_TOOLS)

RULE = "─" * 96

#: A tool result shorter than this is an error message, not material. Measured
#: on the spans of 2026-08-30: the MCP timeout arrives as 97 characters and the
#: 429 as 289. It was 600 that same day, on a sample whose shortest real answer
#: was over 4,000 - and the experiment run of 2026-08-30 17:10 produced a
#: genuine 390-character `search_web` answer (four usable Romanian phrases for
#: refusing an invitation), which 600 would have printed as a failed call. The
#: floor belongs just above the largest error seen, not just below the smallest
#: answer seen: one of those two numbers is bounded by the tool and the other by
#: whatever happened to be measured.
SHORT_RESULT = 320


def cases() -> tuple[list[Case], dict[str, Any]]:
    """The manifest, in the same `Case` shape the route grid runs.

    `expected` is left empty on purpose: that field carries the route label, and
    this file asks nothing about the route. Half-filling it here is how two
    manifests start disagreeing.
    """

    spec = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    built = [
        Case(
            id=case["id"],
            phase=case["phase"],
            format=case["format"],
            pillar=case["pillar"],
            source=case["source"],
            focus=case["focus"],
            expected=None,
            dictated="",
        )
        for case in spec["cases"]
    ]
    return built, spec


# ---- what one search did ----------------------------------------------------


def summarise(search: dict[str, Any]) -> tuple[bool, int, str]:
    """One search, as worked/failed, a size, and the line worth printing.

    The result arrives as the tool's own text. All that is needed here is
    whether it is material or a failure, and the length separates the two
    cleanly enough that parsing the JSON would buy nothing.
    """

    raw = search.get("result")
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    text = text or ""
    worked = len(text) >= SHORT_RESULT
    shown = (search.get("arguments") or {}).get("description") if worked else text
    return worked, len(text), " ".join((shown or "").split())[:104]


# ---- the run ----------------------------------------------------------------


def show(case: Case, route: Route, seconds: float, index: int, total: int) -> dict[str, Any]:
    """One case's line, then one line per search under it."""

    if route.error:
        print(f"✗ [{index:>2}/{total}] {case.id:<24} {seconds:>5.0f}s  RULARE PICATĂ")
        print(f"        {route.error}")
    else:
        print(
            f"  [{index:>2}/{total}] {case.id:<24} {seconds:>5.0f}s  "
            f"{case.phase}/{case.format}/{case.pillar}/{case.source}"
            f"  focus: {case.focus or '—'}"
        )
        if not route.searches:
            print("        (nicio căutare)")
    for search in route.searches:
        worked, size, line = summarise(search)
        mark = "✓" if worked else "✗"
        print(f"        {mark} {search['tool']:<13} {size:>7} car  {line}…")

    return {
        "case": case.id,
        "phase": case.phase,
        "format": case.format,
        "pillar": case.pillar,
        "source": case.source,
        "focus": case.focus,
        "seconds": round(seconds, 1),
        "error": route.error,
        "tools": route.tools,
        "searches": [
            {
                "tool": search["tool"],
                "arguments": search["arguments"],
                "returned_chars": summarise(search)[1],
                "worked": summarise(search)[0],
            }
            for search in route.searches
        ],
    }


# ---- the tally --------------------------------------------------------------


def report(findings: list[dict[str, Any]]) -> None:
    """Per tool: called how many times, answered how many. Then the report file."""

    print(f"\n{RULE}")
    searches = [s for f in findings for s in f["searches"]]
    for tool in DATA_TOOLS:
        mine = [s for s in searches if s["tool"] == tool]
        if not mine:
            print(f"{tool:<15} niciun apel")
            continue
        worked = sum(s["worked"] for s in mine)
        print(f"{tool:<15} {worked}/{len(mine)} apeluri au întors material")

    failed = [f for f in findings if f["error"]]
    if failed:
        print(f"\nRulări picate: {len(failed)} — {', '.join(f['case'] for f in failed)}")
    # A run that searched nothing leaves nothing for the judge, so it shrinks
    # the sample without ever showing up as a low score.
    quiet = [f for f in findings if not f["error"] and not f["searches"]]
    if quiet:
        print(f"Rulări fără nicio căutare: {len(quiet)} — {', '.join(f['case'] for f in quiet)}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = REPORTS / f"skill-cases-{stamp}.json"
    path.write_text(
        json.dumps(
            {"generated_at": datetime.now(UTC).isoformat(), "findings": findings},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nRaport: {path}")
    print(
        "Pasul doi, pe span-urile tocmai produse:\n"
        "  uv run python evals/skill/relevance.py --minutes 60"
    )


async def run_all(chosen: list[Case], spec: dict[str, Any], concurrency: int) -> int:
    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {
                CONVERSATION_HEADER: "skill-cases",
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

    # Built without `__init__` for the same reason `tool_usage.run_grid` does it:
    # a coordinator owns background tasks and MCP factories nothing here wants.
    # The agent builders depend on these two attributes and no more.
    coordinator = GenerationCoordinator.__new__(GenerationCoordinator)
    coordinator._accounts = None
    coordinator._conversations = None

    findings: list[dict[str, Any]] = []
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(case: Case) -> None:
        nonlocal done
        async with gate:
            started = time.monotonic()
            route = await run_case(coordinator, profile_md, data_mcp, case, spec["idea"])
        done += 1
        findings.append(show(case, route, time.monotonic() - started, done, len(chosen)))

    try:
        await asyncio.gather(*(one(case) for case in chosen))
    finally:
        await data_mcp.cleanup()

    order = {case.id: i for i, case in enumerate(chosen)}
    findings.sort(key=lambda finding: order[finding["case"]])
    report(findings)
    return 0


def main() -> int:
    chosen, spec = cases()
    parser = argparse.ArgumentParser(description="run the ten skill cases for real")
    parser.add_argument("--dry-run", action="store_true", help="what would run, free")
    parser.add_argument("--id", dest="ids", action="append", help="one case; repeatable")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="how many containers at once (default 2)",
    )
    args = parser.parse_args()

    if args.ids:
        unknown = set(args.ids) - {case.id for case in chosen}
        if unknown:
            raise SystemExit(f"Cazuri necunoscute: {sorted(unknown)}")
        chosen = [case for case in chosen if case.id in args.ids]

    print(f"{len(chosen)} cazuri\n{RULE}")
    for i, case in enumerate(chosen, 1):
        print(
            f"  {i:>2}. {case.id:<24} {case.phase}/{case.format}/{case.pillar}/"
            f"{case.source}  focus: {case.focus or '—'}"
        )
    print(RULE)
    if args.dry_run:
        return 0

    configure_phoenix()
    try:
        return asyncio.run(run_all(chosen, spec, args.concurrency))
    finally:
        shutdown_phoenix()


if __name__ == "__main__":
    raise SystemExit(main())
