"""Isolated check for `search_web` — no access to the books or the posts.

    uv run content-studio-server            (in another terminal)
    uv run python tests/checks/web.py

Only the generic topic below is sent to OpenAI. It verifies the MCP contract, the
angles and the web provenance; it reads nothing from Neon.
"""

from __future__ import annotations

import asyncio
import json

from agents.mcp import MCPServerStreamableHttp

from content_studio import enable_utf8_output
from content_studio.config import MCP_TIMEOUT, MCP_URL

enable_utf8_output()

TOPIC = "burnout și limite personale — teme actuale pentru conținut social"


def content(result) -> object:
    structured = result.structured_content
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]
    if structured is not None:
        return structured
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    if not texts:
        return None
    decoded = json.loads("".join(texts))
    return decoded.get("result", decoded) if isinstance(decoded, dict) else decoded


async def main() -> int:
    server = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    try:
        await server.connect()
        tools = {t.name: t for t in await server.list_tools()}
        if "search_web" not in tools:
            print("✗ `search_web` is not in the MCP contract")
            return 1

        result = content(
            await server.call_tool("search_web", {"description": TOPIC, "limit": 3})
        )
        sources = result.get("sources", [])
        checks = [
            (result.get("status") == "ok", "the status is ok"),
            (bool(result.get("angles")), "it returned angles"),
            (bool(sources), "it returned sources"),
            (
                all(s.get("title") and s.get("url", "").startswith("http") for s in sources),
                "every source has a title and a URL",
            ),
            ("Nu prelua" in result.get("rule", ""), "it returned the no-facts rule"),
        ]
        failed = 0
        for passed, message in checks:
            failed += not passed
            print(f"{'✓' if passed else '✗'} {message}")
        print(f"Sources: {len(sources)}")
        for source in sources:
            print(f"  - {source['title']}: {source['url']}")
        return 1 if failed else 0
    finally:
        await server.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
