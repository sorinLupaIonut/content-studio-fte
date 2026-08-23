"""The agent's own spans, collected and keyed by the run that produced them."""

from __future__ import annotations

import unittest
import unittest.mock

from content_studio.observability import RUN_ID, RunTraceProcessor


class FakeTrace:
    def __init__(self, trace_id: str = "trace-1") -> None:
        self.trace_id = trace_id

    def export(self) -> dict:
        return {"id": self.trace_id, "workflow_name": "Studio"}


class FakeSpan:
    def __init__(self, span_id: str, trace_id: str = "trace-1", broken: bool = False) -> None:
        self.span_id = span_id
        self.trace_id = trace_id
        self._broken = broken

    def export(self) -> dict:
        if self._broken:
            raise RuntimeError("this span will not serialise")
        return {"id": self.span_id}


class RunTraceProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handed: list[tuple[str, dict]] = []
        self.processor = RunTraceProcessor(
            lambda run_id, payload: self.handed.append((run_id, payload))
        )

    def run_a_trace(self, spans=("a", "b"), trace_id="trace-1") -> None:
        trace = FakeTrace(trace_id)
        self.processor.on_trace_start(trace)
        for span_id in spans:
            span = FakeSpan(span_id, trace_id)
            self.processor.on_span_start(span)
            self.processor.on_span_end(span)
        self.processor.on_trace_end(trace)

    def test_the_spans_reach_the_sink_under_the_current_run(self) -> None:
        token = RUN_ID.set("run-7")
        try:
            self.run_a_trace()
        finally:
            RUN_ID.reset(token)

        self.assertEqual(len(self.handed), 1)
        run_id, payload = self.handed[0]
        self.assertEqual(run_id, "run-7")
        self.assertEqual(payload["run_id"], "run-7")
        self.assertEqual([s["id"] for s in payload["spans"]], ["a", "b"])
        self.assertEqual(payload["trace"]["workflow_name"], "Studio")

    def test_a_trace_outside_a_run_is_dropped(self) -> None:
        """`traces.run_id` is a foreign key, and "-" is not a run."""
        self.run_a_trace()

        self.assertEqual(self.handed, [])

    def test_two_traces_do_not_borrow_each_others_spans(self) -> None:
        first, second = FakeTrace("t1"), FakeTrace("t2")
        token = RUN_ID.set("run-1")
        try:
            self.processor.on_trace_start(first)
            self.processor.on_span_end(FakeSpan("a", "t1"))
            RUN_ID.set("run-2")
            self.processor.on_trace_start(second)
            self.processor.on_span_end(FakeSpan("b", "t2"))
            self.processor.on_trace_end(second)
            self.processor.on_trace_end(first)
        finally:
            RUN_ID.reset(token)

        by_run = {run_id: payload for run_id, payload in self.handed}
        self.assertEqual([s["id"] for s in by_run["run-2"]["spans"]], ["b"])
        # The id is the one that was current when the trace *started*, which is
        # the run it belongs to - not whatever is current when it ends.
        self.assertEqual([s["id"] for s in by_run["run-1"]["spans"]], ["a"])

    def test_a_span_that_will_not_serialise_is_skipped_not_fatal(self) -> None:
        trace = FakeTrace()
        token = RUN_ID.set("run-9")
        try:
            self.processor.on_trace_start(trace)
            self.processor.on_span_end(FakeSpan("bad", broken=True))
            self.processor.on_span_end(FakeSpan("good"))
            self.processor.on_trace_end(trace)
        finally:
            RUN_ID.reset(token)

        self.assertEqual([s["id"] for s in self.handed[0][1]["spans"]], ["good"])

    def test_a_sink_that_raises_does_not_reach_the_agent(self) -> None:
        """These callbacks run inside the run; telemetry does not get to stop it."""
        processor = RunTraceProcessor(
            lambda run_id, payload: (_ for _ in ()).throw(RuntimeError("neon is down"))
        )
        trace = FakeTrace()
        token = RUN_ID.set("run-9")
        try:
            processor.on_trace_start(trace)
            processor.on_trace_end(trace)  # must not raise
        finally:
            RUN_ID.reset(token)

    def test_nothing_is_kept_after_the_trace_ends(self) -> None:
        token = RUN_ID.set("run-3")
        try:
            self.run_a_trace()
        finally:
            RUN_ID.reset(token)

        self.assertEqual(self.processor._runs, {})
        self.assertEqual(self.processor._spans, {})



class AzureMonitorWiringTests(unittest.TestCase):
    """What `configure` asks Azure Monitor for, and why it must keep asking.

    Both of these were silent defaults that contradicted the module docstring,
    found on 2026-08-23 by reading the live resource rather than the code: spans
    were being dropped by a rate limiter nobody had chosen, and every row
    arrived as `unknown_service`. A default that disagrees with the
    documentation is exactly the thing a test should hold in place.
    """

    def _configure_with_spy(self) -> dict:
        """Run `configure` against a real app with every exporter stubbed out.

        The instrumentors are patched rather than allowed to run: they attach to
        asyncpg and httpx process-wide, and a unit test has no business leaving
        that behind for whatever runs next.
        """
        from fastapi import FastAPI

        import content_studio.observability as obs

        seen: dict = {}
        was_configured = obs._configured
        obs._configured = False
        try:
            with (
                unittest.mock.patch(
                    "azure.monitor.opentelemetry.configure_azure_monitor",
                    side_effect=lambda **kwargs: seen.update(kwargs),
                ),
                unittest.mock.patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor"),
                unittest.mock.patch("opentelemetry.instrumentation.asyncpg.AsyncPGInstrumentor"),
                unittest.mock.patch(
                    "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor"
                ),
                unittest.mock.patch.object(
                    obs, "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test"
                ),
            ):
                obs.configure(FastAPI())
        finally:
            obs._configured = was_configured
        return seen

    def test_every_span_is_kept(self) -> None:
        """Without this the distro installs a 5-spans-per-second rate limiter."""
        self.assertEqual(self._configure_with_spy().get("sampling_ratio"), 1.0)

    def test_the_service_names_itself(self) -> None:
        """Otherwise both container apps report as `unknown_service`."""
        from opentelemetry.sdk.resources import SERVICE_NAME

        from content_studio.observability import SERVICE_HARNESS

        resource = self._configure_with_spy().get("resource")
        self.assertIsNotNone(resource)
        self.assertEqual(resource.attributes.get(SERVICE_NAME), SERVICE_HARNESS)


if __name__ == "__main__":
    unittest.main()
