"""Three surfaces, one id.

The deployment course names four observability surfaces and ties them together
with a shared `run_id`. Three of the four apply to this studio:

* **OpenTelemetry spans**, exported to Application Insights - where a request
  went, how long each hop took, which one threw.
* **Every log line**, which carries the same `run_id` whether it is printed to
  the container's stdout or shipped to Application Insights. That is a log
  record factory, not a handler filter, and `install_run_id_factory` explains
  why the difference decides whether the id survives the export.
* **The audit trail in Neon**, keyed by that same `run_id`, which `replay.py`
  already reconstructs turn by turn.

The fourth surface, Phoenix, is deliberately not wired. It is another account,
another key and another bill, and what it would add - a searchable record of the
agent's own reasoning - is already in `public.traces`, durable and replayable.
Should that change, it is one exporter, not a redesign.

Sampling is 100%, also deliberately. The course samples roughly a tenth of the
successful runs because it assumes production traffic. This studio has three
accounts. Dropping nine runs in ten would throw away the only evidence of a
fault that happens once a week, and would save nothing worth saving.

Everything here degrades to silence. With no connection string the harness runs
exactly as it did before, logging to stdout - the same rule the sandbox and the
database already follow.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from content_studio.config import APPLICATIONINSIGHTS_CONNECTION_STRING

# The thread that ties the three surfaces together. A ContextVar rather than a
# parameter because a run crosses about twenty call sites and several spawned
# tasks; each task inherits a copy at creation, which is exactly the scope of a
# run.
RUN_ID: ContextVar[str] = ContextVar("run_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)-7s [run=%(run_id)s] %(name)s: %(message)s"

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

    if not APPLICATIONINSIGHTS_CONNECTION_STRING:
        return {
            "ok": False,
            "detail": (
                "APPLICATIONINSIGHTS_CONNECTION_STRING lipsește; "
                "urmele rămân doar în stdout și în Neon."
            ),
        }
    if _configured:
        return {"ok": True, "detail": "Application Insights primește urmele."}

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError as exc:  # pragma: no cover - a partial install
        return {"ok": False, "detail": f"Pachetele de telemetrie lipsesc ({exc.name})."}

    configure_azure_monitor(
        connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING,
        logger_name="content_studio",
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
    return {"ok": True, "detail": "Application Insights primește urmele."}
