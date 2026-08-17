"""Replay a conversation from its trail. Decision 8, rebuilt on the D4 schema.

    uv run python -m content_studio.replay                 the last conversation
    uv run python -m content_studio.replay <session_id>    a specific one
    uv run python -m content_studio.replay --list          which conversations exist

The criterion has not changed: **you can reconstruct what it did without running
the model.** No API is called here. What changed is where it reads from — two
tables instead of one, because D4 split the turn from the events inside it:

    public.runs        her message and the answer, one row per turn
    public.audit_log   what happened in between, as (run_id, event)

What you no longer see, and should not go looking for: the arguments a tool was
called with and what it returned. The course's trail has no payload column. A row
says `capability_invoked: save_post`; to see the post itself, look in
`public.posts`.

A run whose `output_message` is NULL is a turn that died on the way — which used
to be inferred by counting messages in against messages out, and is now simply
visible.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from collections import Counter

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import (
    CAPABILITY_BLOCKED,
    CAPABILITY_INVOKED,
    MESSAGE_RECEIVED,
    RUN_COMPLETED,
    split_event,
)
from content_studio.config import MissingConfig, database_url

enable_utf8_output()

LIST_SQL = """
SELECT session_id,
       min(created_at) AS started_at,
       count(*)        AS runs
  FROM public.runs
 GROUP BY session_id
 ORDER BY min(created_at) DESC
 LIMIT 20
"""

LAST_SQL = "SELECT session_id FROM public.runs ORDER BY created_at DESC LIMIT 1"

RUNS_SQL = """
SELECT id, input_message, output_message, created_at
  FROM public.runs
 WHERE session_id = $1
 ORDER BY created_at, id
"""

EVENTS_SQL = """
SELECT a.run_id, a.event
  FROM public.audit_log a
  JOIN public.runs      r ON r.id = a.run_id
 WHERE r.session_id = $1
 ORDER BY a.id
"""

#: How each event kind reads. Anything missing here is printed as it is stored.
#: The two structural events are not shown at all: `message_received` and
#: `run_completed` say what the run's own two columns already say.
MARKERS = {
    "skill_activated": "  skill",
    CAPABILITY_INVOKED: "  tool",
    CAPABILITY_BLOCKED: "  REFUSED",
    "post_chosen": "  chose",
    "post_saved": "  SAVED",
    "profile_updated": "  PROFILE CHANGED",
    "proposals_generated": "  produced proposals",
    "guardrail_tripped": "  FAILED",
    "approval_requested": "  gate: asked",
    "approval_granted": "  gate: allowed",
    "approval_rejected": "  gate: REFUSED",
    "corpus_seeded": "  seeded",
}

HIDDEN = {MESSAGE_RECEIVED, RUN_COMPLETED}


def short(text: object, width: int = 96) -> str:
    one_line = " ".join(str(text).split())
    return textwrap.shorten(one_line, width, placeholder="…") if one_line else ""


def describe(event: str) -> str:
    kind, subject = split_event(event)
    return f"{MARKERS.get(kind, '  ' + kind)} {short(subject)}".rstrip()


async def main() -> int:
    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    argument = sys.argv[1] if len(sys.argv) > 1 else None
    engine = create_async_engine(url, connect_args=connect_args)

    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection

            if argument in ("--list", "--lista"):
                rows = await conn.fetch(LIST_SQL)
                if not rows:
                    print("No runs yet. Run the worker first.")
                    return 1
                for r in rows:
                    print(f"{r['started_at']:%Y-%m-%d %H:%M}  {r['session_id']}  "
                          f"{r['runs']:>4} runs")
                return 0

            session = argument or await conn.fetchval(LAST_SQL)
            if not session:
                print("No runs in `public.runs`. Run the worker first.")
                return 1

            runs = await conn.fetch(RUNS_SQL, session)
            events = await conn.fetch(EVENTS_SQL, session)
    finally:
        await engine.dispose()

    if not runs:
        print(f"No trail for {session}.")
        return 1

    by_run: dict[str, list[str]] = {}
    for row in events:
        by_run.setdefault(row["run_id"], []).append(row["event"])

    print(f"Conversation {session}")
    print(f"{len(runs)} runs, between {runs[0]['created_at']:%H:%M:%S} "
          f"and {runs[-1]['created_at']:%H:%M:%S}\n")
    print("─" * 100)

    for run in runs:
        print()
        print(f"client> {short(run['input_message'])}")
        for event in by_run.get(run["id"], []):
            kind, _ = split_event(event)
            if kind not in HIDDEN:
                print(describe(event))
        if run["output_message"] is None:
            print("worker> — nothing came back; this turn died on the way")
        else:
            print(f"worker> {short(run['output_message'])}")

    print("─" * 100)
    print(f"\n{len(runs)} turns.")

    # Derived from the trail rather than from a table of its own. `blocked` means
    # the gate refused the call, and only that: it is a separate event, not a
    # status read out of a result — so a `search_web` that failed still counts as
    # a call that was allowed to happen.
    tools = Counter()
    for event in (row["event"] for row in events):
        kind, subject = split_event(event)
        if kind in (CAPABILITY_INVOKED, CAPABILITY_BLOCKED) and subject:
            tools[(subject, "blocked" if kind == CAPABILITY_BLOCKED else "ok")] += 1

    if tools:
        print("Tools called:")
        for (capability, status), times in sorted(tools.items()):
            print(f"  {capability:<28} {status:<8} × {times}")
    else:
        print("No tool was called.")

    died = sum(run["output_message"] is None for run in runs)
    if died:
        print(f"\n⚠ {died} turn(s) without an answer — they died on the way.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
