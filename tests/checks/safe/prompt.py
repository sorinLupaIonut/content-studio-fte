"""Safe check: the prompt and the tools, built exactly as a real run builds them.

    uv run python tests/checks/safe/prompt.py

No database, no MCP connection, no OpenAI call, no cost. The MCP server object is
constructed but never connected: `build_worker` only holds onto it and reads its
tool filter, which is the whole point - the note about data tools is written from
that filter rather than from a list somebody typed.

This is the file to start under the debugger. Put a breakpoint on the first line
of `build_worker` and step: `references`, `method_note`, `tool_note`, `common`,
and finally `agent.instructions` are every variable the prompt is made of.

It runs both shapes, because they differ in exactly one thing - which data tools
exist - and the difference used to be invisible: the prompt claimed five tools in
both, while chat had seven and generation three.
"""

from __future__ import annotations

from agents.mcp import MCPServerStreamableHttp

from content_studio import enable_utf8_output
from content_studio.config import MCP_URL
from content_studio.mcp_server.protocol import (
    GENERATION_VISIBLE_TOOLS,
    MODEL_VISIBLE_TOOLS,
)
from content_studio.worker import build_worker

#: Stands in for the ~28 KB the real run reads out of Neon (28,639 characters,
#: measured 2026-08-31). A marker rather than a sample of her profile: this file
#: is committed, and her content is not. The number matters when you are reading
#: the token count above: the placeholder is three lines, the real thing is the
#: largest single part of the prompt.
PROFILE_PLACEHOLDER = "<<PROFILUL CLIENTEI - ~28 KB, citit din Neon la runtime>>"

RULE = "=" * 78

#: The two ways the studio runs. Same agent, same skills, different data tools.
SHAPES = (
    ("CHAT (worker.py, conversatie)", MODEL_VISIBLE_TOOLS),
    ("GENERARE (harness, titluri + detalii)", GENERATION_VISIBLE_TOOLS),
)


def stub_server(allowed: frozenset[str]) -> MCPServerStreamableHttp:
    """An MCP server object that is never connected, carrying a real filter."""

    return MCPServerStreamableHttp(
        params={"url": MCP_URL},
        tool_filter={"allowed_tool_names": sorted(allowed)},
    )


def show(label: str, allowed: frozenset[str]) -> None:
    # Breakpoint here, then step in: everything the prompt is made of is inside.
    agent = build_worker(PROFILE_PLACEHOLDER, stub_server(allowed))

    instructions = agent.instructions
    print(RULE)
    print(label)
    print(f"prompt: {len(instructions)} caractere, ~{len(instructions) // 4} token-i")
    print(RULE)
    print(instructions)

    print()
    print(f"--- UNELTE LOCALE ({len(agent.tools)}) ---")
    for tool in agent.tools:
        schema = tool.params_json_schema
        arguments = ", ".join(schema.get("properties", {})) or "niciunul"
        print()
        print(f"* {tool.name}   argumente: {arguments}")
        print(f"  descriere, {len(tool.description)} caractere:")
        for line in tool.description.strip().splitlines():
            print(f"    {line.strip()}")
        for name, spec in schema.get("properties", {}).items():
            for value in spec.get("enum", ()):
                print(f"    enum {name}: {value}")

    print()
    print(f"--- UNELTE PRIN MCP ({len(allowed)}), filtrate inainte de model ---")
    for name in sorted(allowed):
        print(f"* {name}")
    print()


def main() -> int:
    enable_utf8_output()
    for label, allowed in SHAPES:
        show(label, allowed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
