"""Paid D1b probe: one title run, then ten details at explicit concurrency levels.

This uses the real configured model, full live profile, content-data MCP, E2B
sandbox and folder skills. It does not persist drafts or posts.

    uv run python tests/checks/ui_generation_benchmark.py --concurrency 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

from agents import ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig

from content_studio import enable_utf8_output
from content_studio.config import (
    GENERATION_DETAIL_MODEL,
    GENERATION_TITLE_MODEL,
    MCP_TIMEOUT,
    MCP_URL,
)
from content_studio.harness.generation import IdeaDetails, IdeaTitle, IdeaTitles
from content_studio.mcp_server.protocol import CONVERSATION_HEADER, MODEL_VISIBLE_TOOLS
from content_studio.worker import build_sandbox, build_worker, read_profile

enable_utf8_output()

FORMAT = "Reel"
PILLAR = "Educație"
SOURCE = "Memorie"
FOCUS = "limite sănătoase fără vinovăție pentru femeile care fac people pleasing"
SOURCE_PACKET = (
    "Nu există sursă externă pentru această probă. Folosește numai profilul complet "
    "din context și situații obișnuite formulate ca posibilități."
)
RUN_TIMEOUT_SECONDS = 600


@dataclass(slots=True)
class DetailResult:
    ordinal: int
    seconds: float
    value: IdeaDetails | None = None
    error: str | None = None


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--concurrency",
        action="append",
        required=True,
        type=int,
        choices=range(1, 11),
        help="Concurrent detail runs; repeat to compare levels (for example 5 then 10).",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=65,
        help="Pause between repeated probes so their TPM windows do not overlap.",
    )
    return parser.parse_args()


def safe_failure(exc: Exception) -> str:
    """Keep benchmark output useful without printing account identifiers."""

    name = type(exc).__name__
    message = str(exc)
    if "rate limit" in message.lower() or name == "RateLimitError":
        return f"{name}: model TPM limit reached"
    if "Invalid JSON" in message:
        return f"{name}: invalid structured JSON"
    if "Max turns" in message:
        return f"{name}: sandbox skill did not finish within the turn limit"
    if "exec_command" in message:
        return f"{name}: sandbox skill command failed"
    return f"{name}: generation failed"


def title_prompt() -> str:
    return f"""MOD UI STRUCTURAT D1B — TITLURI
Activează skill-ul `propune-postari` și urmează ramura lui pentru UI.

Format: {FORMAT}
Pilon: {PILLAR}
Sursă: {SOURCE}
Focus: {FOCUS}
Material-sursă: {SOURCE_PACKET}

Răspunde numai prin contractul structurat cerut de aplicație.
"""


def detail_prompt(idea: IdeaTitle) -> str:
    idea_json = json.dumps(idea.model_dump(), ensure_ascii=False)
    return f"""MOD UI STRUCTURAT D1B — DETALII
Activează skill-ul `dezvolta-postarea` și urmează ramura lui pentru UI.

Ideea existentă: {idea_json}
Format: {FORMAT}
Pilon: {PILLAR}
Sursă: {SOURCE}
Focus: {FOCUS}
Material-sursă: {SOURCE_PACKET}

Dezvoltă exact ideea primită. Răspunde numai prin contractul structurat cerut de
aplicație; `idea_ordinal` și `title` rămân identice cu ideea existentă.
"""


async def run_on_sandbox(
    agent, prompt: str, output_type: type[Any], label: str, client, sandbox
):
    config = RunConfig(
        sandbox=SandboxRunConfig(client=client, session=sandbox),
        group_id=f"d1b-benchmark-{label}-{uuid.uuid4().hex[:8]}",
    )
    result = await asyncio.wait_for(
        Runner.run(agent, prompt, run_config=config, max_turns=6),
        timeout=RUN_TIMEOUT_SECONDS,
    )
    if result.interruptions:
        raise RuntimeError("the read-only benchmark unexpectedly requested approval")
    return result.final_output_as(output_type, raise_if_incorrect_type=True)


async def run_isolated(agent, prompt: str, output_type: type[Any], label: str):
    client, options = build_sandbox()
    sandbox = await client.create(options=options)
    try:
        return await run_on_sandbox(
            agent, prompt, output_type, label, client, sandbox
        )
    finally:
        await sandbox.aclose()


async def run_detail(agent, idea: IdeaTitle, client, sandbox) -> DetailResult:
    started = time.perf_counter()
    for attempt in (1, 2):
        try:
            value = await run_on_sandbox(
                agent,
                detail_prompt(idea),
                IdeaDetails,
                f"idea-{idea.ordinal}-attempt-{attempt}",
                client,
                sandbox,
            )
            if value.idea_ordinal != idea.ordinal or value.title != idea.title:
                raise ValueError("the detail output changed the existing idea identity")
            return DetailResult(
                ordinal=idea.ordinal,
                seconds=time.perf_counter() - started,
                value=value,
            )
        except Exception as exc:  # noqa: BLE001 - failures are benchmark data
            retryable = "Invalid JSON" in str(exc) or "structured output" in str(exc)
            if attempt == 1 and retryable:
                continue
            return DetailResult(
                ordinal=idea.ordinal,
                seconds=time.perf_counter() - started,
                error=safe_failure(exc),
            )
    raise AssertionError("the bounded retry loop must return")


async def create_pool_slot(agent):
    client, options = build_sandbox()
    sandbox = await client.create(options=options)
    # SandboxAgent instances hold per-run state and the SDK deliberately rejects
    # concurrent reuse. A clone is the same agent definition and skills, not a
    # second role or a delegated agent.
    return agent.clone(), client, sandbox


async def close_pool_slot(slot) -> None:
    _, _, sandbox = slot
    await sandbox.aclose()


async def detail_probe(agent, ideas: list[IdeaTitle], concurrency: int) -> dict[str, Any]:
    started = time.perf_counter()
    created = await asyncio.gather(
        *(create_pool_slot(agent) for _ in range(concurrency)),
        return_exceptions=True,
    )
    slots = [item for item in created if not isinstance(item, BaseException)]
    failures = [item for item in created if isinstance(item, BaseException)]
    if failures:
        await asyncio.gather(
            *(close_pool_slot(slot) for slot in slots), return_exceptions=True
        )
        raise RuntimeError(
            f"only {len(slots)}/{concurrency} E2B pool slots were created"
        ) from failures[0]
    queue: asyncio.Queue[IdeaTitle] = asyncio.Queue()
    for idea in ideas:
        queue.put_nowait(idea)

    results: list[DetailResult] = []

    async def consume(slot) -> None:
        slot_agent, client, sandbox = slot
        while not queue.empty():
            try:
                idea = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            results.append(await run_detail(slot_agent, idea, client, sandbox))

    try:
        await asyncio.gather(*(consume(slot) for slot in slots))
    finally:
        await asyncio.gather(
            *(close_pool_slot(slot) for slot in slots), return_exceptions=True
        )

    results.sort(key=lambda item: item.ordinal)
    wall_seconds = time.perf_counter() - started
    succeeded = [item for item in results if item.value is not None]
    return {
        "concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 2),
        "ready_ideas": len(succeeded),
        "ready_variants": len(succeeded) * 5,
        "mean_task_seconds": round(
            sum(item.seconds for item in results) / len(results), 2
        ),
        "failures": [
            {"ordinal": item.ordinal, "error": item.error}
            for item in results
            if item.error is not None
        ],
    }


async def main() -> int:
    args = parse_args()
    session_id = f"d1b-benchmark-{uuid.uuid4().hex[:8]}"
    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {CONVERSATION_HEADER: session_id},
        },
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    try:
        await data_mcp.connect()
        _, profile_md = await read_profile(data_mcp)
        base_agent = build_worker(profile_md, data_mcp)
        title_agent = base_agent.clone(
            model=GENERATION_TITLE_MODEL,
            output_type=IdeaTitles,
            model_settings=ModelSettings(
                reasoning={"effort": "minimal"},
                verbosity="low",
                max_tokens=4_000,
            ),
        )
        detail_agent = base_agent.clone(
            model=GENERATION_DETAIL_MODEL,
            output_type=IdeaDetails,
            model_settings=ModelSettings(
                reasoning={"effort": "minimal"},
                verbosity="low",
                max_tokens=24_000,
            ),
        )

        print(
            f"Models: {GENERATION_TITLE_MODEL}/{GENERATION_DETAIL_MODEL} · "
            f"profile: {len(profile_md):,} chars · "
            f"format/pillar/source: {FORMAT}/{PILLAR}/{SOURCE}"
        )
        print("Generating the ten titles once...")
        started = time.perf_counter()
        titles = await run_isolated(
            title_agent, title_prompt(), IdeaTitles, "titles"
        )
        title_seconds = time.perf_counter() - started
        print(f"Titles ready: 10/10 in {title_seconds:.2f}s")

        reports = []
        for index, concurrency in enumerate(args.concurrency):
            if index:
                print(
                    f"Cooling down for {args.cooldown_seconds}s before the next TPM window..."
                )
                await asyncio.sleep(args.cooldown_seconds)
            print(f"Running the same ten details at concurrency {concurrency}...")
            report = await detail_probe(detail_agent, titles.ideas, concurrency)
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False))

        result = {
            "title_model": GENERATION_TITLE_MODEL,
            "detail_model": GENERATION_DETAIL_MODEL,
            "profile_characters": len(profile_md),
            "titles_seconds": round(title_seconds, 2),
            "probes": reports,
        }
        print("D1B_BENCHMARK=" + json.dumps(result, ensure_ascii=False))
        return 0 if all(item["ready_ideas"] == 10 for item in reports) else 1
    except Exception as exc:  # noqa: BLE001 - this is an executable probe
        print(f"Benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await data_mcp.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
