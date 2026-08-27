"""Safe check: the MCP contract and the startup profile, with no model and no writes.

    uv run content-studio-server            (in another terminal)
    uv run python tests/checks/bootstrap.py

Reads the profile from Neon through the MCP resource, but never prints its content
and never sends it to OpenAI. It checks the raw server contract and separately
applies the same allowlist used by the agent.
"""

from __future__ import annotations

import asyncio
import sys

from agents.mcp import MCPServerStreamableHttp

from content_studio import enable_utf8_output
from content_studio.config import MCP_TIMEOUT, MCP_URL
from content_studio.mcp_server.protocol import INTERNAL_UI_TOOLS, MODEL_VISIBLE_TOOLS
from content_studio.worker import read_profile

enable_utf8_output()

async def main() -> int:
    server = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    failed = 0
    try:
        await server.connect()
        tools = {t.name for t in await server.list_tools()}
        agent_tools = tools & MODEL_VISIBLE_TOOLS
        name, profile = await read_profile(server)

        checks = [
            (
                tools == MODEL_VISIBLE_TOOLS | INTERNAL_UI_TOOLS,
                f"raw server has {len(MODEL_VISIBLE_TOOLS)} agent + {len(INTERNAL_UI_TOOLS)} internal tools: {len(tools)} total",
            ),
            (
                agent_tools == MODEL_VISIBLE_TOOLS,
                f"agent allowlist matches MODEL_VISIBLE_TOOLS exactly: {sorted(agent_tools)}",
            ),
            (not any("sql" in t.lower() for t in tools), "no SQL tool"),
            (bool(name.strip()), "the profile carries the client's name"),
            (len(profile) > 1_000, f"the profile arrived over MCP: {len(profile):,} characters"),
        ]
        for passed, message in checks:
            failed += not passed
            print(f"{'✓' if passed else '✗'} {message}")
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await server.cleanup()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
