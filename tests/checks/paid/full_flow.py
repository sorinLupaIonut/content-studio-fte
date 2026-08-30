"""End-to-end check: skills as tools, data over MCP, the gate and the trail.

Needs the server running:  uv run content-studio-server

Nine turns, the long way round, because that is where you see whether the skills
are actually read. The turns are Romanian because they are what the client types:

  1. „vreau ceva despre limite"   → asks for the format
  2. „reel"                       → asks for the pillar
  3. „conexiune"                  → asks for the source
  4. „din cărți"                  → proposes 3–4 titles, not the list of 17
  5. „caută în toate"             → calls `search_books`, then produces the ten
  6. „dezvoltă a treia…"          → the second skill: the whole post
  7. „da, salveaz-o"              → the gate stops it, and we REFUSE
  8. „ba da, sunt sigură"         → the gate stops it, and we APPROVE
  9. „acum și a șaptea"           → one more, WITHOUT regenerating the list

What each decision is proved by:

- **4 and 5** — progressive disclosure. That it proposes 3–4 titles and never all
  seventeen is written ONLY in `references/surse.md`; it is not in `SKILL.md` and
  not in the system prompt. If the agent does that, the chain index → SKILL.md →
  references works. If not, the skills are decoration.
- **6** — `search_books` really is called. This looks at the turn's calls, not at
  the words of the answer: an agent that *says* it searched looks the same.
- **7** — the whole cycle, plus turn 9: a second proposal from the same list,
  without regenerating anything.
- **8** — the trail. Afterwards you can run replay on this session.
- **9** — the gate, both ways: refused writes nothing, approved writes.

The post written at turn 8 is deleted at the end, so the check can run as often as
you like without piling up drafts. Its trail stays in the audit for replay.
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
    MESSAGE_RECEIVED,
    POST_CHOSEN,
    POST_SAVED,
    RUN_COMPLETED,
    Audit,
    split_event,
)
from content_studio.config import MCP_TIMEOUT, MCP_URL, database_url
from content_studio.mcp_server.protocol import CONVERSATION_HEADER, MODEL_VISIBLE_TOOLS
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
    "caută în toate",
    "dezvoltă a treia, cu contrastul",
    "da, e bună. salveaz-o",
    "ba da, sunt sigură. salveaz-o",
    "acum dezvoltă și a șaptea, tot cu contrastul",
]

#: The five types, tolerant of diacritics — the model writes „CIFRĂ" or „CIFRA".
HOOK_TYPES = {
    "PROVOCARE": r"PROVOCARE",
    "CIFRĂ": r"CIFR[ĂA]",
    "SECRET": r"SECRET",
    "ÎNTREBARE": r"[ÎI]NTREBARE",
    "CONTRAST": r"CONTRAST",
}

#: Any percentage is an invented result — output rule 7. This catches the obvious
#: class ("30% more time"), not the sly one ("30 minutes of breathing room"). That
#: one is left to the eval set from Decision 10.
PERCENT_PATTERN = re.compile(r"\d\s*%|\bla sută\b", re.IGNORECASE)

#: „dacă nu răspunzi, folosesc X" — output rule 9 forbids it explicitly.
DEFAULT_OPTION_PATTERN = re.compile(
    r"dac[ăa] nu r[ăa]spunzi|folosesc implicit|implicit[,:]", re.IGNORECASE
)

NUMBERING_PATTERN = re.compile(r"^\s*(\d{1,2})[.)]", re.MULTILINE)


def numbers_in(text: str) -> set[int]:
    """The proposal numbers 1–10 found at the start of a line."""
    return {int(n) for n in NUMBERING_PATTERN.findall(text) if 1 <= int(n) <= 10}


def find_list(answers: list[str]) -> tuple[int, str]:
    """The answer holding the list, plus its index (1-based).

    The turn is not assumed. It takes the answer with the most distinct proposal
    numbers; on a tie, the last one, because that is most likely the final one.
    """
    scores = [(len(numbers_in(a)), i) for i, a in enumerate(answers)]
    _, i = max(scores)
    return i + 1, answers[i]


def tools_called(result) -> list[str]:
    """The names of the tools called in this turn.

    This looks at the actual calls, not at the text: an agent that *says* it
    searched the books and one that really did look identical in the answer.
    """
    names = []
    for item in result.new_items:
        raw = getattr(item, "raw_item", None)
        if getattr(item, "type", "") == "tool_call_item" and hasattr(raw, "name"):
            names.append(raw.name)
    return names


class Gatekeeper:
    """The human at the gate, scripted: first "no", then "yes".

    Both directions in a single run — refused writes nothing, approved writes. That
    is Decision 9's criterion, and there is no point proving half of it.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, bool]] = []

    async def __call__(self, name: str, arguments: dict) -> tuple[bool, str]:
        approved = len(self.requests) > 0
        self.requests.append((name, approved))
        print(f"   [gate: {name} → {'APPROVED' if approved else 'REFUSED'}]")
        if approved:
            return True, ""
        return False, "Viorela n-a aprobat scrierea. Întreab-o ce vrea schimbat."


async def session_drafts_and_delete(session_id: str) -> list[dict]:
    """What the check wrote into `posts`, then clean up exactly this session's rows.

    The audit trail stays on purpose, so replay can reconstruct the check.
    """
    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            rows = await raw.fetch(
                """SELECT id, title, hook_type, source, length(script) AS script,
                          length(caption) AS caption, hashtags, cta
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
    """(capability, status), to tell refused apart from executed.

    `blocked` is its own event since D4, not a status read out of a result — so a
    `search_web` that failed still counts as a call that was allowed to happen.
    """
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
            "headers": {CONVERSATION_HEADER: session_id},
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
    called: list[str] = []

    # ONE CONTAINER FOR ALL NINE TURNS, and it is not optional. The worker has
    # been a `SandboxAgent` since the method went back into a sandbox on
    # 2026-08-27; `Runner.run` refuses outright without `RunConfig(sandbox=...)`.
    # This file kept the bare `RunConfig()` it was written with and had been
    # dead ever since - found on 2026-08-30, by running it. Every production
    # caller (`chat.py`, `generator.py`, `service.py`) passes one, so nothing
    # the client uses was affected; what was lost is the only check that walks
    # the whole conversation end to end.
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
                called += tools

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

    # Turn 4 — did it read references/surse.md? That is where "3–4 titles, never the
    # list of 17" is written. Count how many real library titles it named.
    fourth = answers[3].lower()
    named = [t for t in book_titles if t.lower()[:24] in fourth]
    check(
        3 <= len(named) <= 4,
        f"turn 4: proposed {len(named)} library titles (expected 3–4, not 17)",
    )

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

    check(
        "search_books" in called,
        f"it called search_books (tools: {sorted(set(called)) or '—'})",
    )

    where, listing = find_list(answers)
    distinct = numbers_in(listing)
    check(
        len(distinct) == 10,
        f"proposals numbered 1–10: {len(distinct)} found (in turn {where})",
    )

    # Decision 9 — the gate, both ways.
    refused = [n for n, approved in gatekeeper.requests if not approved]
    approved = [n for n, approved in gatekeeper.requests if approved]
    check(
        len(refused) >= 1 and len(approved) >= 1,
        f"the gate opened both ways: {len(refused)} refused, {len(approved)} approved",
    )
    check(
        all(n in GATED_TOOLS for n, _ in gatekeeper.requests),
        f"the gate stopped only the write tools: {[n for n, _ in gatekeeper.requests]}",
    )

    # Decision 7 — a single draft, the approved one. The refused one wrote nothing.
    written = await session_drafts_and_delete(session_id)
    check(len(written) == 1, f"a single draft in `posts`: {len(written)}")
    for r in written:
        print(
            f"    „{r['title']}” · hook {r['hook_type']} · script {r['script']} chars · "
            f"caption {r['caption']} chars · {r['hashtags']}"
        )
        print(f"    source: {r['source']}")
        check(bool(r["cta"]), "the draft has a CTA")
        check(bool(r["source"]), "the draft has its source filled in")
    print("    (deleted, so the check stays repeatable)")

    # Turn 9 — a second proposal from the same list, without regenerating.
    check(
        len(numbers_in(answers[8])) < 8,
        f"turn 9 did not regenerate the list: {len(numbers_in(answers[8]))} numbers",
    )

    # Decision 8 — the trail, on the D4 schema.
    events = await session_events(session_id)
    kinds = [kind for kind, _ in events]
    for required in (
        MESSAGE_RECEIVED,
        RUN_COMPLETED,
        "skill_activated",
        CAPABILITY_INVOKED,
        "approval_requested",
        "approval_rejected",
        POST_CHOSEN,
        "proposals_generated",
    ):
        check(required in kinds, f"the trail has `{required}`")
    check(
        kinds.count(MESSAGE_RECEIVED) == len(TURNS),
        f"the trail has all {len(TURNS)} turns: {kinds.count(MESSAGE_RECEIVED)}",
    )
    check(
        kinds.count(POST_CHOSEN) == 1,
        f"only the approved call is `post_chosen`: {kinds.count(POST_CHOSEN)}",
    )
    check(
        kinds.count(POST_SAVED) == 1,
        f"the server's save is linked to the run: {kinds.count(POST_SAVED)}",
    )
    save_statuses = [s for c, s in capabilities_in(events) if c == "save_post"]
    check(
        sorted(save_statuses) == ["blocked", "ok"],
        f"save_post has one blocked and one ok: {save_statuses}",
    )

    for label, pattern in HOOK_TYPES.items():
        count = len(re.findall(pattern, listing))
        check(count >= 10, f"hook {label:<10} appears {count} times (expected ≥10)")

    # Output rules 7 and 9 are checked against EVERYTHING it said, not just the list.
    everything = "\n".join(answers)

    # A percentage is not automatically a rule 7 violation: "30% more time" is an
    # invented figure, "both sides give 50%" is a metaphor for reciprocity. The
    # pattern cannot tell them apart, so it flags for a human instead of failing the
    # check. The judgement itself is the eval set's job, Decision 10.
    for found in PERCENT_PATTERN.finditer(everything):
        context = everything[max(0, found.start() - 60) : found.end() + 10].replace("\n", " ")
        print(f"⚠ percentage, read it yourself: …{context.strip()}…")

    defaults = DEFAULT_OPTION_PATTERN.findall(everything)
    check(not defaults, f"implicit options offered (rule 9): {len(defaults)}")
    check(
        "Andreea" not in " ".join(answers[:4]),
        "the avatar is not called by name in the conversation",
    )

    print("=" * 72)
    print(f"Trail:  uv run python -m content_studio.replay {session_id}")
    return 1 if mistakes else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
