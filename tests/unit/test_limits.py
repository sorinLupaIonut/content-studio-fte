"""The rate limiter, and the paths it is allowed to touch."""

import unittest

from content_studio.harness.limits import RateLimiter, is_limited, key_for
from content_studio.observability import RUN_ID, install_run_id_factory


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_the_limit(self):
        limiter = RateLimiter(per_minute=3)
        for i in range(3):
            self.assertIsNone(limiter.retry_after("a", now=100.0 + i))

    def test_refuses_past_the_limit(self):
        limiter = RateLimiter(per_minute=2)
        limiter.retry_after("a", now=100.0)
        limiter.retry_after("a", now=101.0)
        self.assertIsNotNone(limiter.retry_after("a", now=102.0))

    def test_retry_after_is_when_the_oldest_hit_expires(self):
        limiter = RateLimiter(per_minute=1)
        limiter.retry_after("a", now=100.0)
        # The one hit leaves the window at 160; asked at 130, that is 30 away.
        self.assertEqual(limiter.retry_after("a", now=130.0), 30)

    def test_retry_after_is_never_zero(self):
        """A client that obeys a 0 would come back inside the same window."""
        limiter = RateLimiter(per_minute=1)
        limiter.retry_after("a", now=100.0)
        self.assertGreaterEqual(limiter.retry_after("a", now=159.9), 1)

    def test_the_window_slides(self):
        limiter = RateLimiter(per_minute=2)
        limiter.retry_after("a", now=100.0)
        limiter.retry_after("a", now=101.0)
        self.assertIsNotNone(limiter.retry_after("a", now=150.0))
        # 100.0 has now left the window, so one slot is free again.
        self.assertIsNone(limiter.retry_after("a", now=161.0))

    def test_keys_do_not_share_an_allowance(self):
        limiter = RateLimiter(per_minute=1)
        limiter.retry_after("a", now=100.0)
        self.assertIsNone(limiter.retry_after("b", now=100.0))

    def test_zero_turns_it_off(self):
        limiter = RateLimiter(per_minute=0)
        self.assertFalse(limiter.enabled)
        for i in range(50):
            self.assertIsNone(limiter.retry_after("a", now=100.0 + i))


class LimitedPathTests(unittest.TestCase):
    def test_the_api_is_limited(self):
        self.assertTrue(is_limited("/api/library"))
        self.assertTrue(is_limited("/runs"))
        self.assertTrue(is_limited("/sessions/abc/pending"))

    def test_the_blazor_application_is_not(self):
        """A first load is several hundred files; counted, it would trip."""
        for path in (
            "/",
            "/_framework/blazor.webassembly.js",
            "/_framework/System.Text.Json.wasm",
            "/css/app.css",
            "/health",
        ):
            self.assertFalse(is_limited(path), path)

    def test_event_streams_are_exempt(self):
        """One long connection, not many requests."""
        self.assertFalse(is_limited("/api/runs/abc/events"))
        self.assertFalse(is_limited("/api/generation-batches/abc/events"))


class KeyTests(unittest.TestCase):
    def test_the_principal_wins(self):
        key = key_for({"x-ms-client-principal-id": "1234"}, "10.0.0.1")
        self.assertEqual(key, "principal:1234")

    def test_falls_back_to_the_peer(self):
        self.assertEqual(key_for({}, "10.0.0.1"), "peer:10.0.0.1")

    def test_an_unknown_peer_still_has_a_key(self):
        self.assertEqual(key_for({}, None), "peer:unknown")


class RunIdOnEveryRecordTests(unittest.TestCase):
    """The id has to be on the record itself, not added by one handler's filter.

    A filter is what this used to be, and it left Application Insights without
    the id: the exporter's handler is installed after `configure_logging` and
    runs before the stdout handler that carried the filter.
    """

    def setUp(self):
        import logging

        install_run_id_factory()
        self.make = logging.getLogRecordFactory()

    def _record(self):
        import logging

        return self.make("t", logging.INFO, "f", 1, "m", None, None)

    def test_the_record_is_born_with_the_current_run(self):
        token = RUN_ID.set("run-42")
        try:
            self.assertEqual(self._record().run_id, "run-42")
        finally:
            RUN_ID.reset(token)

    def test_outside_a_run_the_field_still_exists(self):
        """The format string names it, so a missing field would raise on log."""
        self.assertEqual(self._record().run_id, "-")

    def test_installing_twice_does_not_nest_the_factory(self):
        import logging

        install_run_id_factory()
        first = logging.getLogRecordFactory()
        install_run_id_factory()
        self.assertIs(logging.getLogRecordFactory(), first)

    def test_an_explicit_run_id_is_not_overwritten(self):
        import logging

        record = self.make("t", logging.INFO, "f", 1, "m", None, None)
        record.run_id = "given"
        self.assertEqual(
            logging.getLogRecordFactory()("t", logging.INFO, "f", 1, "m", None, None).run_id,
            RUN_ID.get(),
        )
        self.assertEqual(record.run_id, "given")


class RateLimitMiddlewareTests(unittest.TestCase):
    """The limiter as the running app actually applies it."""

    def _app(self, per_minute: int):
        from unittest.mock import patch as mock_patch

        from fastapi.testclient import TestClient

        from content_studio.harness.main import create_app
        from tests.unit.test_harness import TEST_AUTH, FakeService

        with mock_patch(
            "content_studio.harness.limits.RATE_LIMIT_PER_MINUTE", per_minute
        ):
            return TestClient(create_app(FakeService, identity_resolver=TEST_AUTH))

    def test_a_flood_gets_429_with_retry_after(self):
        with self._app(per_minute=3) as client:
            for _ in range(3):
                self.assertNotEqual(client.get("/api/library").status_code, 429)
            refused = client.get("/api/library")

        self.assertEqual(refused.status_code, 429)
        self.assertEqual(refused.json()["code"], "rate_limited")
        self.assertGreaterEqual(int(refused.headers["Retry-After"]), 1)

    def test_the_application_shell_is_never_limited(self):
        """A first load is hundreds of files; the page must still appear."""
        with self._app(per_minute=2) as client:
            for _ in range(20):
                self.assertNotEqual(client.get("/health").status_code, 429)


class ObservabilityDegradesTests(unittest.TestCase):
    """No key is a supported state, not a misconfiguration."""

    def test_without_a_connection_string_it_reports_off_and_does_not_raise(self):
        from unittest.mock import patch as mock_patch

        import content_studio.observability as obs

        # configure_logging mutates the root logger, which would follow the rest
        # of the suite around; the behaviour under test is the return value.
        with mock_patch.object(obs, "APPLICATIONINSIGHTS_CONNECTION_STRING", ""), \
             mock_patch.object(obs, "configure_logging"):
            status = obs.configure(app=None)

        self.assertFalse(status["ok"])
        self.assertIn("APPLICATIONINSIGHTS_CONNECTION_STRING", status["detail"])

    def test_bind_run_works_with_no_span_in_context(self):
        """The CLI has no OpenTelemetry context and must not care."""
        from content_studio.observability import RUN_ID, bind_run

        token = RUN_ID.set("-")
        try:
            bind_run("cli-run")
            self.assertEqual(RUN_ID.get(), "cli-run")
        finally:
            RUN_ID.reset(token)


class CodedRefusalTests(unittest.TestCase):
    """Refusals a bilingual page has to word itself carry a code."""

    def test_the_app_turns_a_coded_error_into_detail_plus_code(self):
        """The handler, not a probe route: the UI mount owns every unmatched path."""
        import asyncio
        import json

        from content_studio.harness.errors import CodedError
        from content_studio.harness.main import create_app
        from tests.unit.test_harness import TEST_AUTH, FakeService

        app = create_app(FakeService, identity_resolver=TEST_AUTH)
        handler = app.exception_handlers[CodedError]
        response = asyncio.run(
            handler(None, CodedError(418, "kettle", "i_am_a_teapot"))
        )

        self.assertEqual(response.status_code, 418)
        self.assertEqual(
            json.loads(response.body),
            {"detail": "kettle", "code": "i_am_a_teapot"},
        )

    def test_the_english_detail_carries_no_romanian(self):
        """The client's safety net keys on diacritics; the server must not need it."""
        from content_studio.harness.errors import CodedError

        error = CodedError(404, "saved post not found", "post_not_found")
        self.assertFalse(
            any(c in "ăâîșțĂÂÎȘȚ" for c in error.detail), error.detail
        )


if __name__ == "__main__":
    unittest.main()
