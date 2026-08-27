"""Metric 2, `convergenta` — the course's Trajectory lab on our agent.

    uv run content-studio-server              # terminal 1
    uv run python evals/convergence.py        # terminal 2: local run
    uv run python evals/convergence.py --phoenix  # same run, as an experiment

WHAT IS MEASURED. One intent, many phrasings, and how efficiently the agent
reaches the same destination each time: score = optimal_path / observed
path_length, capped at 1.0 — the formula from the course's Trajectory lab.
`path_length` counts the history entries at the end of the run (message, each
tool call, each tool result, each model message), the same number metric 1
already records on every case.

THE LABEL IS THE OPTIMUM, NOT THE ROUTE. `optimal_path` in the dataset says
what a healthy run costs (6: message → skill call → method text → answer).
The report also prints the empirical minimum across the runs — the way the
course derives it — so a wrong label shows up as every run scoring low while
the empirical minimum sits elsewhere. Correct the label from that evidence.

THE PAIR: tool_use (metric 1) owns "nothing required is missing"; this metric
owns "nothing superfluous", because a missing call makes the path SHORTER and
would score BETTER here — measured on 2026-08-26: the same book-search case
walked 15, 18 and 32 steps to the same destination.

Writes are refused the same way as metric 1; the shared pieces are imported
from `evals/tool_use.py` rather than repeated.
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

from agents.mcp import MCPServerStreamableHttp

sys.path.insert(0, str(Path(__file__).parent))

from tool_use import phoenix_client, route_of  # noqa: E402

from content_studio import enable_utf8_output  # noqa: E402
from content_studio.config import MCP_TIMEOUT, MCP_URL  # noqa: E402
from content_studio.mcp_server.protocol import MODEL_VISIBLE_TOOLS  # noqa: E402
from content_studio.worker import GATED_TOOLS, build_worker, read_profile  # noqa: E402

enable_utf8_output()

HERE = Path(__file__).parent
DATASET_FILE = HERE / "convergence-dataset.json"
REPORTS = HERE / "reports"


def load_dataset() -> dict[str, Any]:
    return json.loads(DATASET_FILE.read_text(encoding="utf-8"))


def data_mcp_server() -> MCPServerStreamableHttp:
    return MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
        require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
    )


def convergence(optimal: int, observed: int) -> float:
    if observed <= 0:
        return 0.0
    return min(1.0, optimal / observed)


async def run_local() -> int:
    data = load_dataset()
    optimal = data["optimal_path"]
    server = data_mcp_server()
    try:
        await server.connect()
        _, profile_md = await read_profile(server)
    except Exception as e:  # noqa: BLE001
        print(f"Serverul MCP nu răspunde la {MCP_URL}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    worker = build_worker(profile_md, server)
    findings: list[dict[str, Any]] = []
    try:
        for phrase in data["formulari"]:
            started = time.monotonic()
            try:
                route, _final, path = await route_of(worker, [phrase])
                score = convergence(optimal, path)
            except Exception as e:  # noqa: BLE001
                route, path, score = [], 0, 0.0
                print(f"  rularea a eșuat: {type(e).__name__}: {e}", file=sys.stderr)
            print(
                f"{score:.2f}  path={path:>2}  {time.monotonic() - started:>4.0f}s  "
                f"ruta: {route or ['—']}  «{phrase[:48]}»"
            )
            findings.append(
                {"formulare": phrase, "path_length": path, "route": route, "score": score}
            )
    finally:
        await server.cleanup()

    paths = [f["path_length"] for f in findings if f["path_length"] > 0]
    scores = [f["score"] for f in findings]
    empirical = min(paths) if paths else 0
    mean = sum(scores) / len(scores) if scores else 0.0
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"convergence-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "intent": data["intent"],
                "optimal_path": optimal,
                "empirical_min_path": empirical,
                "mean_convergence": round(mean, 3),
                "findings": findings,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"\nconvergenta: medie {mean:.2f} · optim etichetat {optimal} · "
        f"minim empiric {empirical} · {out.relative_to(HERE.parent)}"
    )
    if empirical and empirical != optimal:
        print(
            f"atenție: minimul empiric ({empirical}) diferă de eticheta ({optimal}) — "
            "dovadă pentru corectarea etichetei, într-un sens sau altul"
        )
    return 0


async def run_phoenix() -> int:
    """The same phrasings as a Phoenix dataset + experiment."""
    from phoenix.client.experiments import async_run_experiment

    data = load_dataset()
    optimal = data["optimal_path"]
    client = phoenix_client()
    dataset = client.datasets.create_dataset(
        name="convergence",
        examples=[
            {
                "input": {"formulare": phrase},
                "output": {"optimal_path": optimal, "intent": data["intent"]},
                "metadata": {"ordinal": i + 1},
            }
            for i, phrase in enumerate(data["formulari"])
        ],
    )

    async def task(input: dict[str, Any]) -> dict[str, Any]:
        server = data_mcp_server()
        try:
            await server.connect()
            _, profile_md = await read_profile(server)
            worker = build_worker(profile_md, server)
            route, final, path = await route_of(worker, [input["formulare"]])
        finally:
            await server.cleanup()
        return {"route": route, "path_length": path, "final_answer": final[:2000]}

    def convergenta(output: dict[str, Any], expected: dict[str, Any]) -> tuple[float, str]:
        score = convergence(expected["optimal_path"], output["path_length"])
        return score, f"drum {output['path_length']} față de optimul {expected['optimal_path']}"

    await async_run_experiment(
        dataset=dataset,
        task=task,
        evaluators={"convergenta": convergenta},
        experiment_name=f"convergence-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}",
        experiment_description="convergenta pe o intenție, opt formulări, agentul real",
        timeout=600,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="convergence over phrasings of one intent")
    parser.add_argument("--phoenix", action="store_true", help="upload dataset + run experiment")
    args = parser.parse_args()
    if args.phoenix:
        return asyncio.run(run_phoenix())
    return asyncio.run(run_local())


if __name__ == "__main__":
    raise SystemExit(main())
