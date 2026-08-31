"""End-to-end check of the CHAT door: the interview, the trigger, the refusal.

Needs the server running:  uv run content-studio-server

WHAT THIS CHECK IS FOR, AND WHY IT IS SHORTER THAN IT WAS.

It used to walk nine turns ending in a saved post, because until 2026-08-27 the
conversation *was* the product: the agent asked three questions, wrote ten
proposals with five hooks each, developed one and saved it. None of that is true
now. The chat agent records an INTENT — `start_generation` — and the harness runs
the same pipeline the buttons run. `start_generation`'s own docstring says it in
two places: „Cărțile nu se aleg aici: motorul își alege singur titlurile" and „NU
scrii tu cele zece idei".

So a conversation driven through `worker.py` alone can no longer reach a write,
by design, and the old assertions failed for that reason rather than because
anything was broken — found on 2026-08-30 by running it, rewritten on 2026-08-31.
What each dropped check proved, and where that proof lives now:

  · ten proposals, five hooks each   → `evals/experiment.py` (`router`,
                                        `references`, `tools`) and
                                        `evals/route/tool_usage.py`
  · the gate both ways, one draft    → `tests/checks/safe/write_gate.py`, which
                                        proves refused → `capability_blocked` and
                                        approved → row + trail row, for free and
                                        without a model
  · one real batch, button-side      → `tests/checks/paid/run_like_production.py`

What is left is what NOTHING ELSE checks: that the conversation itself behaves,
end to end, against real MCP, a real container and a real model.

FIVE TURNS, each proving one thing the method actually says today:

  1. „vreau ceva despre limite"   → asks for the format. It does not assume one.
  2. „reel"                        → asks for the pillar, with the closed
                                     vocabulary of five and no invented sixth.
  3. „conexiune"                   → asks for the source, all four.
  4. „din cărți"                   → calls `start_generation` and says the batch
                                     is starting. It must NOT write the ten
                                     ideas, and must NOT show her the shelf.
  5. „dezvoltă a treia…"           → THE REFUSAL. There is no list in this
                                     conversation, because nothing executed the
                                     trigger. Both skill descriptions say the
                                     same thing in that case: say you do not have
                                     the list, and do not invent one. An agent
                                     that helpfully makes up a third proposal
                                     here is the exact failure this door was
                                     redesigned to prevent.

Turn 4 is also what proves the method was READ: „nu scrii tu lista" is in the
skill body and in the tool's description, nowhere in the system prompt. Turn 5 is
the same evidence from the other side.

Nothing is written to `posts` in this flow. The check asserts that, and deletes
anything it finds anyway, so it stays repeatable.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time

from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import (
    CAPABILITY_BLOCKED,
    CAPABILITY_INVOKED,
    GENERATION_REQUESTED,
    MESSAGE_RECEIVED,
    RUN_COMPLETED,
    SKILL_ACTIVATED,
    Audit,
    split_event,
)
from content_studio.config import MCP_TIMEOUT, MCP_URL, database_url
from content_studio.mcp_server.protocol import (
    CONVERSATION_HEADER,
    MODEL_VISIBLE_TOOLS,
    OWNER_HEADER,
)
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import (
    GATED_TOOLS,
    build_worker,
    open_session,
    read_profile,
    run_turn,
)

enable_utf8_output()

TURNS = [
    "vreau ceva despre limite",
    "reel",
    "conexiune",
    "din cărți",
    "dezvoltă a treia, cu contrastul",
]

#: Turn 4 must start the batch. This is the whole chat door in one tool name.
TRIGGER_TOOL = "start_generation"

#: WHO THIS CONVERSATION IS, and it has to be someone.
#:
#: The three trigger tools refuse a connection with no owner header — „unealta e
#: disponibilă numai din interfața Studio, unde identitatea este verificată" —
#: and that refusal is correct: the harness executes under the principal it
#: authenticated, never one the model could name.
#:
#: The first run of this check did not set it, and the result was worth keeping:
#: both triggers refused, and the model did the work ITSELF rather than stop —
#: „develop_idea nu e disponibil aici, așa că îți trimit eu varianta". Read
#: quickly that looks like the agent ignoring „nu scrii tu lista". It is the
#: opposite: the tool told it the tool did not apply here, and it fell back
#: exactly as the error message suggests. A check that drives the chat door has
#: to stand where the studio stands, or it measures a door nobody uses.
#:
#: A name of its own rather than a real principal: `client_of` finds no such row
#: in `app_users` and falls back to `CLIENT_SLUG`, so the conversation reads the
#: same data the terminal always did, and no real account is touched.
CHECK_PRINCIPAL = "full-flow-check"

#: Any percentage is an invented result unless it counts the post's own points.
#: This catches the obvious class ("30% more time"), not the sly one ("30 minutes
#: of breathing room"). It prints for a human rather than failing the check.
PERCENT_PATTERN = re.compile(r"\d\s*%|\bla sută\b", re.IGNORECASE)

#: „dacă nu răspunzi, folosesc X" — the method forbids choosing for her.
DEFAULT_OPTION_PATTERN = re.compile(
    r"dac[ăa] nu r[ăa]spunzi|folosesc implicit|implicit[,:]", re.IGNORECASE
)

NUMBERING_PATTERN = re.compile(r"^\s*(\d{1,2})[.)]", re.MULTILINE)

#: What „nu am lista" sounds like, tolerant of how the model phrases it. Turn 5
#: has to say some version of this; the alternative is that it invented a third
#: proposal, which is the failure mode this door exists to prevent.
NO_LIST_PATTERN = re.compile(
    r"nu (am|exist[ăa]|s-a generat)|nu (e|este) (nicio |niciun )?(list[ăa]|lot)"
    r"|nu v[ăa]d (o )?list[ăa]|lista nu|niciun lot|nu au ap[ăa]rut|[îi]nc[ăa] nu",
    re.IGNORECASE,
)


def numbers_in(text: str) -> set[int]:
    """The proposal numbers 1–10 found at the start of a line."""
    return {int(n) for n in NUMBERING_PATTERN.findall(text) if 1 <= int(n) <= 10}


def tools_called(result) -> list[str]:
    """The names of the tools called in this turn.

    This looks at the actual calls, not at the text: an agent that *says* it
    started the batch and one that really did look identical in the answer.
    """
    names = []
    for item in result.new_items:
        raw = getattr(item, "raw_item", None)
        if getattr(item, "type", "") == "tool_call_item" and hasattr(raw, "name"):
            names.append(raw.name)
    return names


class Gatekeeper:
    """The human at the gate. Nothing in this flow should ever reach it.

    The three trigger tools are deliberately not gated — they make drafts, and
    rule 6's one confirmation stays on saving a post. So a request arriving here
    means the agent reached for a write it had no business reaching for, and the
    check refuses it and says so.
    """

    def __init__(self) -> None:
        self.requests: list[str] = []

    async def __call__(self, name: str, arguments: dict) -> tuple[bool, str]:
        self.requests.append(name)
        print(f"   [gate: {name} → REFUSED — nothing in this flow should write]")
        return False, "Viorela n-a cerut nicio salvare aici."


async def session_drafts_and_delete(session_id: str) -> list[dict]:
    """What this session wrote into `posts` — expected empty — then clean up.

    The audit trail stays on purpose, so replay can reconstruct the check.
    """
    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            rows = await raw.fetch(
                """SELECT id, title, hook_type, source
                     FROM public.posts
                    WHERE status = 'draft' AND conversation_id = $1""",
                session_id,
            )
            written = [dict(r) | {"id": str(r["id"])} for r in rows]
            for r in written:
                await raw.execute("DELETE FROM public.posts WHERE id = $1::uuid", r["id"])
        return written
    finally:
        await engine.dispose()


TRAIL_SQL = """
SELECT a.event
  FROM public.audit_log a
  JOIN public.runs      r ON r.id = a.run_id
 WHERE r.session_id = $1
 ORDER BY a.id
"""


async def session_events(session_id: str) -> list[tuple[str, str]]:
    """Every (kind, subject) written for this session's runs, in order.

    Since D4 the trail hangs off `runs`, so the session is reached through the
    join rather than through a column of its own.
    """
    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            rows = await raw.fetch(TRAIL_SQL, session_id)
        return [split_event(r["event"]) for r in rows]
    finally:
        await engine.dispose()


def capabilities_in(events: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(capability, status), to tell refused apart from executed."""
    return [
        (subject, "blocked" if kind == CAPABILITY_BLOCKED else "ok")
        for kind, subject in events
        if kind in (CAPABILITY_INVOKED, CAPABILITY_BLOCKED) and subject
    ]


async def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing.", file=sys.stderr)
        return 1

    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args)
    session_id = await open_session(engine, new=True)
    async with engine.begin() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        book_titles = [
            r["title"]
            for r in await raw.fetch(
                "SELECT title FROM public.documents WHERE source = 'library' ORDER BY title"
            )
        ]
    await engine.dispose()

    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {
                CONVERSATION_HEADER: session_id,
                OWNER_HEADER: CHECK_PRINCIPAL,
            },
        },
        name="content-data",
        tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
        require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
    )
    try:
        await data_mcp.connect()
        _, profile_md = await read_profile(data_mcp)
    except Exception as e:  # noqa: BLE001
        print(f"Nothing answers at {MCP_URL} ({type(e).__name__}).", file=sys.stderr)
        print("Start it:  uv run content-studio-server", file=sys.stderr)
        return 1

    worker = build_worker(profile_md, data_mcp)
    trail = Audit(url, connect_args)
    gatekeeper = Gatekeeper()

    print(f"Profile: {len(profile_md):,} characters · {len(book_titles)} books")
    print(f"Session: {session_id}\n")

    history: list = []
    answers: list[str] = []
    per_turn_tools: list[list[str]] = []

    # ONE CONTAINER FOR ALL THE TURNS, and it is not optional. The worker has
    # been a `SandboxAgent` since the method went back into a sandbox on
    # 2026-08-27; `Runner.run` refuses outright without `RunConfig(sandbox=...)`.
    # This file kept the bare `RunConfig()` it was written with and had been
    # dead ever since - found on 2026-08-30, by running it. Every production
    # caller (`chat.py`, `generator.py`, `service.py`) passes one, so nothing
    # the client uses was affected; what was lost is the only check that walks
    # the conversation end to end.
    try:
        async with sandbox_run_config("full_flow") as sandbox:
            config = RunConfig(
                workflow_name=f"Full flow {session_id[:16]}",
                group_id=session_id,
                sandbox=sandbox,
            )
            for message in TURNS:
                t0 = time.monotonic()
                run_id = await trail.open_run(session_id, message)
                print(f"tu> {message}")

                result = await run_turn(
                    worker,
                    history + [{"role": "user", "content": message}],
                    None,
                    config,
                    trail,
                    run_id,
                    gatekeeper,
                )

                history = result.to_input_list()
                answer = str(result.final_output)
                answers.append(answer)
                tools = tools_called(result)
                per_turn_tools.append(tools)

                await trail.turn(run_id, result)
                await trail.close_run(run_id, answer)

                print(f"   ({time.monotonic() - t0:.0f}s)")
                if tools:
                    print(f"   [tools: {', '.join(tools)}]")
                print(f"worker> {answer}\n")
                print("-" * 72)
    finally:
        await data_mcp.cleanup()
        await trail.close()

    print()
    print("=" * 72)
    mistakes = 0

    def check(passed: bool, label: str) -> None:
        nonlocal mistakes
        mistakes += not passed
        print(f"{'✓' if passed else '✗'} {label}")

    called = [name for turn in per_turn_tools for name in turn]

    # ---- turns 2 and 3: the closed vocabularies ------------------------------
    # Written in the skill body and nowhere else. An agent answering from memory
    # renames a pillar or invents a sixth.
    required_pillars = ("Poziționare", "Educație", "Conexiune", "Conversie", "Magnetism")
    check(
        all(p in answers[1] for p in required_pillars) and "Inspirație" not in answers[1],
        "turn 2 offers exactly the closed vocabulary of the 5 pillars",
    )
    required_sources = ("Cărți", "Internet", "Memorie", "Combinat")
    check(
        all(s in answers[2] for s in required_sources),
        "turn 3 offers all 4 sources",
    )

    # ---- turn 4: the trigger, and the two things it must NOT do --------------
    check(
        TRIGGER_TOOL in per_turn_tools[3],
        f"turn 4 called `{TRIGGER_TOOL}` (tools: {per_turn_tools[3] or '—'})",
    )
    proposals = numbers_in(answers[3])
    check(
        len(proposals) < 8,
        f"turn 4 did not write the ten ideas itself: {len(proposals)} numbers found",
    )
    # „Nu-i arăți lista și nu-i ceri să aleagă din ea" — and `start_generation`
    # goes further: the books are not chosen in the conversation at all.
    fourth = answers[3].lower()
    named = [t for t in book_titles if t.lower()[:24] in fourth]
    check(
        len(named) <= 1,
        f"turn 4 did not show her the shelf: {len(named)} library titles named",
    )

    # ---- turn 5: the refusal -------------------------------------------------
    # Nothing executed the trigger, so there is no list. Both skill descriptions
    # say the same thing here, and an agent that invents a third proposal instead
    # is the exact failure this door was redesigned to prevent.
    fifth = answers[4]
    check(
        bool(NO_LIST_PATTERN.search(fifth)),
        "turn 5 said it does not have the list",
    )
    check(
        len(numbers_in(fifth)) < 3 and "HOOK" not in fifth.upper(),
        f"turn 5 did not invent a proposal: {len(numbers_in(fifth))} numbers, "
        f"hook written = {'HOOK' in fifth.upper()}",
    )

    # ---- nothing writes in this flow ----------------------------------------
    check(
        not gatekeeper.requests,
        f"the gate was never reached: {gatekeeper.requests or 'no write attempted'}",
    )
    written = await session_drafts_and_delete(session_id)
    check(len(written) == 0, f"nothing was written to `posts`: {len(written)}")
    for r in written:
        print(f"    unexpected draft: „{r['title']}” · {r['hook_type']} · {r['source']}")
    if written:
        print("    (deleted, so the check stays repeatable)")

    # ---- the trail -----------------------------------------------------------
    events = await session_events(session_id)
    kinds = [kind for kind, _ in events]
    for required in (MESSAGE_RECEIVED, RUN_COMPLETED, SKILL_ACTIVATED, GENERATION_REQUESTED):
        check(required in kinds, f"the trail has `{required}`")
    check(
        kinds.count(MESSAGE_RECEIVED) == len(TURNS),
        f"the trail has all {len(TURNS)} turns: {kinds.count(MESSAGE_RECEIVED)}",
    )
    # `skill_activated` is derived from the shell command that opened the file.
    # It recorded nothing at all between 2026-08-27 and 2026-08-31, because it
    # was still matching tool names from the shape before the sandbox came back.
    skills = sorted({subject for kind, subject in events if kind == SKILL_ACTIVATED})
    check(
        "propune-postari" in skills,
        f"the trail names the skill that was opened: {skills or '—'}",
    )
    check(
        not [c for c, _ in capabilities_in(events) if c in GATED_TOOLS],
        "no write capability appears in the trail",
    )

    # ---- what it said, across every turn ------------------------------------
    everything = "\n".join(answers)

    # A percentage is not automatically an invented figure: "30% more time" is,
    # "both sides give 50%" is a metaphor for reciprocity. The pattern cannot tell
    # them apart, so it flags for a human instead of failing the check.
    for found in PERCENT_PATTERN.finditer(everything):
        context = everything[max(0, found.start() - 60) : found.end() + 10].replace("\n", " ")
        print(f"⚠ percentage, read it yourself: …{context.strip()}…")

    defaults = DEFAULT_OPTION_PATTERN.findall(everything)
    check(not defaults, f"it never chose for her by default: {len(defaults)} found")
    check(
        "Andreea" not in everything,
        "the avatar is not called by name in the conversation",
    )
    print(f"  tools across the conversation: {sorted(set(called)) or '—'}")

    print("=" * 72)
    print(f"Trail:  uv run python -m content_studio.replay {session_id}")
    return 1 if mistakes else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
