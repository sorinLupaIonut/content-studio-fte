"""Isolated check for `search_web` — no access to the books or the posts.

    uv run content-studio-server            (in another terminal)
    uv run python tests/checks/paid/web.py

Only the generic topic below is sent to OpenAI. It verifies the MCP contract and
the web provenance; it reads nothing from Neon.

`search_web` returns the same shape as `search_books`: a list of findings, each
carrying its own text and its own provenance.
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
        findings = result if isinstance(result, list) else []
        checks = [
            (bool(findings), "it returned findings"),
            (len(findings) <= 3, "it honoured the limit"),
            (
                all(f.get("text") for f in findings),
                "every finding carries the text read on the page",
            ),
            (
                all(
                    f.get("title") and f.get("url", "").startswith("http")
                    for f in findings
                ),
                "every finding has a title and a URL",
            ),
        ]
        failed = 0
        for passed, message in checks:
            failed += not passed
            print(f"{'✓' if passed else '✗'} {message}")
        print(f"Findings: {len(findings)}")
        for f in findings:
            print(f"  - {f['title']} — {f.get('site') or '?'}: {f['url']}")
            print(f"      {f['text'][:100].strip()}…")
        return 1 if failed else 0
    finally:
        await server.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
