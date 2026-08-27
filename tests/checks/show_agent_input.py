"""Safe check: the EXACT input one generation run sends, assembled and measured.

    uv run content-studio-server                        (in another terminal)
    uv run python tests/checks/show_agent_input.py
    uv run python tests/checks/show_agent_input.py --phase detail --full
    uv run python tests/checks/show_agent_input.py --json input.json

No model is called and no container is opened, so this costs nothing. What it
prints is not a reconstruction: the system prompt comes out of the SDK's own
`build_sandbox_instructions`, the same function `prepare_sandbox_agent` calls
one line before the request goes out, fed the same manifest `sandbox.py` mounts.

WHY IT EXISTS. The input is assembled from six places that no single file can
show you - our two prompt strings, the profile out of Neon, the source packet
out of the MCP tools, the SDK's capability notes, and the schema the contract
turns into. Before this, the only way to see the whole thing was to pay for a
run and read the span. Two of the faults this project has actually shipped were
faults of composition, not of any one part: a prompt naming tools that were not
attached, and a prompt telling the model to open files it had no shell for.

The arguments are the generator form in `Generator.razor`, field for field, so
what is measured here is what a click produces - nothing invented for the test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from agents.mcp import MCPServerStreamableHttp
from agents.run_context import RunContextWrapper
from agents.sandbox.runtime_agent_preparation import build_sandbox_instructions

from content_studio import enable_utf8_output
from content_studio.config import CLIENT_SLUG, MCP_TIMEOUT, MCP_URL
from content_studio.harness.drafts import GenerationDraftClient
from content_studio.harness.generation import (
    GenerationBatchRequest,
    IdeaTitle,
    detail_output_type,
    detail_prompt,
    title_prompt,
)
from content_studio.harness.generator import (
    GENERATION_MAX_TURNS,
    GenerationCoordinator,
    collect_source_packet,
)
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    GENERATION_VISIBLE_TOOLS,
)
from content_studio.sandbox import capabilities, sandbox_manifest, sandbox_run_config
from content_studio.worker import read_profile

enable_utf8_output()

#: The idea a detail run is handed. Phase 2 never invents one - it develops a
#: title phase 1 already wrote and the database already holds - so a plausible
#: row stands in for the one that would come off `generation_ideas`.
SAMPLE_IDEA = IdeaTitle(
    ordinal=3,
    title="Formula celor 3 pași pentru un NU blând",
    angle="Trei pași concreți, în ordinea în care se spun",
)


def megabytes(text: str) -> str:
    """Characters and bytes, because the two disagree on every Romanian line."""
    return f"{len(text):>7,} chars / {len(text.encode('utf-8')):>7,} bytes"


def rule(title: str) -> None:
    print(f"\n{'─' * 78}\n{title}\n{'─' * 78}")


async def assemble(args: argparse.Namespace) -> dict[str, Any]:
    """Build every layer of one run's input, exactly as the harness would."""

    session_id = f"{CLIENT_SLUG}-input-check-{uuid4().hex[:8]}"
    headers = {CONVERSATION_HEADER: session_id, CLIENT_HEADER: CLIENT_SLUG}

    # The generation door's own connection: reads only, three tools, no
    # approval loop. Copied in shape from `HarnessService._generation_data_mcp`
    # - if that filter ever changes, this check is wrong and should be updated
    # with it, because the tool list is half of what the prompt promises.
    data_mcp = MCPServerStreamableHttp(
        params={"url": MCP_URL, "headers": headers},
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(GENERATION_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    internal_mcp = MCPServerStreamableHttp(
        params={"url": MCP_URL, "headers": headers},
        name="content-data-internal",
        cache_tools_list=True,
        use_structured_content=True,
        client_session_timeout_seconds=MCP_TIMEOUT,
    )

    request = GenerationBatchRequest(
        format=args.format,
        pillar=args.pillar,
        source=args.source,
        focus=args.focus,
    )
    # The same resolution `start` does before the batch row is written, so the
    # model named here is the model the row would name.
    coordinator = GenerationCoordinator.__new__(GenerationCoordinator)
    request = request.model_copy(
        update={"model": GenerationCoordinator._batch_model(request)}
    )

    stack = AsyncExitStack()
    try:
        await asyncio.gather(data_mcp.connect(), internal_mcp.connect())
        _, profile_md = await read_profile(data_mcp)
        drafts = GenerationDraftClient(internal_mcp)
        packet = await collect_source_packet(internal_mcp, drafts, request)
        tools = await data_mcp.list_tools()

        if args.phase == "title":
            agent = coordinator._title_agent(
                profile_md, data_mcp, request, args.language, "input-check"
            )
            user_message = title_prompt(request, packet, args.language)
            output_type = agent.output_type
        else:
            agent = coordinator._detail_agent(
                profile_md, data_mcp, request, args.language, "input-check"
            )
            user_message = detail_prompt(request, SAMPLE_IDEA, packet, args.language)
            output_type = detail_output_type(request.format)

        # THE SYSTEM PROMPT, from the SDK's own assembler rather than from a
        # copy of its rules here. Order is the runtime's: base, then our
        # instructions under `# Agent instructions`, then the capability notes,
        # then the filesystem tree.
        #
        # TWO OF THOSE SECTIONS NEED A LIVE CONTAINER, and the SDK does not say
        # so - it returns them empty. `Skills._resolve_runtime_metadata` starts
        # with `if self.session is None: return []`, so with no session the
        # skills index is absent rather than wrong, and the filesystem section
        # shows the manifest's shape instead of the mounted tree. Offline is
        # the cheap mode and it is honest about the gap; `--live` opens one
        # container - about a second, no model - and prints the real thing.
        capability_set = capabilities()
        manifest = sandbox_manifest()
        if args.live:
            sandbox_cm = sandbox_run_config("input-check")
            sandbox = await stack.enter_async_context(sandbox_cm)
            session = sandbox.session
            for capability in capability_set:
                capability.bind(session)
            manifest = session.state.manifest

        assemble_instructions = build_sandbox_instructions(
            base_instructions=agent.base_instructions,
            additional_instructions=agent.instructions,
            capabilities=capability_set,
            manifest=manifest,
        )
        system_prompt = await assemble_instructions(RunContextWrapper(None), agent)
    finally:
        await stack.aclose()
        await asyncio.gather(
            data_mcp.cleanup(), internal_mcp.cleanup(), return_exceptions=True
        )

    settings = agent.model_settings
    return {
        "phase": args.phase,
        "request": request.model_dump(mode="json"),
        "model": agent.model,
        "system_prompt": system_prompt or "",
        "agent_instructions": agent.instructions,
        "base_instructions": agent.base_instructions,
        "profile_md": profile_md,
        "source_packet": packet,
        "user_message": user_message,
        "tools": [
            {"name": tool.name, "description": (tool.description or "").strip()}
            for tool in tools
        ],
        # Named rather than listed: `Capability.tools()` refuses to answer
        # without a live session, and opening a container to learn two names
        # would make a free check cost money. Shell contributes `exec_command`
        # always and `write_stdin` only where the session offers a PTY; Skills
        # contributes none unless it is configured to load lazily, which it is
        # not here. See `agents/sandbox/capabilities`.
        "shell_tools": ["exec_command", "write_stdin (only with a PTY)"],
        "output_schema": output_type.model_json_schema()
        if hasattr(output_type, "model_json_schema")
        else None,
        "model_settings": {
            # `reasoning` is a Pydantic `Reasoning`, and --json has to survive it.
            "reasoning": settings.reasoning.model_dump(exclude_none=True)
            if hasattr(settings.reasoning, "model_dump")
            else settings.reasoning,
            "verbosity": settings.verbosity,
            "max_tokens": settings.max_tokens,
            "extra_args": settings.extra_args,
        },
        "max_turns": GENERATION_MAX_TURNS,
        "live": args.live,
    }


def report(payload: dict[str, Any], full: bool) -> None:
    system = payload["system_prompt"]
    user = payload["user_message"]
    schema = json.dumps(payload["output_schema"], ensure_ascii=False)

    rule(f"WHAT THE MODEL RECEIVES  ·  phase={payload['phase']}  model={payload['model']}")
    print(f"  1. system prompt      {megabytes(system)}")
    print(f"     ├─ base            {megabytes(payload['base_instructions'])}   sandbox.py")
    print(f"     ├─ agent           {megabytes(payload['agent_instructions'])}   worker.py")
    print(f"     │  └─ of which profile {megabytes(payload['profile_md'])}   Neon, over MCP")
    if payload["live"]:
        print("     └─ capabilities + skills index + file tree                    the SDK's")
    else:
        print("     └─ capabilities only, no skills index                        the SDK's")
        print("        ⚠ the index and the file tree need a container: rerun with --live.")
        print("          Offline they come back EMPTY, not wrong, so this total is a floor.")
    print(f"  2. user message       {megabytes(user)}   generation.py")
    packet_json = json.dumps(payload["source_packet"], ensure_ascii=False)
    print(f"     └─ of which packet  {megabytes(packet_json)}   collected once, before the model")
    print(f"  3. output schema      {megabytes(schema)}   the contract, as response_format")
    tool_names = [t["name"] for t in payload["tools"]] + payload["shell_tools"]
    print(f"  4. tools              {len(tool_names)}: {', '.join(tool_names)}")
    print(f"  5. settings           {payload['model_settings']}")
    print(f"     max_turns          {payload['max_turns']}")

    total = len(system) + len(user) + len(schema)
    print(f"\n  first request ≈ {total:,} characters before the model writes a word")

    if not full:
        print("\n  (--full prints every layer verbatim, --json writes them to a file)")
        return

    rule("1. SYSTEM PROMPT")
    print(system)
    rule("2. USER MESSAGE")
    print(user)
    rule("3. OUTPUT SCHEMA")
    print(json.dumps(payload["output_schema"], ensure_ascii=False, indent=2))
    rule("4. TOOLS")
    for tool in payload["tools"]:
        print(f"\n· {tool['name']}\n  {tool['description'][:400]}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # The generator form, field for field.
    parser.add_argument("--format", default="Reel", choices=["Reel", "Carusel", "Stories"])
    parser.add_argument(
        "--pillar",
        default="Educație",
        choices=["Poziționare", "Educație", "Conexiune", "Conversie", "Magnetism"],
    )
    parser.add_argument(
        "--source", default="Memorie", choices=["Memorie", "Cărți", "Internet", "Combinat"]
    )
    parser.add_argument("--focus", default=None)
    parser.add_argument("--language", default="ro", choices=["ro", "en"])
    parser.add_argument("--phase", default="title", choices=["title", "detail"])
    parser.add_argument(
        "--live",
        action="store_true",
        help="open one container so the skills index and the file tree are real",
    )
    parser.add_argument("--full", action="store_true", help="print every layer verbatim")
    parser.add_argument("--json", type=Path, default=None, help="write the layers to a file")
    args = parser.parse_args()

    try:
        payload = await assemble(args)
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}", file=sys.stderr)
        print("  is `uv run content-studio-server` running?", file=sys.stderr)
        return 1

    report(payload, args.full)
    if args.json is not None:
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n  written: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
