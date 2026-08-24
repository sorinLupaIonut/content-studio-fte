"""Surface 2's one requirement: every span carries the run it belongs to.

`bind_run` stamps the span that is current when the id is minted. That covers
chat, where the id is born inside the request. It does not cover generation:
`/api/generation-batches/{id}/ideas/{n}/details` answers 202 and the work runs
in a task afterwards, so the server span has already ended and setting an
attribute on it does nothing. Measured before the fix: on that path no span
reached Application Insights with `studio.run_id` at all.
"""

from __future__ import annotations

import unittest

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from content_studio.observability import RUN_ID, _make_run_id_stamp, bind_run


class _Collect(SpanExporter):
    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):  # noqa: ANN001, ANN201
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


class RunIdReachesEverySpan(unittest.TestCase):
    def setUp(self) -> None:
        self.collected = _Collect()
        self.provider = TracerProvider()
        self.provider.add_span_processor(_make_run_id_stamp())
        self.provider.add_span_processor(SimpleSpanProcessor(self.collected))
        self.tracer = self.provider.get_tracer(__name__)
        self._token = RUN_ID.set("-")

    def tearDown(self) -> None:
        RUN_ID.reset(self._token)

    def _stamped(self) -> dict[str, str]:
        return {
            span.name: (span.attributes or {}).get("studio.run_id", "")
            for span in self.collected.spans
        }

    def test_a_span_opened_after_the_id_exists_carries_it(self) -> None:
        """The generation shape: nothing is current when the run begins."""
        bind_run("run-detail")
        with self.tracer.start_as_current_span("model call"):
            pass
        self.assertEqual(self._stamped()["model call"], "run-detail")

    def test_children_carry_it_too_not_only_the_parent(self) -> None:
        """A query you find by run_id beats one you find by reading a trace."""
        with self.tracer.start_as_current_span("POST /api/chat"):
            bind_run("run-chat")
            with self.tracer.start_as_current_span("asyncpg.query"):
                pass
        stamped = self._stamped()
        self.assertEqual(stamped["POST /api/chat"], "run-chat")
        self.assertEqual(stamped["asyncpg.query"], "run-chat")

    def test_no_run_bound_is_not_an_error(self) -> None:
        """Telemetry never breaks a request — the default is a dash."""
        with self.tracer.start_as_current_span("startup"):
            pass
        self.assertEqual(self._stamped()["startup"], "-")

    def test_the_stamp_survives_a_span_that_raises(self) -> None:
        bind_run("run-boom")
        with self.assertRaises(ValueError):
            with self.tracer.start_as_current_span("failing"):
                raise ValueError("boom")
        self.assertEqual(self._stamped()["failing"], "run-boom")


class WhereTheStampIsRegistered(unittest.TestCase):
    def test_the_global_provider_gets_it_not_only_phoenix(self) -> None:
        """It was on Phoenix's provider alone, which is the one Application
        Insights does not read."""
        import inspect

        from content_studio import observability

        source = inspect.getsource(observability.configure)
        self.assertIn("add_span_processor(_make_run_id_stamp())", source)


if __name__ == "__main__":
    unittest.main()


class TelemetryNeverGatesARequest(unittest.TestCase):
    """A provider that cannot take a processor must not raise.

    Until an SDK provider is installed the global one is a
    `ProxyTracerProvider` with no `add_span_processor`. Registering blind turned
    a missing stamp into a failed startup.
    """

    def test_a_proxy_provider_is_survived(self) -> None:
        from unittest import mock

        from fastapi import FastAPI

        from content_studio import observability as obs

        with (
            mock.patch.object(obs, "APPLICATIONINSIGHTS_CONNECTION_STRING", "x"),
            mock.patch.object(obs, "_configured", False),
            mock.patch.object(obs, "configure_phoenix", return_value={"ok": False}),
            mock.patch(
                "azure.monitor.opentelemetry.configure_azure_monitor",
                lambda **_: None,
            ),
        ):
            result = obs.configure(FastAPI())
        self.assertTrue(result["ok"])
