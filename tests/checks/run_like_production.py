"""COSTS MONEY: one real generation run, wired exactly the way production is.

    uv run content-studio-server                          (another terminal)
    uv run python tests/checks/run_like_production.py
    uv run python tests/checks/run_like_production.py --phase detail --format Carusel

Three things, top to bottom, in the order they happen:

  1. THE INPUT, built by the harness's own builders. Nothing is re-typed here:
     the profile comes off Neon over MCP, the source packet off the same tools
     the interface uses, and the agent out of `GenerationCoordinator`. A demo
     that assembled its own prompt would be a second source of truth that agrees
     with production only until somebody edits one of them.
  2. THE RUN, through `GenerationCoordinator._run_agent` - the same call a click
     makes, container and all.
  3. THE PROOF IT ARRIVED, read back out of Phoenix by `run_id` and counted in
     Neon beside it. Not "it should be there now": the spans, listed.

WHY IT EXISTS. `observability.py` wires two destinations and stamps one id onto
everything going to either, but nothing showed that end to end. This is where
you watch the id born, travel, and come back - and where the wiring is checked
against a live collector instead of a unit test's fake.

WHAT IT IS NOT. It writes no batch, idea or variant: `_run_agent` is the model
call alone, so nothing here can reach a gated write or leave rows in the
generation tables. One `runs` row and its traces are the whole footprint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agents.mcp import MCPServerStreamableHttp
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import Audit
from content_studio.config import (
    CLIENT_SLUG,
    MCP_TIMEOUT,
    MCP_URL,
    PHOENIX_API_KEY,
    PHOENIX_PROJECT_NAME,
    database_url,
)
from content_studio.harness.drafts import GenerationDraftClient
from content_studio.harness.generation import (
    GenerationBatchRequest,
    IdeaTitle,
    detail_output_type,
    detail_prompt,
    title_prompt,
)
from content_studio.harness.generator import (
    GenerationCoordinator,
    collect_source_packet,
    describe_batch,
    workflow_name,
)
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    GENERATION_VISIBLE_TOOLS,
)
from content_studio.observability import (
    configure_logging,
    configure_phoenix,
    current_run,
    phoenix_api_base,
    record_agent_traces,
    shutdown_phoenix,
)
from content_studio.worker import read_profile

enable_utf8_output()

#: Phase 2 develops a title phase 1 already wrote, so a plausible row stands in
#: for the one that would come off `generation_ideas`.
SAMPLE_IDEA = IdeaTitle(
    ordinal=3,
    title="Formula celor 3 pași pentru un NU blând",
    angle="Trei pași concreți, în ordinea în care se spun",
)

#: How many spans of this run reached Neon. The contrast with Phoenix is the
#: point: Neon is the permanent record, Phoenix the sample the evaluators read,
#: and a run present in one but not the other is a wiring fault worth seeing.
NEON_SPANS_SQL = """
SELECT count(*)
  FROM public.traces t,
       jsonb_array_elements(t.payload->'spans') AS span
 WHERE t.payload ? 'spans' AND t.run_id = $1
"""

#: Strong references to the in-flight trace writes. `create_task` alone does not
#: keep a task alive; the harness holds the same set for the same reason.
_TRACE_WRITES: set[asyncio.Task[None]] = set()

RULE = "─" * 78


def rule(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def trace_sink(trail: Audit):
    """Schedule the trace write without blocking the agent's own execution.

    The same shape as `HarnessService._keep_trace`: called from inside the
    agent's run, so it does the least possible and never raises.
    """

    def keep(run_id: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(trail.sdk_trace(run_id, payload))
        _TRACE_WRITES.add(task)
        task.add_done_callback(_TRACE_WRITES.discard)

    return keep


def project_url() -> str:
    """A link straight to the project, when Phoenix will name its id for us."""
    base = phoenix_api_base()
    try:
        from phoenix.client import Client

        for project in Client(base_url=base, api_key=PHOENIX_API_KEY).projects.list():
            if project.get("name") == PHOENIX_PROJECT_NAME:
                return f"{base}/projects/{project['id']}"
    except Exception:  # noqa: BLE001 - a link is a convenience, never a failure
        pass
    return f"{base}/projects"


def arrived_in_phoenix(run_id: str, since: datetime) -> list[dict[str, Any]]:
    """The spans Phoenix holds for this run. Empty is an answer, not an error."""
    from phoenix.client import Client

    client = Client(base_url=phoenix_api_base(), api_key=PHOENIX_API_KEY)
    spans = client.spans.get_spans(
        project_identifier=PHOENIX_PROJECT_NAME, start_time=since, limit=1000
    )
    # Filtered here rather than server-side: the attribute is nested, and one
    # run's worth of spans is small enough that reading them all costs less than
    # getting a filter expression wrong and reporting a false empty.
    return [
        span
        for span in spans
        if (span.get("attributes") or {}).get("studio.run_id") == run_id
    ]


def describe_input(agent, profile_md: str, prompt: str, packet: dict, label: str) -> None:
    print(f"  model          {agent.model}")
    print(f"  agent prompt   {len(agent.instructions):>7,} chars")
    print(f"                 {len(profile_md):>7,} of which the profile, from Neon")
    print(f"  user message   {len(prompt):>7,} chars")
    print(f"  source packet  {len(json.dumps(packet, ensure_ascii=False)):>7,} chars")
    print(f"  workflow       {workflow_name(label)}")
    print("\n  (every layer verbatim: tests/checks/show_agent_input.py --live --full)")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--wait",
        type=float,
        default=8.0,
        help="seconds to let Phoenix ingest before reading the spans back",
    )
    args = parser.parse_args()

    # FIRST, BEFORE ANYTHING MAKES A SPAN. `configure_phoenix` installs its own
    # TracerProvider and instruments the agent SDK; an agent built before it
    # would hold an uninstrumented tracer. The harness does this inside
    # `observability.configure(app)`, which also wires Application Insights when
    # a connection string exists - absent here because this script has no
    # FastAPI app to instrument, not because it is optional in production.
    configure_logging()
    phoenix = configure_phoenix()
    rule("0. TELEMETRY")
    print(f"  phoenix   {phoenix['detail']}")
    if not phoenix["ok"]:
        print("  ✗ step 4 will have nothing to show; set PHOENIX_* in .env.", file=sys.stderr)

    session_id = f"{CLIENT_SLUG}-production-demo-{uuid4().hex[:8]}"
    headers = {CONVERSATION_HEADER: session_id, CLIENT_HEADER: CLIENT_SLUG}

    url, connect_args = database_url()
    trail = Audit(url, connect_args)
    # The same registration `HarnessService.start` makes. Without it the agent's
    # spans reach Phoenix and nowhere else, and `public.traces` stays empty.
    record_agent_traces(trace_sink(trail))
    print("  neon      public.traces receives the same spans, keyed by run_id")

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
        format=args.format, pillar=args.pillar, source=args.source, focus=args.focus
    )
    # Built without `__init__` on purpose: a coordinator owns background tasks
    # and MCP factories this script does not want. What it needs are the agent
    # builders and `_run_agent`, and those depend only on these two attributes.
    coordinator = GenerationCoordinator.__new__(GenerationCoordinator)
    coordinator._accounts = None
    coordinator._conversations = None
    request = request.model_copy(
        update={"model": GenerationCoordinator._batch_model(request)}
    )

    run_id: str | None = None
    started = datetime.now(UTC) - timedelta(seconds=5)
    try:
        await asyncio.gather(data_mcp.connect(), internal_mcp.connect())

        rule("1. THE INPUT, from the harness's own builders")
        _, profile_md = await read_profile(data_mcp)
        packet = await collect_source_packet(
            internal_mcp, GenerationDraftClient(internal_mcp), request
        )
        label = f"demo-{uuid4().hex[:8]}"
        if args.phase == "title":
            agent = coordinator._title_agent(
                profile_md, data_mcp, request, args.language, label
            )
            prompt = title_prompt(request, packet, args.language)
            output_type = agent.output_type
        else:
            agent = coordinator._detail_agent(
                profile_md, data_mcp, request, args.language, label
            )
            prompt = detail_prompt(request, SAMPLE_IDEA, packet, args.language)
            output_type = detail_output_type(request.format)

        print(f"  request        {describe_batch(request)}")
        describe_input(agent, profile_md, prompt, packet, label)

        # The id is born here, and `open_run` calls `bind_run` - which is why
        # nothing below passes it to anybody. Every log line and every span from
        # this point on stamps itself.
        run_id = await trail.open_run(session_id, describe_batch(request))
        print(f"\n  run_id         {run_id}   (bound: {current_run()})")

        rule("2. THE RUN — the same call a click makes")
        print("  one container, then the model. This is the part that costs money.\n")
        result = await coordinator._run_agent(agent, prompt, output_type, label, label)

        rule("3. WHAT CAME BACK")
        payload = result.model_dump() if hasattr(result, "model_dump") else result
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # WHOLE, not a preview. A cap here hid proposals 8, 9 and 10 - the
        # tail of a batch is where sameness shows, so truncating the output
        # truncates the evidence. Redirect the run if the terminal is small.
        if isinstance(payload, dict) and isinstance(payload.get("ideas"), list):
            for idea in payload["ideas"]:
                print(f"  {idea['ordinal']:>2}. [{idea['angle_type']}] {idea['title']}")
                print(f"      {idea['angle']}\n")
        else:
            print(text)
        await trail.close_run(run_id, text[:400])
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ {type(e).__name__}: {e}", file=sys.stderr)
        print("  is `uv run content-studio-server` running?", file=sys.stderr)
        return 1
    finally:
        await asyncio.gather(
            data_mcp.cleanup(), internal_mcp.cleanup(), return_exceptions=True
        )

    rule("4. WHERE IT WENT")
    # `shutdown_phoenix` flushes the batch processor. Without it a script that
    # exits promptly drops the very spans it just made - the failure that looks
    # like "Phoenix is broken" and is really "the process left early".
    print(f"  flushing Phoenix, then waiting {args.wait:.0f}s for ingest…")
    if _TRACE_WRITES:
        await asyncio.gather(*_TRACE_WRITES, return_exceptions=True)
    shutdown_phoenix()
    await asyncio.sleep(args.wait)

    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            neon_spans = await conn.fetchval(NEON_SPANS_SQL, run_id)
    finally:
        await engine.dispose()
    await trail.close()

    print(f"\n  Neon     public.traces    {neon_spans or 0} spans for this run_id")
    if phoenix["ok"]:
        spans = arrived_in_phoenix(run_id, started)
        print(f"  Phoenix  {PHOENIX_PROJECT_NAME:<16} {len(spans)} spans carrying studio.run_id\n")
        for span in sorted(spans, key=lambda s: str(s.get("start_time") or "")):
            # `span_kind` is a column of its own here, not an attribute: the
            # OpenInference attribute is promoted by Phoenix on ingest.
            print(f"    {span.get('span_kind', '?'):<10} {span.get('name', '?')}")
        print(f"\n  {project_url()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
