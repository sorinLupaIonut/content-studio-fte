"""Free tests for the rule that decides when a batch is finished.

The bug these close: one idea that exhausted its retry used to set the whole
batch to 'failed', and the promotion rule demanded ten ready ideas out of ten.
Together that made eight good ideas unreachable behind the two that failed.
"""

import asyncio
import unittest
from uuid import uuid4

from content_studio.mcp_server.generation_store import (
    REFRESH_BATCH_STATUS_SQL,
    fail_idea,
)


class RecordingConnection:
    """The smallest stub that lets `fail_idea` run and be observed."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.fetchvals: list[str] = []

    async def fetchrow(self, sql: str, *args):
        self.executed.append(sql)
        return {"id": uuid4(), "status": "failed", "retry_count": 2}

    async def fetchval(self, sql: str, *args):
        self.fetchvals.append(sql)
        return "ready"

    async def execute(self, sql: str, *args) -> None:
        self.executed.append(sql)


class FailIdeaTests(unittest.TestCase):
    def _fail(self, *, retryable: bool) -> RecordingConnection:
        conn = RecordingConnection()
        asyncio.run(fail_idea(conn, uuid4(), 4, "invalid json", retryable=retryable))
        return conn

    def test_a_permanently_failed_idea_does_not_hard_fail_the_batch(self) -> None:
        conn = self._fail(retryable=False)
        for sql in conn.executed:
            self.assertNotIn(
                "generation_batches SET status = 'failed'",
                " ".join(sql.split()),
                "one idea giving up must not decide the whole batch",
            )

    def test_failing_an_idea_re_evaluates_the_batch(self) -> None:
        conn = self._fail(retryable=False)
        self.assertIn(REFRESH_BATCH_STATUS_SQL, conn.fetchvals)

    def test_a_retryable_failure_also_re_evaluates_the_batch(self) -> None:
        conn = self._fail(retryable=True)
        self.assertIn(REFRESH_BATCH_STATUS_SQL, conn.fetchvals)


class RefreshRuleTests(unittest.TestCase):
    """The promotion rule is SQL, so assert the shape of the decision it makes."""

    def setUp(self) -> None:
        self.sql = " ".join(REFRESH_BATCH_STATUS_SQL.split())

    def test_a_batch_is_generating_only_while_an_idea_is_actually_being_written(
        self,
    ) -> None:
        # Narrowed on 2026-08-24, when details became something she asks for.
        # The old rule - anything not ready or failed - counted the nine ideas
        # she has not opened yet, so every batch stayed 'generating' for ever,
        # under a spinner and a cancel button, with nothing running.
        self.assertIn("i.status IN ('generating', 'retrying') ) THEN 'generating'", self.sql)

    def test_undeveloped_ideas_rest_at_titles_ready(self) -> None:
        self.assertIn("i.status = 'waiting' ) THEN 'titles_ready'", self.sql)
        # After 'ready', so one developed idea still reads as developed rather
        # than dragging the batch back to "titles only".
        self.assertTrue(
            self.sql.index("THEN 'ready'") < self.sql.index("THEN 'titles_ready'")
        )

    def test_one_ready_idea_is_enough_to_call_the_batch_ready(self) -> None:
        self.assertIn("i.status = 'ready' ) THEN 'ready'", self.sql)

    def test_failed_is_the_last_resort(self) -> None:
        self.assertTrue(self.sql.index("THEN 'ready'") < self.sql.index("ELSE 'failed'"))

    def test_a_cancelled_batch_still_wins_over_everything(self) -> None:
        self.assertTrue(
            self.sql.index("cancel_requested THEN 'cancelled'")
            < self.sql.index("THEN 'generating'")
        )


if __name__ == "__main__":
    unittest.main()
