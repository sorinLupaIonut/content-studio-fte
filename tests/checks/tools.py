"""Decision 6's criterion: the `content-data` server answers over HTTP.

    uv run content-studio-server            (in another terminal, left running)
    uv run python tests/checks/tools.py

It checks four things, in the order they matter:

1. **Exactly five tools**, with the names from the plan. If another one shows up,
   or if any name contains "sql", the check fails — rule 1 is not a preference.
2. **`search_books` returns passages with provenance.** Returning text is not
   enough: without a title and a page, the passage cannot reach the `source` field.
3. **`search_web` returns angles and the links of its sources.**
4. **The write tools exist and require the right fields.** They are not called — a
   check has no business in the `posts` table. End-to-end is Decision 7's job.
"""

from __future__ import annotations

import asyncio
import json
import sys

from agents.mcp import MCPServerStreamableHttp

from content_studio import enable_utf8_output
from content_studio.config import MCP_TIMEOUT, MCP_URL

enable_utf8_output()

EXPECTED = {
    "search_books",
    "search_web",
    "list_posts",
    "save_post",
    "update_profile",
}
QUESTION = "vinovăția de a spune nu"
WEB_QUESTION = "burnout și limite personale — ce se discută acum"


def content(result) -> object:
    """What the tool returned, as a Python object.

    `content` arrives as one TextContent per element, so a list would have to be
    glued back together. `structured_content` holds the whole answer in one piece —
    for a list, under the `result` key.
    """
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
    # 90 seconds, not the default 5: `search_books` calls OpenAI for the embedding
    # first and only then Neon. On the first call, with cold connections, the two
    # of them together comfortably pass five seconds.
    server = MCPServerStreamableHttp(
        params={"url": MCP_URL}, name="content-data", client_session_timeout_seconds=MCP_TIMEOUT
    )
    try:
        await server.connect()
    except Exception as e:  # noqa: BLE001
        print(f"Nothing answers at {MCP_URL} ({type(e).__name__}).", file=sys.stderr)
        print("Start it first:  uv run content-studio-server", file=sys.stderr)
        return 1

    failed = 0
    try:
        tools = {t.name: t for t in await server.list_tools()}
        print(f"Tools: {', '.join(sorted(tools))}\n")

        missing = EXPECTED - set(tools)
        extra = set(tools) - EXPECTED
        if missing or extra:
            print(f"✗ tools: missing {missing or '—'}, extra {extra or '—'}")
            failed += 1
        else:
            print("✓ exactly the five tools from the plan")

        if any("sql" in name.lower() for name in tools):
            print("✗ there is a tool with \"sql\" in its name — rule 1")
            failed += 1

        # 1. Searching the books
        passages = content(
            await server.call_tool("search_books", {"description": QUESTION, "limit": 5})
        )
        print(f"\n„{QUESTION}” → {len(passages)} passages")
        with_marker = 0
        for p in passages:
            marker = (
                f"page {p['page']}"
                if p["page"]
                else (f"chapter {p['chapter']}" if p["chapter"] else "no marker")
            )
            with_marker += bool(p["page"] or p["chapter"])
            print(f"  [{p['score']:.3f}] {p['title']} — {p['author']}, {marker}")
            print(f"          {p['text'][:90].strip()}…")

        if not passages:
            print("✗ the search returned nothing")
            failed += 1
        elif with_marker < len(passages):
            print(f"✗ {len(passages) - with_marker} passages with no citable marker")
            failed += 1
        elif any(
            not all(
                p.get(field) is not None
                for field in (
                    "title",
                    "authority_class",
                    "version",
                    "is_summary",
                    "has_page_markers",
                    "rights_basis",
                    "owner",
                    "embedding_model",
                )
            )
            for p in passages
        ):
            print("✗ a passage is missing its mandatory provenance")
            failed += 1
        else:
            print("✓ every passage carries its provenance and embedding model")

        # 2. Searching the web
        web = content(
            await server.call_tool("search_web", {"description": WEB_QUESTION, "limit": 3})
        )
        print(f"\nWeb: {web['topic']}")
        print(f"  {web['angles'][:180].strip()}…")
        for source in web["sources"]:
            print(f"  - {source['title']}: {source['url']}")
        if not web["angles"] or not web["sources"]:
            print("✗ the web search returned no angles with sources")
            failed += 1
        elif any(not s.get("title") or not s.get("url") for s in web["sources"]):
            print("✗ a web source has no title and URL")
            failed += 1
        else:
            print("✓ the web search returns angles with their source links")

        # 3. The posts already written
        posts = content(await server.call_tool("list_posts", {"limit": 3}))
        print(f"\nLatest posts: {len(posts)}")
        for p in posts:
            print(f"  {p['posted_on']}  {p['title'][:58]}")
        if not posts:
            print("✗ it returned no post, although the seed inserted 26")
            failed += 1
        else:
            print("✓ the posts can be read")

        # 4. The write tools — the shape is checked, they are not called
        print()
        for name in ("save_post", "update_profile"):
            required = set(tools[name].input_schema.get("required", []))
            print(f"  {name}: requires {', '.join(sorted(required))}")
        if "source" not in set(tools["save_post"].input_schema.get("required", [])):
            print("✗ save_post accepts a post without `source` — rule 8")
            failed += 1
        else:
            print("✓ save_post refuses a post without a source")

    finally:
        await server.cleanup()

    print(f"\n{'FAILED: ' + str(failed) + ' checks' if failed else 'PASSED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
