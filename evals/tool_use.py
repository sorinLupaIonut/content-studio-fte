"""Metric 1, `tool_use` — layer 4 of the eval pyramid: right tool, one label.

    uv run content-studio-server          # terminal 1
    uv run python evals/tool_use.py       # terminal 2: local run, prints verdicts
    uv run python evals/tool_use.py --phoenix   # same run, as a Phoenix experiment
    uv run python evals/tool_use.py --id propuneri-direct

WHAT IS MEASURED. Layer 4 of the eval pyramid — the right tools got called —
with one label per case: the list of tools the run must call, in any order,
skills included, because a skill here IS a tool (AGENTS.md rule 4). An empty
list means the route must be empty, which covers both honest chat cases
("the right move is to ask, not to call") and the whole generation door: the
method is already in the prompt there (`method.py`), so any call at all is a
wasted turn and evidence the preloaded block contradicts itself. Live runs
carry the generation branch on their `session_id` ("generation…"), which is
how `monitor.py` will pick it for real traffic; `usa` in the dataset only
tells the runner HOW to run a case (chat turns vs a brief), never what to
expect.

One question per metric, the way the course splits its labs — and the two
metrics cover each other's blind side: convergence (metric 2) charges for
every surplus call but rewards a missing one, so this metric owns "nothing
required is missing" and metric 2 owns "nothing superfluous". Order of calls
is a trace eval, deferred; unapproved writes belong to metric 8 (policy).
First-skill checks, required order and forbidden lists all used to be folded
in here; they were cut on 2026-08-26.

CODE, NOT A JUDGE, because the labels exist: `tool-use-dataset.json` writes the
correct route next to each message. Comparing a recorded route with a written
one is `==`, and a rule settled by `==` should never cost a model call. The
judge variant (Phoenix's TOOL_CALLING template) belongs to live chat traffic,
where nobody has written the label — that is `monitor.py`'s job, not this
file's.

THE GENERATION PROBE IS THE REAL SHAPE, NOT A REPLICA: the same
`build_worker`, the same `title_prompt`, and the same sandbox the coordinator
opens - which since 2026-08-27 is the whole point, because the method is read
from files inside it. What the probe skips is the persistence machinery
(drafts, batches, structured output), because none of it can change which tools
the model reaches for.

ONE CONTAINER PER CASE, opened here rather than once for the file: a case that
left its own state behind would make the next one cheaper and less honest, and
the container is where the method lives.

WRITES ARE REFUSED, the same rule the old runner had: an eval must not leave
posts or profile changes behind, so every approval interruption is rejected and
the attempted tool still lands in the route — an attempt is routing evidence.

WITH --phoenix the same six cases become a dataset in Phoenix Cloud and the
same code path runs as `run_experiment`, so the results land next to the traces
the run produced and two versions of the method can be compared side by side.
Local mode needs no Phoenix and no key; it is the cheap loop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents import Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig

from content_studio import enable_utf8_output
from content_studio.audit import calls_in
from content_studio.config import (
    MCP_TIMEOUT,
    MCP_URL,
    PHOENIX_API_KEY,
    PHOENIX_COLLECTOR_ENDPOINT,
)
from content_studio.mcp_server.protocol import MODEL_VISIBLE_TOOLS
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import (
    GATED_TOOLS,
    build_worker,
    describe_request,
    read_profile,
)

enable_utf8_output()

HERE = Path(__file__).parent
DATASET_FILE = HERE / "tool-use-dataset.json"
REPORTS = HERE / "reports"

def load_cases(ids: list[str] | None) -> list[dict[str, Any]]:
    data = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    cases = data["cazuri"]
    if ids:
        unknown = set(ids) - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"Cazuri necunoscute: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in ids]
    return cases


async def run_without_writing(worker, message, config):
    """Run one turn and refuse every approval interruption.

    Returns (result, attempted_writes). The attempts join the route: a model
    that reached for `save_post` routed there, whether or not the gate let it.
    """
    result = await Runner.run(worker, message, run_config=config)
    attempts: list[str] = []
    retries = 0
    while result.interruptions:
        retries += 1
        if retries > 5:
            raise RuntimeError("agentul insistă să scrie după cinci refuzuri")
        state = result.to_state()
        for request in result.interruptions:
            name, _, _ = describe_request(request)
            attempts.append(name)
            state.reject(request, rejection_message="Evaluarea nu aprobă nicio scriere.")
        result = await Runner.run(worker, state, run_config=config)
    return result, attempts


async def route_of_generation(
    data_mcp, profile_md: str, brief: dict[str, Any]
) -> tuple[list[str], str]:
    """One title run, door 2 — production pieces, no persistence."""
    from content_studio.harness.generation import GenerationBatchRequest, title_prompt

    worker = build_worker(profile_md, data_mcp)
    request = GenerationBatchRequest(
        format=brief["format"],
        pillar=brief["pilon"],
        source=brief["sursa"],
        focus=brief.get("focus"),
    )
    async with sandbox_run_config("tool-use-generation") as sandbox:
        result, attempts = await run_without_writing(
            worker, title_prompt(request, profile_md), RunConfig(sandbox=sandbox)
        )
    route = [call["name"] for call in calls_in(result)] + attempts
    # The course's Trajectory lab counts the message history as the path; the
    # convergence score (metric 2) will read this off the same experiments.
    return route, str(result.final_output), len(result.to_input_list())


async def route_of_variant_chat(
    data_mcp, profile_md: str, case: dict[str, Any]
) -> tuple[list[str], str, int]:
    """The selected-idea flow — the most common one: a variant open, edits in chat.

    Production pieces again: the server-verified target context goes through
    `chat_prompt` and the answer comes back through the structured
    `ChatTurnOutput`, where the edit is a patch. A healthy run calls nothing —
    the write stays a browser draft until she saves and confirms at the gate —
    which is exactly what the empty label asserts.
    """
    from content_studio.harness.chat import ChatTurnOutput, chat_prompt

    worker = build_worker(profile_md, data_mcp, output_type=ChatTurnOutput)
    async with sandbox_run_config("tool-use-variant") as sandbox:
        result, attempts = await run_without_writing(
            worker,
            chat_prompt(case["turns"][0], case["tinta"]),
            RunConfig(sandbox=sandbox),
        )
    route = [call["name"] for call in calls_in(result)] + attempts
    reply = getattr(result.final_output, "reply", None) or str(result.final_output)
    return route, reply, len(result.to_input_list())


async def route_of(worker, turns: list[str]) -> tuple[list[str], str, int]:
    """The ordered tool route across all turns, plus the final answer.

    One container for the whole case, not one per turn: the turns are a single
    conversation, and a model that opened the method on turn one has read it for
    turn two. Re-mounting between them would measure a conversation nobody has.
    """
    history: list = []
    route: list[str] = []
    final = ""
    async with sandbox_run_config("tool-use-chat") as sandbox:
        config = RunConfig(sandbox=sandbox)
        for message in turns:
            result, attempts = await run_without_writing(
                worker, history + [{"role": "user", "content": message}], config
            )
            history = result.to_input_list()
            final = str(result.final_output)
            route.extend(call["name"] for call in calls_in(result))
            route.extend(attempts)
    return route, final, len(history)


def verdict(route: list[str], expected_tools: list[str]) -> tuple[float, list[str]]:
    """`tool_use` on one case: no required tool is missing.

    The course judges each call with an LLM because it has no ground truth;
    we have a label per case, so the check is code and the label is one
    list - every tool that must be called, skills included, in any order.
    An empty label means the route must be empty too: that is the whole
    generation-door expectation, and also the honest chat cases where the
    right move is to ask, not to call. Nothing else is checked here on
    purpose - metric 2 (convergence) charges for every surplus call but
    rewards a missing one, so this metric owns the missing side; order is
    a trace eval, deferred, and the ordered route is in every report.
    """
    reasons: list[str] = []
    if not expected_tools:
        if route:
            reasons.append(f"nu trebuia chemat niciun tool; ruta: {route}")
    else:
        missing = [t for t in expected_tools if t not in route]
        if missing:
            reasons.append(f"tool-uri cerute care lipsesc din rută: {missing}")
    return (0.0 if reasons else 1.0), reasons


async def run_local(cases: list[dict[str, Any]]) -> int:
    data_mcp = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
        require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
    )
    try:
        await data_mcp.connect()
        _, profile_md = await read_profile(data_mcp)
    except Exception as e:  # noqa: BLE001
        print(f"Serverul MCP nu răspunde la {MCP_URL}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    worker = build_worker(profile_md, data_mcp)
    findings: list[dict[str, Any]] = []
    failures = 0
    try:
        for case in cases:
            started = time.monotonic()
            try:
                if case.get("usa") == "generare":
                    route, final, path_length = await route_of_generation(
                        data_mcp, profile_md, case["brief"]
                    )
                elif case.get("tinta"):
                    route, final, path_length = await route_of_variant_chat(
                        data_mcp, profile_md, case
                    )
                else:
                    route, final, path_length = await route_of(worker, case["turns"])
                score, reasons = verdict(route, case["tools"])
            except Exception as e:  # noqa: BLE001
                route, final, path_length = [], "", 0
                score, reasons = 0.0, [f"rularea a eșuat: {type(e).__name__}: {e}"]
            failures += score < 1.0
            mark = "✓" if score == 1.0 else "✗"
            print(
                f"{mark} {case['id']:<24} {score:.0f}  "
                f"{time.monotonic() - started:>4.0f}s  ruta: {route or ['—']}"
            )
            for reason in reasons:
                print(f"    {reason}")
            findings.append(
                {
                    "case": case["id"],
                    "score": score,
                    "route": route,
                    "path_length": path_length,
                    "reasons": reasons,
                    "final_answer": final[:2000],
                }
            )
    finally:
        await data_mcp.cleanup()

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"tool-use-{stamp}.json"
    out.write_text(
        json.dumps({"generated_at": stamp, "findings": findings}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"\ntool_use: {len(cases) - failures}/{len(cases)} · {out.relative_to(HERE.parent)}")
    return 1 if failures else 0


def phoenix_client():
    if not (PHOENIX_COLLECTOR_ENDPOINT and PHOENIX_API_KEY):
        raise SystemExit("PHOENIX_COLLECTOR_ENDPOINT sau PHOENIX_API_KEY lipsește din .env")
    from phoenix.client import Client

    # `.env` holds the OTLP endpoint, path included - that is what the span
    # exporter wants. The REST client wants the space root, so the trace path
    # comes off; anything else in the URL (host, space) is shared by both.
    base_url = PHOENIX_COLLECTOR_ENDPOINT.removesuffix("/v1/traces")
    return Client(base_url=base_url, api_key=PHOENIX_API_KEY)


async def run_phoenix(cases: list[dict[str, Any]]) -> int:
    """The same five cases, as a Phoenix dataset + experiment.

    The dataset is versioned by Phoenix itself: uploading again appends a new
    version, so the URL in the UI always shows the current one. The task opens
    its own MCP connection per example — five cases, five cheap connections,
    and no shared state between them.
    """
    from phoenix.client.experiments import async_run_experiment

    client = phoenix_client()
    dataset = client.datasets.create_dataset(
        name="tool-use",
        examples=[
            {
                "input": {
                    "usa": c["usa"],
                    **(
                        {"brief": c["brief"]}
                        if c["usa"] == "generare"
                        else {"turns": c["turns"]}
                    ),
                    **({"tinta": c["tinta"]} if c.get("tinta") else {}),
                },
                "output": {"tools": c["tools"], "expected": c["expected"]},
                "metadata": {"case_id": c["id"]},
            }
            for c in cases
        ],
    )

    async def task(input: dict[str, Any]) -> dict[str, Any]:
        data_mcp = MCPServerStreamableHttp(
            params={"url": MCP_URL},
            name="content-data",
            cache_tools_list=True,
            tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
            client_session_timeout_seconds=MCP_TIMEOUT,
            require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
        )
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
            if input.get("usa") == "generare":
                route, final, path_length = await route_of_generation(
                    data_mcp, profile_md, input["brief"]
                )
            elif input.get("tinta"):
                route, final, path_length = await route_of_variant_chat(
                    data_mcp, profile_md, dict(input)
                )
            else:
                worker = build_worker(profile_md, data_mcp)
                route, final, path_length = await route_of(worker, list(input["turns"]))
        finally:
            await data_mcp.cleanup()
        # The same output shape the course's `process_messages` settles on:
        # the calls, the answer, and the path length - so the convergence
        # evaluator (metric 2) can read future experiments without a re-run.
        return {"route": route, "final_answer": final[:2000], "path_length": path_length}

    def tool_use(output: dict[str, Any], expected: dict[str, Any]) -> tuple[float, str]:
        score, reasons = verdict(output["route"], expected["tools"])
        return score, ("; ".join(reasons) if reasons else "tool-urile corecte")

    experiment = await async_run_experiment(
        dataset=dataset,
        task=task,
        evaluators={"tool_use": tool_use},
        experiment_name=f"tool-use-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}",
        experiment_description="tool_use pe setul etichetat, ambele uși, agentul real",
        # The default is 60s per example and it cancels mid-flight - the
        # generation case alone takes ~100s, and a cancelled MCP session
        # hangs on cleanup. Measured: 5/6 done in 2:29, then 28 minutes stuck.
        timeout=600,
    )
    print(f"\nExperimentul e în Phoenix: {getattr(experiment, 'url', '(vezi UI)')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="tool_use on the labelled routes, both doors")
    parser.add_argument("--id", dest="ids", action="append", help="run only this case; repeatable")
    parser.add_argument("--phoenix", action="store_true", help="upload dataset + run as experiment")
    args = parser.parse_args()
    cases = load_cases(args.ids)
    if args.phoenix:
        return asyncio.run(run_phoenix(cases))
    return asyncio.run(run_local(cases))


if __name__ == "__main__":
    raise SystemExit(main())
