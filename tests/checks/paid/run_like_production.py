"""COSTS MONEY: one real generation run, wired exactly the way production is.

    uv run content-studio-server                          (another terminal)
    uv run python tests/checks/paid/run_like_production.py
    uv run python tests/checks/paid/run_like_production.py --phase detail --format Carusel
    uv run python tests/checks/paid/run_like_production.py --debug --spans spans.json

Or F5 on "6. One real run" with no command line at all, which is what
`FROM_THE_UI` at the bottom of this file is for: the generator form, in code,
where a breakpoint can reach it.

Three things, top to bottom, in the order they happen:

  1. THE INPUT, built by the harness's own builders. Nothing is re-typed here:
     the profile comes off Neon over MCP and the agent out of
     `GenerationCoordinator`. The source material is NOT assembled here or
     anywhere - since 2026-08-27 the agent fetches it itself, with its own
     tools (`search_books`, `search_web`), following the skill, exactly as it
     would in a conversation. Watch for those tool calls in step 4's spans.
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
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
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
from content_studio.harness.generation import (
    GenerationBatchRequest,
    IdeaTitle,
    detail_output_type,
    detail_prompt,
    title_prompt,
)
from content_studio.harness.generator import (
    GenerationCoordinator,
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

#: How much of one debug line survives. The SDK logs whole requests, and one of
#: them carries a 30,000-character system prompt: uncapped, the first model call
#: buries every step after it. The head plus a count of what was cut is enough to
#: tell which call this was, and `--spans` keeps the payloads whole anyway.
DEBUG_LINE_CAP = 400

#: What a span is worth reading back for, in the order it reads. Phoenix flattens
#: its attributes, so these are the keys as they arrive rather than a nested path.
SPAN_FIELDS = (
    "tool.name",
    "input.value",
    "output.value",
    "llm.token_count.prompt",
    "llm.token_count.prompt_details.cache_read",
    "llm.token_count.completion",
)


def rule(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def _cap_line(record: logging.LogRecord) -> bool:
    """Shorten a record in place. A filter, because it must reach every handler."""
    text = record.getMessage()
    if len(text) > DEBUG_LINE_CAP:
        record.msg = f"{text[:DEBUG_LINE_CAP]}… (+{len(text) - DEBUG_LINE_CAP:,} chars)"
        record.args = ()
    return True


def turn_on_debug() -> None:
    """Every step the SDK takes, live, with the payloads it hides by default.

    Two loggers and no more. Putting the ROOT at DEBUG would also turn on
    `httpcore`, which narrates every frame of the connection to OpenAI and says
    nothing about the run - so the level goes on the two loggers that do, and
    their records still reach the root's handler, which has no level of its own.

    The redaction flags are module constants in `agents._debug`, read from the
    environment when that module is imported - and it was imported at the top of
    this file, long before this function is called. Setting the variable here
    would be too late, so the constants are assigned instead. Without this, every
    tool call and every model reply logs as `[redacted]`.
    """
    from agents import _debug as agents_debug

    agents_debug.DONT_LOG_MODEL_DATA = False
    agents_debug.DONT_LOG_TOOL_DATA = False

    for name in ("openai.agents", "content_studio"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_cap_line)


def span_ms(span: dict[str, Any]) -> str:
    """How long a span took, when both ends parse. Blank rather than a guess."""
    try:
        start = datetime.fromisoformat(str(span["start_time"]))
        end = datetime.fromisoformat(str(span["end_time"]))
    except (KeyError, TypeError, ValueError):
        return ""
    return f"{(end - start).total_seconds() * 1000:>7,.0f}ms"


def span_detail(span: dict[str, Any], cap: int) -> None:
    """The inside of one span: the command it ran, what came back, what it cost.

    This is the half `--debug` exists for. A span list tells you the model opened
    a shell; only the payload tells you whether it read `SKILL.md` or ran `bash`
    and answered from memory - the one failure of this design that does not raise.
    """
    attributes = span.get("attributes") or {}
    for key in SPAN_FIELDS:
        value = attributes.get(key)
        if value in (None, ""):
            continue
        text = " ".join(str(value).split())
        if len(text) > cap:
            text = f"{text[:cap]}… (+{len(text) - cap:,} chars)"
        print(f"{'':>14}{key:<38} {text}")


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


def describe_input(agent, profile_md: str, prompt: str, label: str) -> None:
    print(f"  model          {agent.model}")
    print(f"  agent prompt   {len(agent.instructions):>7,} chars")
    print(f"                 {len(profile_md):>7,} of which the profile, from Neon")
    print(f"  user message   {len(prompt):>7,} chars")
    print("  material       none up front - the agent fetches its own, per the skill")
    print(f"  workflow       {workflow_name(label)}")
    print("\n  (every layer verbatim: tests/checks/safe/show_agent_input.py --live --full)")


#: What a failure means, in the words of the thing that has to be fixed.
#:
#: Until 2026-08-28 every exception here printed one guess - "is
#: `uv run content-studio-server` running?" - and on the day E2B blocked the
#: team for reaching its billing limit, that guess sent the reading in the
#: wrong direction: the MCP server WAS running, it had answered twice, and its
#: two 200s were on screen above the error. A hint that is right once and
#: confident always is worse than no hint, because it is read as a diagnosis.
#: Each entry below matches on what the failure actually says.
DIAGNOSES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("billing limit", "team is blocked"),
        "E2B a blocat contul: plafonul de facturare e atins. Nu e cod - se ridica"
        " limita in e2b.dev/dashboard, la Team → Billing. Fara container nu se"
        " poate citi metoda, deci nicio rulare nu porneste pana atunci.",
    ),
    (
        ("e2b_api_key", "sandboxexception", "403", "401"),
        "Sandbox-ul n-a pornit. Cheia E2B din .env, si contul din e2b.dev.",
    ),
    (
        ("connection", "connect", "8765", "econnrefused"),
        "Nimeni nu raspunde pe 8765: porneste `uv run content-studio-server`.",
    ),
    (
        ("modelbehaviorerror", "invalid json"),
        "Modelul a rupt contractul structurat. Productia reincearca o data pentru"
        " exact clasa asta; scriptul asta nu. Ruleaza din nou inainte sa cauti"
        " vinovatul in cod.",
    ),
)


def diagnose(e: Exception) -> list[str]:
    """The lines printed under a failure. Empty when nothing is recognised."""
    haystack = f"{type(e).__name__} {e}".lower()
    hits = [text for needles, text in DIAGNOSES if any(n in haystack for n in needles)]
    # Silence beats a guess: an unrecognised failure gets its own message and
    # nothing else, which is the honest amount of help available.
    return hits or ["Eroare nerecunoscuta - citeste mesajul de mai sus, e tot ce se stie."]


async def main(argv: list[str] | None = None) -> int:
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="the SDK's own steps live, and every span's payload at the end",
    )
    parser.add_argument(
        "--debug-chars",
        type=int,
        default=600,
        help="how much of each span attribute to print (--debug only)",
    )
    parser.add_argument(
        "--spans",
        type=Path,
        default=None,
        help="write the run's Phoenix spans, whole, to this file",
    )
    args = parser.parse_args(argv)

    # FIRST, BEFORE ANYTHING MAKES A SPAN. `configure_phoenix` installs its own
    # TracerProvider and instruments the agent SDK; an agent built before it
    # would hold an uninstrumented tracer. The harness does this inside
    # `observability.configure(app)`, which also wires Application Insights when
    # a connection string exists - absent here because this script has no
    # FastAPI app to instrument, not because it is optional in production.
    configure_logging()
    if args.debug:
        turn_on_debug()
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

    # One connection is enough now: the internal one existed to pre-collect the
    # source packet, and the packet is gone - the agent brings its own material
    # through these very tools, which is what the tool filter is for.
    data_mcp = MCPServerStreamableHttp(
        params={"url": MCP_URL, "headers": headers},
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(GENERATION_VISIBLE_TOOLS)},
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
        await data_mcp.connect()

        rule("1. THE INPUT, from the harness's own builders")
        _, profile_md = await read_profile(data_mcp)
        label = f"demo-{uuid4().hex[:8]}"
        if args.phase == "title":
            agent = coordinator._title_agent(
                profile_md, data_mcp, request, args.language, label
            )
            prompt = title_prompt(request, profile_md, language=args.language)
            output_type = agent.output_type
        else:
            agent = coordinator._detail_agent(
                profile_md, data_mcp, request, args.language, label
            )
            prompt = detail_prompt(
                request, SAMPLE_IDEA, profile_md, language=args.language
            )
            output_type = detail_output_type(request.format)

        print(f"  request        {describe_batch(request)}")
        describe_input(agent, profile_md, prompt, label)

        # The id is born here, and `open_run` calls `bind_run` - which is why
        # nothing below passes it to anybody. Every log line and every span from
        # this point on stamps itself.
        run_id = await trail.open_run(session_id, describe_batch(request))
        print(f"\n  run_id         {run_id}   (bound: {current_run()})")

        rule("2. THE RUN — the same call a click makes")
        print("  one container, then the model. This is the part that costs money.\n")
        clock = perf_counter()
        result = await coordinator._run_agent(agent, prompt, output_type, label, label)
        seconds = perf_counter() - clock

        rule(f"3. WHAT CAME BACK — after {seconds:,.1f}s")
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
        for line in diagnose(e):
            print(f"  {line}", file=sys.stderr)
        # The run row exists from `open_run` on, and a failure that leaves it
        # open is a run that never ends - the same shape of missing record this
        # script was pointed at on 2026-08-28. Production marks it; so does this.
        await trail.failed(run_id, e)
        return 1
    finally:
        await asyncio.gather(
            data_mcp.cleanup(), return_exceptions=True
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

    # The report is printed, the request log is logged, and both go to stdout
    # with no shared lock - so an httpx line lands in the middle of a span's
    # payload and the table stops being readable. Nothing below is worth a log
    # line anyway: what it reads, it prints.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    print(f"\n  Neon     public.traces    {neon_spans or 0} spans for this run_id")
    if phoenix["ok"]:
        spans = arrived_in_phoenix(run_id, started)
        print(f"  Phoenix  {PHOENIX_PROJECT_NAME:<16} {len(spans)} spans carrying studio.run_id\n")
        for span in sorted(spans, key=lambda s: str(s.get("start_time") or "")):
            # `span_kind` is a column of its own here, not an attribute: the
            # OpenInference attribute is promoted by Phoenix on ingest.
            print(
                f"    {span_ms(span)}  {span.get('span_kind', '?'):<10}"
                f" {span.get('name', '?')}"
            )
            if args.debug:
                span_detail(span, args.debug_chars)
        if args.spans is not None:
            args.spans.write_text(
                json.dumps(spans, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"\n  written: {args.spans}   ({len(spans)} spans, whole)")
        print(f"\n  {project_url()}")
    return 0


#: THE GENERATOR FORM, filled in as if you had clicked it - the four fields of
#: `Generator.razor`, in its own words. Edit them and press F5: a debugger has
#: no command line to type into, and a run whose settings live in a launch
#: configuration is a run whose settings you have to leave the file to change.
#:
#: MIND THE CLOCKS while you sit on a breakpoint. Three of them are running and
#: none of them knows you are reading: the model call is wrapped in
#: `asyncio.wait_for(RUN_TIMEOUT_SECONDS)` - 20 minutes - the E2B container
#: expires after `SANDBOX_TIMEOUT_SECONDS`, 10 minutes, and an MCP call gives up
#: after `MCP_TIMEOUT`, 90 seconds. Stopping inside the run for longer than that
#: does not pause them; it fails the run, and the tokens are spent either way.
FROM_THE_UI = [
    "--format", "Reel",      # Reel | Carusel | Stories
    "--pillar", "Educație",  # Poziționare | Educație | Conexiune | Conversie | Magnetism
    "--source", "Cărți",   # Memorie | Cărți | Internet | Combinat
    # "--focus", "despre limite la job",   # the form's fourth field, optional
    "--phase", "title",      # NOT a form field - see below
    "--debug",               # every step live, and every span's payload at the end
]  # fmt: skip
# `--phase` is the one argument here with no control in `Generator.razor`, and
# that is not an omission: the interface has no phase picker because the two
# phases are two different gestures. "Generare" runs the titles; opening one of
# the ten runs the detail, minutes or days later. This script makes one call, so
# it has to be told which of the two - and `detail` then develops `SAMPLE_IDEA`,
# because phase 2 never invents a title, it develops one phase 1 already wrote.


if __name__ == "__main__":
    # A command line, when there is one, still wins - nothing about running this
    # from a terminal changes. `FROM_THE_UI` is what F5 sends, because F5 sends
    # nothing.
    raise SystemExit(asyncio.run(main(sys.argv[1:] or FROM_THE_UI)))
