"""Paid D1b probe: one title run, then ten details at explicit concurrency levels.

This uses the real configured model, full live profile, content-data MCP and the
skill tools. It does not persist drafts or posts.

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
from agents.run_config import RunConfig

from content_studio import enable_utf8_output
from content_studio.config import (
    GENERATION_DETAIL_MODEL,
    GENERATION_TITLE_MODEL,
    MCP_TIMEOUT,
    MCP_URL,
)
from content_studio.harness.generation import (
    GenerationBatchRequest,
    IdeaDetails,
    IdeaTitle,
    IdeaTitles,
    detail_prompt,
    title_prompt,
)
from content_studio.mcp_server.protocol import CONVERSATION_HEADER, MODEL_VISIBLE_TOOLS
from content_studio.worker import build_worker, read_profile

enable_utf8_output()

FORMAT = "Reel"
PILLAR = "Educație"
SOURCE = "Memorie"
FOCUS = "limite sănătoase fără vinovăție pentru femeile care fac people pleasing"
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
        return f"{name}: the skill did not finish within the turn limit"
    return f"{name}: generation failed"


#: The benchmark used to carry its OWN copies of the two prompts, and they had
#: drifted: they still said "Activează skill-ul", the wording measured on
#: 2026-08-24 to leave the title phase never calling its tool at all. A benchmark
#: that measures a prompt nobody sends measures nothing, so it now asks the
#: harness for the same strings production sends.
REQUEST = GenerationBatchRequest(
    format=FORMAT, pillar=PILLAR, source=SOURCE, focus=FOCUS
)


def titles_prompt() -> str:
    return title_prompt(REQUEST)


def details_prompt(idea: IdeaTitle) -> str:
    return detail_prompt(REQUEST, idea)


async def run_agent(agent, prompt: str, output_type: type[Any], label: str):
    config = RunConfig(group_id=f"d1b-benchmark-{label}-{uuid.uuid4().hex[:8]}")
    result = await asyncio.wait_for(
        Runner.run(agent, prompt, run_config=config, max_turns=6),
        timeout=RUN_TIMEOUT_SECONDS,
    )
    if result.interruptions:
        raise RuntimeError("the read-only benchmark unexpectedly requested approval")
    return result.final_output_as(output_type, raise_if_incorrect_type=True)


async def run_isolated(agent, prompt: str, output_type: type[Any], label: str):
    return await run_agent(agent, prompt, output_type, label)


async def run_detail(agent, idea: IdeaTitle) -> DetailResult:
    started = time.perf_counter()
    for attempt in (1, 2):
        try:
            value = await run_agent(
                agent,
                details_prompt(idea),
                IdeaDetails,
                f"idea-{idea.ordinal}-attempt-{attempt}",
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
    # An Agent holds per-run state and the SDK deliberately rejects concurrent
    # reuse. A clone is the same definition and the same tools, not a second role.
    return agent.clone()


async def detail_probe(agent, ideas: list[IdeaTitle], concurrency: int) -> dict[str, Any]:
    started = time.perf_counter()
    created = await asyncio.gather(
        *(create_pool_slot(agent) for _ in range(concurrency)),
        return_exceptions=True,
    )
    slots = [item for item in created if not isinstance(item, BaseException)]
    failures = [item for item in created if isinstance(item, BaseException)]
    if failures:
        raise RuntimeError(
            f"only {len(slots)}/{concurrency} pool slots were created"
        ) from failures[0]
    queue: asyncio.Queue[IdeaTitle] = asyncio.Queue()
    for idea in ideas:
        queue.put_nowait(idea)

    results: list[DetailResult] = []

    async def consume(slot_agent) -> None:
        while not queue.empty():
            try:
                idea = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            results.append(await run_detail(slot_agent, idea))

    await asyncio.gather(*(consume(slot) for slot in slots))

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
            title_agent, titles_prompt(), IdeaTitles, "titles"
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
