"""Free tests for the live errand log a generation run publishes.

A generation run is silent until it lands — the conversation is witnessed
afterwards — and this is what fills the ninety seconds in between. The rules
worth holding: a reader gets each line exactly once, a finished errand can be
paired with the one it finished, and the log cannot grow without bound because
nothing ever deletes it explicitly.
"""

import unittest

from content_studio.harness.generation import StreamEvent, encode_sse
from content_studio.harness.generator import ACTIVITY_CODES, ActivityLog


class Lines(unittest.TestCase):
    def test_a_reader_gets_each_line_once(self) -> None:
        log = ActivityLog()
        log.started("search_books")
        first = log.since(0)
        self.assertEqual(len(first), 1)
        # Read again from where it got to: nothing new.
        self.assertEqual(log.since(log.sequence), [])

        log.started("search_web")
        self.assertEqual(len(log.since(first[-1]["seq"])), 1)

    def test_done_is_a_new_line_not_a_changed_one(self) -> None:
        """A reader asks for everything after a number, so a mutated line would
        never be sent again. `done` carries `of` instead."""
        log = ActivityLog()
        started = log.started("search_books")
        drained = log.sequence
        log.finished(started, empty=True)

        fresh = log.since(drained)
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]["state"], "done")
        self.assertEqual(fresh[0]["of"], started)
        self.assertTrue(fresh[0]["empty"])

    def test_the_tool_name_becomes_a_code(self) -> None:
        """The page never shows `exec_command`; `Copy.cs` chooses the words."""
        log = ActivityLog()
        log.started("search_books")
        log.started("exec_command")
        log.started("something_new")
        codes = [line["code"] for line in log.since(0) if line["state"] == "running"]
        self.assertEqual(codes, ["books", "method", "tool"])

    def test_every_named_tool_has_a_code(self) -> None:
        for tool in ("search_books", "search_web", "exec_command"):
            self.assertIn(tool, ACTIVITY_CODES)

    def test_it_cannot_grow_for_ever(self) -> None:
        """Nothing deletes a line, so the log has to forget its own oldest."""
        log = ActivityLog(keep=4)
        for _ in range(20):
            log.started("search_web")
        self.assertEqual(len(log.since(0)), 4)
        # And the sequence keeps counting, so a reader is never sent a line twice
        # just because the front fell off.
        self.assertEqual(log.sequence, 20)


class ItReachesTheBrowser(unittest.TestCase):
    """The log is only half of it; the event has to be constructible.

    It was not, on the first live run: `StreamEventType` is a closed `Literal`
    and `activity` was not in it, so the stream raised on the first errand and
    the whole SSE died - taking the batch's status events with it. Nothing in
    the unit tests touched the two halves together, and the browser found it in
    a minute. This is that minute, made free.
    """

    def test_the_event_type_exists(self) -> None:
        log = ActivityLog()
        log.started("search_books")
        line = log.since(0)[0]
        event = StreamEvent(sequence=1, event="activity", payload=line)
        self.assertEqual(event.event, "activity")

    def test_it_encodes_with_the_payload_the_drawer_reads(self) -> None:
        log = ActivityLog()
        started = log.started("search_web")
        log.finished(started, empty=False)
        for line in log.since(0):
            encoded = encode_sse(StreamEvent(sequence=1, event="activity", payload=line))
            self.assertIn("event: activity", encoded)
            # The drawer switches on `state` and pairs `done` by `of`.
            self.assertIn('"state"', encoded)


if __name__ == "__main__":
    unittest.main()
