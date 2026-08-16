"""Replay a conversation from its trail. Decision 8.

    uv run python -m content_studio.replay                 the last conversation
    uv run python -m content_studio.replay <session_id>    a specific one
    uv run python -m content_studio.replay --list          which conversations exist

The criterion: **you can reconstruct what it did without running the model.** No
API is called here — it reads `audit_log` and `capability_invocations`, nothing else.

If a turn shows `message_received` with no `message_sent`, that turn failed, and it
shows. Which is also why the trail is written before the run, not after.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url

enable_utf8_output()

LIST_SQL = """
SELECT c.session_id, c.started_at, count(a.id) AS rows
  FROM conversations c
  LEFT JOIN audit_log a ON a.conversation_id = c.session_id
 GROUP BY c.session_id, c.started_at
 ORDER BY c.started_at DESC
 LIMIT 20
"""

LAST_SQL = """
SELECT conversation_id FROM audit_log
 WHERE conversation_id IS NOT NULL
 ORDER BY created_at DESC LIMIT 1
"""

TRAIL_SQL = """
SELECT created_at, actor, action, target, payload, result
  FROM audit_log
 WHERE conversation_id = $1
 ORDER BY id
"""

CAPABILITIES_SQL = """
SELECT capability, status, count(*) AS times
  FROM capability_invocations
 WHERE conversation_id = $1
 GROUP BY capability, status
 ORDER BY capability
"""

#: How each action reads. Anything missing here is printed raw.
MARKERS = {
    "message_received": ("client>", "text"),
    "message_sent": ("worker>", "text"),
    "skill_activated": ("  skill", "skill"),
    "capability_invoked": ("  tool", None),
    "post_chosen": ("  chose", "title"),
    "proposals_generated": ("  produced proposals", "count"),
    "guardrail_tripped": ("  FAILED", "message"),
    "post_saved": ("  SAVED", "title"),
    "profile_updated": ("  PROFILE CHANGED", "section"),
    "approval_requested": ("  gate: asked", None),
    "approval_rejected": ("  gate: REFUSED", None),
}


def short(text: object, width: int = 96) -> str:
    one_line = " ".join(str(text).split())
    return textwrap.shorten(one_line, width, placeholder="…") if one_line else ""


def describe(row) -> str:
    action = row["action"]
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    label, key = MARKERS.get(action, (f"  {action}", None))

    if action == "capability_invoked":
        arguments = ", ".join(f"{k}={short(v, 40)}" for k, v in payload.items())
        return f"{label} {row['target']}({arguments})"

    value = payload.get(key) if key else json.dumps(payload, ensure_ascii=False)
    return f"{label} {short(value)}"


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
                for r in await conn.fetch(LIST_SQL):
                    print(f"{r['started_at']:%Y-%m-%d %H:%M}  {r['session_id']}  "
                          f"{r['rows']:>4} trail rows")
                return 0

            session = argument or await conn.fetchval(LAST_SQL)
            if not session:
                print("No trail in `audit_log`. Run the worker first.")
                return 1

            trail = await conn.fetch(TRAIL_SQL, session)
            capabilities = await conn.fetch(CAPABILITIES_SQL, session)
    finally:
        await engine.dispose()

    if not trail:
        print(f"No trail for {session}.")
        return 1

    print(f"Conversation {session}")
    print(f"{len(trail)} trail rows, between {trail[0]['created_at']:%H:%M:%S} "
          f"and {trail[-1]['created_at']:%H:%M:%S}\n")
    print("─" * 100)

    turns = 0
    for row in trail:
        if row["action"] == "message_received":
            turns += 1
            print()
        print(describe(row))

    print("─" * 100)
    print(f"\n{turns} turns.")
    if capabilities:
        print("Tools called:")
        for r in capabilities:
            print(f"  {r['capability']:<28} {r['status']:<8} × {r['times']}")
    else:
        print("No tool was called.")

    received = sum(r["action"] == "message_received" for r in trail)
    sent = sum(r["action"] == "message_sent" for r in trail)
    if received != sent:
        print(f"\n⚠ {received - sent} turns without an answer — they died on the way.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
