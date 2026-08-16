"""Short check for the write → conversation → audit link.

Needs the server running and never calls the model. It writes a dummy post inside a
brand new conversation, verifies exactly one blocked call and one successful one,
then deletes every row of that conversation. It does not touch the client's posts.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agents.mcp import MCPServerStreamableHttp
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import Audit
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
    """Only the test conversation's rows, in the order that is safe for the FKs."""
    async with engine.begin() as sa_conn:
        conn = (await sa_conn.get_raw_connection()).driver_connection
        await conn.execute("DELETE FROM posts WHERE conversation_id = $1", session_id)
        await conn.execute("DELETE FROM audit_log WHERE conversation_id = $1", session_id)
        await conn.execute(
            "DELETE FROM capability_invocations WHERE conversation_id = $1", session_id
        )
        await conn.execute("DELETE FROM conversations WHERE session_id = $1", session_id)


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

        blocked_call = "check-blocked"
        reason = "Viorela n-a aprobat scrierea."
        await trail.capability_blocked(
            session_id, "save_post", arguments, reason, blocked_call
        )
        await trail.turn(session_id, call_result(blocked_call, arguments, reason))

        response = await server.call_tool("save_post", arguments)
        result = response.structured_content or {}
        await trail.turn(session_id, call_result("check-approved", arguments, result))

        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            posts = await conn.fetchval(
                "SELECT count(*) FROM posts WHERE conversation_id = $1", session_id
            )
            actions = await conn.fetch(
                """SELECT action FROM audit_log
                    WHERE conversation_id = $1 ORDER BY id""",
                session_id,
            )
            statuses = await conn.fetch(
                """SELECT status FROM capability_invocations
                    WHERE conversation_id = $1 AND capability = 'tool:save_post'
                    ORDER BY status""",
                session_id,
            )

        actions = [r["action"] for r in actions]
        statuses = [r["status"] for r in statuses]
        checks = [
            (posts == 1, f"exactly one post linked to the conversation: {posts}"),
            (
                actions.count("post_saved") == 1,
                f"transactional audit linked to the conversation: {actions.count('post_saved')}",
            ),
            (
                actions.count("post_chosen") == 1,
                f"only the successful call counts as chosen: {actions.count('post_chosen')}",
            ),
            (
                statuses == ["blocked", "ok"],
                f"the capability has blocked + ok: {statuses}",
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
