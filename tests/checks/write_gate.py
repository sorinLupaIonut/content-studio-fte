"""Short check for the write → run → audit link.

Needs the server running and never calls the model. It opens a run, writes a dummy
post inside it, verifies that exactly one call was refused and one allowed, then
deletes every row it created. It does not touch the client's posts.

Rebuilt for the D4 schema: the trail is `(run_id, event)` now, so the assertions
are about which events landed rather than about the `result` column each one
carried — that column no longer exists.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agents.mcp import MCPServerStreamableHttp
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import (
    CAPABILITY_BLOCKED,
    CAPABILITY_INVOKED,
    POST_CHOSEN,
    POST_SAVED,
    Audit,
    split_event,
)
from content_studio.config import MCP_URL, database_url
from content_studio.mcp_server.protocol import CONVERSATION_HEADER
from content_studio.worker import open_session

enable_utf8_output()


def call_result(call_id: str, arguments: dict, result: object):
    """The minimum shape `Audit.turn` reads out of the SDK."""
    call = SimpleNamespace(
        type="tool_call_item",
        raw_item=SimpleNamespace(
            name="save_post",
            arguments=json.dumps(arguments, ensure_ascii=False),
            call_id=call_id,
        ),
    )
    output = SimpleNamespace(
        type="tool_call_output_item",
        raw_item=SimpleNamespace(call_id=call_id),
        output=result,
    )
    return SimpleNamespace(new_items=[call, output], final_output="")


async def clean_up(engine, session_id: str) -> None:
    """Only this check's rows. In dependency order: the trail points at the run."""
    async with engine.begin() as sa_conn:
        conn = (await sa_conn.get_raw_connection()).driver_connection
        await conn.execute(
            "DELETE FROM public.posts WHERE conversation_id = $1", session_id
        )
        await conn.execute(
            """DELETE FROM public.audit_log
                WHERE run_id IN (SELECT id FROM public.runs WHERE session_id = $1)""",
            session_id,
        )
        await conn.execute(
            """DELETE FROM public.traces
                WHERE run_id IN (SELECT id FROM public.runs WHERE session_id = $1)""",
            session_id,
        )
        await conn.execute("DELETE FROM public.runs WHERE session_id = $1", session_id)


async def main() -> int:
    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args)
    session_id = await open_session(engine, new=True)
    trail = Audit(url, connect_args)
    server = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {CONVERSATION_HEADER: session_id},
        },
        name="content-data",
        client_session_timeout_seconds=30,
    )

    arguments = {
        "title": "PROBĂ — se șterge automat",
        "pillar": "Conexiune",
        "format": "Reel",
        "hook": "Hook de probă",
        "hook_type": "CONTRAST",
        "script": "Script de probă.",
        "caption": "Caption de probă?",
        "hashtags": "#proba #limite #continut",
        "cta": "CTA de probă.",
        "source": "din memorie 🧠 (profil + avatar), fără sursă externă",
    }
    failed = 0

    try:
        await server.connect()

        # The run has to exist before the tool is called: the MCP server links its
        # audit row to the newest run of this session, and without one it would
        # write NULL.
        run_id = await trail.open_run(session_id, "probă pentru poarta de scriere")
        if run_id is None:
            print("✗ the run could not be opened — nothing else can be checked")
            return 1

        blocked_call = "check-blocked"
        await trail.capability_blocked(run_id, "save_post", blocked_call)
        await trail.turn(run_id, call_result(blocked_call, arguments, "refuzat"))

        response = await server.call_tool("save_post", arguments)
        result = response.structured_content or {}
        await trail.turn(run_id, call_result("check-approved", arguments, result))

        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            posts = await conn.fetchval(
                "SELECT count(*) FROM public.posts WHERE conversation_id = $1", session_id
            )
            rows = await conn.fetch(
                "SELECT event FROM public.audit_log WHERE run_id = $1 ORDER BY id",
                run_id,
            )
            linked = await conn.fetchval(
                """SELECT count(*) FROM public.audit_log
                    WHERE run_id = $1 AND event LIKE $2 || '%'""",
                run_id,
                POST_SAVED,
            )

        kinds = [split_event(r["event"])[0] for r in rows]
        gate = sorted(k for k in kinds if k in (CAPABILITY_INVOKED, CAPABILITY_BLOCKED))
        checks = [
            (posts == 1, f"exactly one post linked to the conversation: {posts}"),
            (
                linked == 1,
                f"the MCP server's audit row hangs off this run: {linked}",
            ),
            (
                kinds.count(POST_CHOSEN) == 1,
                f"only the successful call counts as chosen: {kinds.count(POST_CHOSEN)}",
            ),
            (
                gate == [CAPABILITY_BLOCKED, CAPABILITY_INVOKED],
                f"one refused call and one allowed: {gate}",
            ),
        ]
        for passed, message in checks:
            failed += not passed
            print(f"{'✓' if passed else '✗'} {message}")
    finally:
        await server.cleanup()
        await trail.close()
        await clean_up(engine, session_id)
        await engine.dispose()
        print("✓ the check rows were deleted")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
