"""Four surfaces, one id.

The deployment course names four observability surfaces and ties them together
with a shared `run_id`. All four are wired here:

* **OpenTelemetry spans**, exported to Application Insights - where a request
  went, how long each hop took, which one threw.
* **Every log line**, which carries the same `run_id` whether it is printed to
  the container's stdout or shipped to Application Insights. That is a log
  record factory, not a handler filter, and `install_run_id_factory` explains
  why the difference decides whether the id survives the export.
* **The audit trail in Neon**, keyed by that same `run_id`, which `replay.py`
  already reconstructs turn by turn.
* **Phoenix**, which gets the agent's own steps in OpenInference form - the
  surface evaluators read, and the one that answers "is the behaviour drifting"
  rather than "what happened in this run". It was refused once, on the grounds
  that `public.traces` already holds a durable, replayable record; that stays
  true, and Phoenix does not replace it. It is off unless a key is present, and
  when it is off nothing else changes.

Sampling is 100%, and it has to be *asked for*. The course samples roughly a
tenth of the successful runs because it assumes production traffic. This studio
has three accounts. Dropping nine runs in ten would throw away the only evidence
of a fault that happens once a week, and would save nothing worth saving.

That paragraph used to be a claim rather than a fact. `configure_azure_monitor`
called with no sampling argument does NOT keep everything: in
azure-monitor-opentelemetry 1.8.9 the default branch builds a
`RateLimitedSampler(target_spans_per_second_limit=5.0)`. Verified against the
live resource on 2026-08-23 - one page load fires around forty asset requests in
two seconds, so the limit was reached constantly and Application Insights held
319 records standing in for 490 requests, each carrying an `itemCount` the portal
extrapolates from. Charts stayed correct; the individual trace you go looking for
after an incident was often simply not there. `sampling_ratio=1.0` selects
`ApplicationInsightsSampler(1.0)` instead, which keeps every span.

Everything here degrades to silence. With no connection string the harness runs
exactly as it did before, logging to stdout - the same rule the sandbox and the
database already follow.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from content_studio.config import (
    APPLICATIONINSIGHTS_CONNECTION_STRING,
    PHOENIX_API_KEY,
    PHOENIX_COLLECTOR_ENDPOINT,
    PHOENIX_PROJECT_NAME,
)

# The thread that ties the three surfaces together. A ContextVar rather than a
# parameter because a run crosses about twenty call sites and several spawned
# tasks; each task inherits a copy at creation, which is exactly the scope of a
# run.
RUN_ID: ContextVar[str] = ContextVar("run_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)-7s [run=%(run_id)s] %(name)s: %(message)s"

#: What this process calls itself in telemetry. Matches the container app name so
#: a row in Application Insights and a revision in Azure are obviously the same
#: thing. The MCP server is a separate container and names itself separately.
SERVICE_HARNESS = "studio-harness"

_configured = False
_factory_installed = False

log = logging.getLogger("content_studio")


def bind_run(run_id: str) -> None:
    """Tie everything that follows in this task to one run.

    Called once, where the id is born - `Audit.open_run`. From there the log
    filter picks it up for free, and the current span carries it as an
    attribute, which is what makes an Application Insights search for one
    `run_id` return the matching rows in Neon.
    """
    RUN_ID.set(run_id)
    span = _current_span()
    if span is not None:
        span.set_attribute("studio.run_id", run_id)


def current_run() -> str:
    return RUN_ID.get()


def _current_span() -> Any | None:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - the package is a hard dependency
        return None
    span = trace.get_current_span()
    if not span.get_span_context().is_valid:
        return None
    return span


def install_run_id_factory() -> None:
    """Stamp `run_id` on every record as it is created. Idempotent.

    WHY A FACTORY AND NOT A FILTER. This was a filter, attached to the handlers
    that existed when `configure_logging` ran - and it did not work where it
    mattered most. `configure_azure_monitor` installs its own handler on the
    `content_studio` logger *afterwards*, and a logger runs its own handlers
    before the root's, so the exporter saw each record before the filter on the
    stdout handler had put anything on it. The id was in the terminal and absent
    from Application Insights, which is the surface you search when the terminal
    is gone. Verified against the live resource on 2026-08-23: every exported
    record carried `logger_name` and nothing else.

    A record factory runs at construction, before any handler is consulted and
    before any handler exists, so a handler installed later inherits it for
    free. `record.__dict__` is also exactly where the Azure exporter looks when
    it builds customDimensions.
    """
    global _factory_installed
    if _factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        # `hasattr` rather than an unconditional write: a caller that passed
        # `extra={"run_id": ...}` meant it, and this is not the place to argue.
        if not hasattr(record, "run_id"):
            record.run_id = RUN_ID.get()
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def configure_logging(level: int = logging.INFO) -> None:
    """Every handler, including ones installed later, gets the run id."""
    install_run_id_factory()

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    formatter = logging.Formatter(LOG_FORMAT)
    # uvicorn attaches its own handlers to its own loggers with propagate off,
    # so walking the root alone would leave the access log unformatted.
    names = ["", "uvicorn", "uvicorn.error", "uvicorn.access", "content_studio"]
    for name in names:
        for handler in logging.getLogger(name).handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setFormatter(formatter)


def configure(app: Any) -> dict[str, Any]:
    """Wire OpenTelemetry to Application Insights. Safe without a key.

    Returns what `/health` reports, so that "is this thing recording?" is a
    question the deployed app answers about itself rather than one you go and
    ask a portal.
    """
    global _configured

    configure_logging()

    # Independent of Application Insights on purpose: the two surfaces answer
    # different questions, and a studio running locally with no Azure at all can
    # still send the agent's steps somewhere it can look at them.
    phoenix = configure_phoenix()

    if not APPLICATIONINSIGHTS_CONNECTION_STRING:
        return {
            "ok": False,
            "phoenix": phoenix,
            "detail": (
                "APPLICATIONINSIGHTS_CONNECTION_STRING lipsește; "
                "urmele rămân doar în stdout și în Neon."
            ),
        }
    if _configured:
        return {
            "ok": True,
            "phoenix": phoenix,
            "detail": "Application Insights primește urmele.",
        }

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    except ImportError as exc:  # pragma: no cover - a partial install
        return {
            "ok": False,
            "phoenix": phoenix,
            "detail": f"Pachetele de telemetrie lipsesc ({exc.name}).",
        }

    configure_azure_monitor(
        connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING,
        logger_name="content_studio",
        # Keep every span. See the header of this module for what the default
        # does instead, and how it was caught.
        sampling_ratio=1.0,
        # Without this every row arrives as `cloud_RoleName: unknown_service`,
        # which is what the Application Map and the Roles tab group by. Two
        # container apps and no way to tell them apart is not a map.
        resource=Resource.create({SERVICE_NAME: SERVICE_HARNESS}),
        # The distro instruments FastAPI itself, by patching the constructor -
        # which would have no effect on an app already built, and would double
        # every server span on one built later. Own it here instead, where the
        # app is in hand and the health probe can be excluded.
        instrumentation_options={
            "fastapi": {"enabled": False},
            "django": {"enabled": False},
            "flask": {"enabled": False},
            "psycopg2": {"enabled": False},
        },
    )

    # `/health` is polled by Container Apps every few seconds. Left in, it would
    # be most of the telemetry and none of the information.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    AsyncPGInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    _configured = True
    log.info("observability: Application Insights wired, sampling everything")
    return {
        "ok": True,
        "phoenix": phoenix,
        "detail": "Application Insights primește urmele.",
    }


# ---- the agent's own trace ---------------------------------------------------
# The SDK keeps a second, richer trace of its own: which agent ran, which tool it
# called, what the model was asked and answered. It was leaving no mark here -
# `public.traces` held one row per run with the final reply and nothing about how
# it was reached, and the SDK's `group_id` was the session, not the run. So the
# audit could say a run happened and `replay.py` could show the turns, but the
# steps between them lived only in OpenAI's dashboard.


class RunTraceProcessor:
    """Collect the SDK's spans and hand each finished trace to a sink.

    Registered with `agents.tracing.add_trace_processor`, so it sits beside
    whatever else is exporting rather than replacing it.

    The run id is read from the ContextVar, never passed in - the rule the rest
    of this module already follows. `on_trace_start` runs in the task that
    called `Runner.run`, which is the task `bind_run` bound, and child tasks
    inherit the value at creation.

    The sink must not block and must not raise: these callbacks run inside the
    agent's own execution, and telemetry that can stall a run is worse than no
    telemetry. Everything here is wrapped accordingly.
    """

    def __init__(self, sink: Callable[[str, dict[str, Any]], None]) -> None:
        self._sink = sink
        self._runs: dict[str, str] = {}
        self._spans: dict[str, list[dict[str, Any]]] = {}
        # The interface documents these as thread-safe; the SDK may end a span
        # from a worker thread even when the run itself is a coroutine.
        self._lock = threading.Lock()

    def on_trace_start(self, trace: Any) -> None:
        with self._lock:
            self._runs[trace.trace_id] = current_run()

    def on_span_start(self, span: Any) -> None:
        return None

    def on_span_end(self, span: Any) -> None:
        try:
            exported = span.export() or {}
        except Exception:  # noqa: BLE001
            return
        with self._lock:
            self._spans.setdefault(span.trace_id, []).append(exported)

    def on_trace_end(self, trace: Any) -> None:
        with self._lock:
            run_id = self._runs.pop(trace.trace_id, "-")
            spans = self._spans.pop(trace.trace_id, [])
        # Not every trace belongs to a run: the CLI and anything started outside
        # `Audit.open_run` have no id, and `public.traces.run_id` is a foreign
        # key. Dropping those is right - there is nothing to hang them off.
        if run_id in ("", "-"):
            return
        try:
            payload = {
                "run_id": run_id,
                "trace": trace.export() or {},
                "spans": spans,
            }
            self._sink(run_id, payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("observability: could not hand off a trace: %s", exc)

    def shutdown(self) -> None:
        with self._lock:
            self._runs.clear()
            self._spans.clear()

    def force_flush(self) -> None:
        return None


def record_agent_traces(sink: Callable[[str, dict[str, Any]], None]) -> bool:
    """Register the processor. False when the SDK's tracing is not importable."""
    try:
        from agents.tracing import add_trace_processor
    except ImportError:  # pragma: no cover - the package is a hard dependency
        return False
    add_trace_processor(RunTraceProcessor(sink))
    return True


# ---- the fourth surface: Phoenix ---------------------------------------------
# Neon answers "what happened in this run"; Phoenix answers "is the behaviour
# drifting". Different questions, so both are kept. Phoenix is the sample you
# browse and run evaluators against; `public.traces` stays the durable record,
# and nothing here is allowed to affect it.


def _traces_endpoint(base: str) -> str:
    """Phoenix Cloud hands out a space URL; OTLP wants the `/v1/traces` path.

    Accepting either shape is deliberate: the value is copied out of a web page
    by hand, and a missing suffix would fail as silent non-delivery rather than
    as an error.
    """
    base = base.rstrip("/")
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def _make_run_id_stamp() -> Any:
    """A span processor that stamps `run_id` on every span, from the ContextVar.

    Same move as `install_run_id_factory`, one surface over: nothing has to pass
    the id and nothing has to remember to.

    WHY A SUBCLASS AND WHY BUILT HERE. This was a plain duck-typed object -
    `on_start`, `on_end`, `shutdown`, `force_flush`, which is the whole
    documented `SpanProcessor` interface. It crashed the first span it saw:
    opentelemetry-sdk 1.43 also calls a private `_on_ending` on every registered
    processor, so ending a span raised `AttributeError` from inside the SDK.
    Subclassing inherits that hook and any future one. The class is defined
    inside a function because the base class is imported lazily - this module
    still has to import with no OpenTelemetry SDK present, the rule the rest of
    the file follows.
    """
    from opentelemetry.sdk.trace import SpanProcessor

    class _StampRunId(SpanProcessor):
        def on_start(self, span: Any, parent_context: Any = None) -> None:
            try:
                span.set_attribute("studio.run_id", RUN_ID.get())
            except Exception:  # noqa: BLE001 - telemetry never breaks a run
                pass

    return _StampRunId()


_phoenix_provider: Any | None = None


def configure_phoenix() -> dict[str, Any]:
    """Send the agent's own steps to Phoenix. Safe without a key.

    ITS OWN TRACER PROVIDER, not the global one. The global provider belongs to
    `configure_azure_monitor`, and OpenTelemetry refuses to replace one once set
    - quietly, with a log line, which is the worst way to find out. A second
    provider also bounds the damage: if Phoenix stops answering, the batch
    processor that backs up is not the one Application Insights depends on.
    """
    global _phoenix_provider

    if not (PHOENIX_COLLECTOR_ENDPOINT and PHOENIX_API_KEY):
        return {
            "ok": False,
            "detail": (
                "PHOENIX_COLLECTOR_ENDPOINT sau PHOENIX_API_KEY lipsește; "
                "urmele agentului rămân în public.traces."
            ),
        }
    if _phoenix_provider is not None:
        return {"ok": True, "detail": f"Phoenix primește urmele ({PHOENIX_PROJECT_NAME})."}

    try:
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - a partial install
        return {"ok": False, "detail": f"Pachetele Phoenix lipsesc ({exc.name})."}

    try:
        provider = TracerProvider(
            resource=Resource.create(
                {
                    SERVICE_NAME: SERVICE_HARNESS,
                    # How Phoenix decides which project a span belongs to.
                    "openinference.project.name": PHOENIX_PROJECT_NAME,
                }
            )
        )
        # Before the exporting processor: a provider runs its processors in
        # order, and the attribute has to exist before the span is handed on.
        provider.add_span_processor(_make_run_id_stamp())
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=_traces_endpoint(PHOENIX_COLLECTOR_ENDPOINT),
                    headers={"authorization": f"Bearer {PHOENIX_API_KEY}"},
                )
            )
        )
        # `exclusive_processor=False` is not a preference. The default is True,
        # and True calls `agents.set_trace_processors([...])`, which REPLACES the
        # SDK's processor list - taking `RunTraceProcessor` with it and stopping
        # `public.traces` from ever receiving another span. Read out of
        # openinference-instrumentation-openai-agents 2.0.0 on 2026-08-23; if
        # that package is ever upgraded, check this line first.
        OpenAIAgentsInstrumentor().instrument(
            tracer_provider=provider, exclusive_processor=False
        )
    except Exception as exc:  # noqa: BLE001 - never let telemetry refuse a boot
        return {"ok": False, "detail": f"Phoenix nu a putut fi pornit ({exc})."}

    _phoenix_provider = provider
    log.info("observability: Phoenix wired, project=%s", PHOENIX_PROJECT_NAME)
    return {"ok": True, "detail": f"Phoenix primește urmele ({PHOENIX_PROJECT_NAME})."}


def shutdown_phoenix() -> None:
    """Flush whatever the batch processor is still holding. Never raises."""
    global _phoenix_provider
    provider, _phoenix_provider = _phoenix_provider, None
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception as exc:  # noqa: BLE001
        log.warning("observability: Phoenix did not shut down cleanly: %s", exc)
