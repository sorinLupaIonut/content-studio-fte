"""Metric `convergence` — one request said ten ways, and the path each one took.

    uv run content-studio-server                              # terminal 1
    uv run python evals/path/convergence.py --dry-run         # the ten, free
    uv run python evals/path/convergence.py                   # ten chat turns. COSTS MONEY.
    uv run python evals/path/convergence.py --id telegrafic   # one; repeatable

THE COURSE'S LAB 4, ADAPTED. `Trajectory.py` asks seventeen wordings of one
question, records how many steps each answer took, calls the SHORTEST one
optimal, and scores every run `optimal / its own length`. A stable agent walks
the same path however the question is phrased; one that wanders scores below 1
and the number says by how much.

WHY CHAT AND NOT GENERATION. The test needs a question said several ways, and
the studio has exactly one free-text surface. A button sends a structured
`GenerationBatchRequest` — the same four fields every time — so repeating a
generation run measures variance, not convergence.

THE ANCHOR IS THE DICTATED SENTENCE, AND IT IS NOT IN THE MANIFEST. AGENTS.md
says a button press is dictation, and that the sentence a button dictates,
typed by hand, must behave identically. That is a convergence claim, written
into the contract and never measured until this file. `dictated_batch_request`
builds it here at run time from the same function the buttons call, so the
manifest holds no second copy of a string the contract owns.

TWO NUMBERS, BOTH FREE. No judge is called and nothing is paid beyond the runs
themselves:

  · **convergence** — `optimal / turns`, the course's own score.
  · **agreement**   — did the turn record `start_generation` with exactly the
                      request every phrasing was written to mean? A path of
                      equal length that lands on the wrong pillar is not
                      convergence, and length alone cannot tell you.

Agreement is reported beside convergence rather than folded into it, because
they break for different reasons: a long path is a model that dithered, a wrong
argument is a model that misread her.

NOTHING RUNS AFTERWARDS. `Runner.run` is called directly, with no orchestrator
attached, so a recorded intent stays recorded: no batch is created, no idea is
written, no `runs` row is opened. The trigger tools are ungated by design (they
make drafts), and the one gated tool a chat turn can reach is `save_post`,
which a request for ten ideas has no reason to touch — an interruption is
reported as a failed path rather than answered.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents import ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig

from content_studio import enable_utf8_output
from content_studio.audit import calls_in
from content_studio.config import CHAT_MODEL, CLIENT_SLUG, MCP_TIMEOUT, MCP_URL
from content_studio.harness.chat import (
    CHAT_MAX_TURNS,
    CHAT_TIMEOUT_SECONDS,
    ChatTurnOutput,
    chat_prompt,
    trigger_calls,
)
from content_studio.harness.conversations import dictated_batch_request
from content_studio.harness.generator import METHOD_MARKERS
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    MODEL_VISIBLE_TOOLS,
    OWNER_HEADER,
)
from content_studio.observability import configure_phoenix, shutdown_phoenix
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import build_worker, read_profile

# Same three lines, same reason, as `tool_usage.py` and `run_cases.py`: running
# this file as a script puts `evals/path/` on the path and not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

enable_utf8_output()

HERE = Path(__file__).parent
PHRASINGS_FILE = HERE / "phrasings.json"
#: One reports folder for the whole suite, one level up from this group.
REPORTS = HERE.parent / "reports"

#: The chat agent's own settings, copied from `ChatCoordinator._run_in_sandbox`.
#: A different effort or a different ceiling would change the path length, which
#: is the thing being measured.
CHAT_SETTINGS = ModelSettings(
    reasoning={"effort": "low"}, verbosity="low", max_tokens=12_000
)

#: The tool this eval expects every phrasing to reach.
TRIGGER = "start_generation"

#: `start_generation` calls `owner_of(ctx)` and throws away the answer - the
#: comment there says it plainly: "The identity is enforced, not used." Without
#: the header the tool refuses, and a refusal would change the path of all ten
#: runs, which is the one thing this eval must not let happen. So a named eval
#: principal rather than a borrowed real one: any non-empty value behaves
#: identically for this tool, and nothing downstream is executed to care.
EVAL_PRINCIPAL = "eval-convergence"

RULE = "─" * 96


@dataclass
class Phrasing:
    id: str
    text: str
    why: str | None = None


@dataclass
class Walk:
    """What one phrasing actually did."""

    turns: int = 0
    intent: dict[str, Any] | None = None
    accepted: bool = False
    reply: str = ""
    error: str | None = None
    tools: list[str] = field(default_factory=list)
    #: Did this turn actually open the method, or answer from memory? The
    #: course's metric calls the SHORTEST path optimal, and in this project that
    #: assumption can be false: the named failure mode is a model that never
    #: opens SKILL.md and writes something plausible instead. A seven-step run
    #: that skipped the method is not better than an eight-step one that read it.
    opened_method: bool = False


def manifest() -> tuple[list[Phrasing], dict[str, str]]:
    """The ten, with the dictated sentence built rather than read, and first."""

    spec = json.loads(PHRASINGS_FILE.read_text(encoding="utf-8"))
    request = spec["request"]
    dictated = Phrasing(
        id="dictat",
        text=dictated_batch_request(
            format=request["format"],
            pillar=request["pillar"],
            source=request["source"],
            focus=request["focus"],
        ),
        why="The anchor: exactly what the button sends. Built, not copied.",
    )
    rest = [Phrasing(id=p["id"], text=p["text"], why=p.get("why")) for p in spec["phrasings"]]
    return [dictated, *rest], request


# ---- the run ----------------------------------------------------------------


async def walk(
    profile_md: str, data_mcp: MCPServerStreamableHttp, phrasing: Phrasing
) -> Walk:
    """One chat turn, built the way `ChatCoordinator` builds one.

    `Runner.run` rather than `run_streamed`: the streaming half exists to push
    deltas at a browser, and nothing here is watching. Everything that decides
    the path — the agent, the prompt, the model, the settings, the turn ceiling
    and the container — is the coordinator's.

    No session is passed. Each phrasing is a first message in an empty
    conversation, which is what makes the ten comparable; sharing a session
    would let phrasing four answer out of phrasing three's history.
    """

    agent = build_worker(
        profile_md,
        data_mcp,
        model=CHAT_MODEL,
        output_type=ChatTurnOutput,
        language="ro",
        model_settings=CHAT_SETTINGS,
    )
    try:
        async with sandbox_run_config(f"convergence-{phrasing.id}") as sandbox:
            result = await asyncio.wait_for(
                Runner.run(
                    agent,
                    chat_prompt(phrasing.text, None, "ro"),
                    run_config=RunConfig(
                        workflow_name=f"Convergence {phrasing.id}",
                        group_id="convergence",
                        sandbox=sandbox,
                    ),
                    max_turns=CHAT_MAX_TURNS,
                ),
                timeout=CHAT_TIMEOUT_SECONDS,
            )
    except asyncio.CancelledError:
        raise
    except BaseException as exc:  # noqa: BLE001 - one phrasing must not stop the ten
        return Walk(error=f"{type(exc).__name__}: {exc}")

    if result.interruptions:
        # A gated tool was reached. Nothing here can answer it, and a suspended
        # run has no path length worth comparing.
        return Walk(error="asked for approval at the gate")

    intent, accepted = None, False
    for name, arguments, output in trigger_calls(result):
        if name != TRIGGER:
            continue
        intent, accepted = arguments, '"accepted"' in output

    commands = json.dumps(
        [call.get("arguments") or {} for call in calls_in(result)], ensure_ascii=False
    )
    return Walk(
        # `to_input_list` is the whole history of the turn, which is what
        # `Trajectory.py` counts. Same measure `tool_usage.py` calls `turns`.
        turns=len(result.to_input_list()),
        intent=intent,
        accepted=accepted,
        reply=getattr(result.final_output, "reply", "") or "",
        tools=[name for name, _, _ in trigger_calls(result)],
        opened_method=any(marker in commands for marker in METHOD_MARKERS),
    )


# ---- the two scores ---------------------------------------------------------


def plain(text: str) -> str:
    """Case-folded and stripped of diacritics.

    ONLY FOR THE FOCUS, and the first run of this eval is why. `fara-diacritice`
    types "limite fara vinovatie" from a phone, the tool records exactly that,
    and a byte comparison called it a disagreement — punishing the one behaviour
    the tool description demands ("nu inventa un focus"). The focus is her own
    words passing through; the three enum axes are a closed vocabulary and stay
    an exact match, because there a near miss IS a miss.
    """

    folded = unicodedata.normalize("NFD", text.strip().casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


#: Words in a focus that carry no topic. Kept tiny on purpose: this is a
#: containment test, not a language model.
STOPWORDS = frozenset({"fara", "de", "a", "si", "cu", "la", "in", "pe", "sa"})


def survived(focus: str | None, wanted: str) -> bool:
    """Did the topic reach the tool at all — however she happened to say it?

    NOT an equality test, and the second run of this eval is why. `cu-voce-tare`
    says "reels despre cum să pui limite fără să te simți vinovată": there is no
    label, only a sentence. Twice out of four the topic was dropped entirely
    (`focus: None`), and once it came through in her own words. Compared to the
    canonical string both read as the same failure — but only the first one IS
    one. The tool's own description says "nu inventa un focus", so passing her
    wording through is the behaviour being asked for, and a metric that fails it
    is teaching the wrong lesson.

    So: at least one content word of the wanted topic has to appear. Loose - a
    focus of "limite de timp la muncă" would pass on "limite" alone - and that
    is the honest edge of a check that costs no model call. Tightening it means
    a judge, and this whole eval exists to be the free one.
    """

    if not focus:
        return False
    got = plain(focus)
    stems = [w for w in plain(wanted).split() if w not in STOPWORDS]
    return any(stem in got for stem in stems)


def agrees(intent: dict[str, Any] | None, request: dict[str, str]) -> tuple[bool, list[str]]:
    """Did the turn record the request every phrasing was written to mean?

    The three enum axes are a closed vocabulary, so a near miss IS a miss and
    they stay an exact match. The focus is free text she typed, and it is judged
    by `survived` instead.
    """

    if intent is None:
        return False, ["did not call start_generation"]
    wrong = []
    for axis in ("format", "pillar", "source"):
        got = intent.get(axis)
        if got != request[axis]:
            wrong.append(f"{axis}: {got!r} instead of {request[axis]!r}")
    if not survived(intent.get("focus"), request["focus"]):
        wrong.append(f"focus pierdut: {intent.get('focus')!r}")
    return not wrong, wrong


def report(findings: list[dict[str, Any]], request: dict[str, str]) -> int:
    """The course's score, the agreement beside it, and the report file."""

    walked = [f for f in findings if f["turns"]]
    if not walked:
        # NEVER PRINT A SCORE THAT COULD NOT BE COMPUTED. An optimal of zero
        # would make every convergence 0.0, which reads exactly like ten runs
        # that all wandered.
        print("\nNo path to measure — every phrasing failed.", file=sys.stderr)
        return 1

    # THE OPTIMUM IS THE CHEAPEST CORRECT PATH, NOT THE CHEAPEST PATH.
    # `Trajectory.py` takes `min(path_length)` outright, and it can: every run
    # in it ends at the same SQL answer, so a shorter one is simply a better
    # one. Here it is not. Measured 2026-08-30, third run of this file:
    # `porunca-scurta` finished in six steps by never calling
    # `start_generation` at all — it replied and stopped. That set `optimal = 6`
    # and scored every honest run 0.750 against a run that did nothing. So the
    # floor is taken over the paths that agreed; if none did, there is no
    # optimum to divide by and the score is refused rather than invented.
    correct = [f for f in walked if f["agreement"]]
    if not correct:
        print(
            "\nNo path recorded the request — there is no optimum to"
            " divide by. Convergence cannot be computed.",
            file=sys.stderr,
        )
        return 1
    optimal = min(f["turns"] for f in correct)
    print(f"\n{RULE}")
    print(
        f"Shortest CORRECT path: {optimal} steps, out of the {len(correct)}"
        f" that recorded the request. Score = {optimal} / your steps.\n"
    )
    print(f"{'phrasing':<18}{'steps':>6}{'convergence':>14}{'method':>9}   agreement")
    print(f"{'-' * 96}")
    for finding in findings:
        if not finding["turns"]:
            print(f"{finding['id']:<18}{'—':>6}{'—':>14}{'—':>9}   {finding['error']}")
            continue
        # Capped at 1.0: a run that agreed cannot beat the optimum by
        # construction, but a run that did NOT agree can be shorter than it, and
        # letting that print 1.200 would make the worst outcome look the best.
        finding["convergence"] = round(min(optimal / finding["turns"], 1.0), 3)
        mark = "✓" if finding["agreement"] else "✗ " + "; ".join(finding["wrong"])
        print(
            f"{finding['id']:<18}{finding['turns']:>6}"
            f"{finding['convergence']:>14.3f}"
            f"{'da' if finding['opened_method'] else 'NU':>9}   {mark}"
        )

    scores = [f["convergence"] for f in findings if f.get("convergence") is not None]
    agreed = sum(1 for f in findings if f["agreement"])
    print(f"\n{RULE}")
    print(f"convergence    mean {sum(scores) / len(scores):.3f} over {len(scores)} paths")
    print(f"agreement      {agreed}/{len(findings)} recorded exactly the request")
    blind = [f["id"] for f in walked if not f["opened_method"]]
    if blind:
        # THE SHORTEST PATH IS NOT AUTOMATICALLY THE BEST ONE HERE. Trajectory.py
        # can assume it because every path in it ends at the same SQL answer.
        # This project's named failure mode is a model that never opens the
        # method and answers plausibly from memory - and that run is SHORTER, so
        # it would set `optimal` and score 1.000 while every honest run scored
        # below it. Printed, never folded into the score: what to do about it is
        # a decision, not an arithmetic.
        print(f"no method      {len(blind)} — {', '.join(blind)}  (a short path for a bad reason)")
    if len(walked) < len(findings):
        print(f"picate         {len(findings) - len(walked)}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = REPORTS / f"convergence-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "model": CHAT_MODEL,
                "request": request,
                "optimal_turns": optimal,
                "findings": findings,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nRaport: {path}")
    return 0


async def run_all(chosen: list[Phrasing], request: dict[str, str], concurrency: int) -> int:
    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {
                CONVERSATION_HEADER: "convergence",
                CLIENT_HEADER: CLIENT_SLUG,
                OWNER_HEADER: EVAL_PRINCIPAL,
            },
        },
        name="content-data",
        cache_tools_list=True,
        # The chat agent's own tool set, not generation's: the trigger tools
        # only exist here, and they are what the whole eval watches for.
        tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
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

    findings: list[dict[str, Any]] = []
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(phrasing: Phrasing) -> None:
        nonlocal done
        async with gate:
            started = time.monotonic()
            result = await walk(profile_md, data_mcp, phrasing)
        done += 1
        agreement, wrong = agrees(result.intent, request)
        seconds = time.monotonic() - started
        mark = "✗" if result.error else ("✓" if agreement else "~")
        print(
            f"{mark} [{done:>2}/{len(chosen)}] {phrasing.id:<18}{seconds:>5.0f}s  "
            f"{result.turns:>3} steps  {result.error or ''}"
        )
        findings.append(
            {
                "id": phrasing.id,
                "text": phrasing.text,
                "seconds": round(seconds, 1),
                "turns": result.turns,
                "intent": result.intent,
                "accepted": result.accepted,
                "tools": result.tools,
                "opened_method": result.opened_method,
                "agreement": agreement,
                "wrong": wrong,
                "convergence": None,
                "error": result.error,
            }
        )

    try:
        await asyncio.gather(*(one(p) for p in chosen))
    finally:
        await data_mcp.cleanup()

    order = {p.id: i for i, p in enumerate(chosen)}
    findings.sort(key=lambda finding: order[finding["id"]])
    return report(findings, request)


def main() -> int:
    chosen, request = manifest()
    parser = argparse.ArgumentParser(description="convergence over ten phrasings")
    parser.add_argument("--dry-run", action="store_true", help="the ten, free")
    parser.add_argument("--id", dest="ids", action="append", help="one; repeatable")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="how many containers at once (default 3)",
    )
    args = parser.parse_args()

    if args.ids:
        unknown = set(args.ids) - {p.id for p in chosen}
        if unknown:
            raise SystemExit(f"Unknown phrasings: {sorted(unknown)}")
        chosen = [p for p in chosen if p.id in args.ids]

    wanted = ", ".join(f"{k}={v}" for k, v in request.items())
    print(f"The same request, {len(chosen)} phrasings — {wanted}\n{RULE}")
    for i, phrasing in enumerate(chosen, 1):
        print(f"  {i:>2}. {phrasing.id:<18} {phrasing.text}")
    print(RULE)
    if args.dry_run:
        return 0

    configure_phoenix()
    try:
        return asyncio.run(run_all(chosen, request, args.concurrency))
    finally:
        shutdown_phoenix()


if __name__ == "__main__":
    raise SystemExit(main())
