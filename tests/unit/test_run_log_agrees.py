"""The run log has to agree with what the run actually did.

Two bugs live here, opposite in direction and one day apart.

Until 2026-08-31 `_develop_one` closed every run as `completed`, including the
ones whose idea had ended `failed`: the run log, which is the first place a
person looks, answered with the opposite of what happened. The repair made
`_generate_one_detail` return whether it wrote, and the caller read it.

The repair then shipped with a bare `return` on the success path of a function
annotated `-> bool`. `None` is falsy, so it inverted the same lie: eight ideas
developed with five variants each, all stored, each recorded as a FAILED run.
Ruff's `RET502` now refuses that shape repository-wide, which catches the typo;
this test catches the meaning, which is that the caller can trust the answer.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from uuid import uuid4

from content_studio.harness import generator as G
from content_studio.harness.generation import (
    HOOK_TYPES,
    GenerationBatchRequest,
    IdeaDetails,
    IdeaTitle,
)


def details(ordinal: int, title: str) -> IdeaDetails:
    return IdeaDetails(
        idea_ordinal=ordinal,
        title=title,
        variants=[
            {
                "hook_type": hook,
                "hook": f"hook {hook}",
                "script": "script",
                "caption": "caption",
                "hashtags": ["#unu", "#doi", "#trei"],
                "cta": "scrie-mi",
                "source": "Memorie",
                "format_details": {
                    "content_blocks": ["unu", "doi"],
                    "visual_direction": "cadru fix",
                    "duration_or_count": "30s",
                },
            }
            for hook in HOOK_TYPES
        ],
    )


class Drafts:
    """Only the three calls the detail path makes."""

    def __init__(self) -> None:
        self.started: list[int] = []
        self.completed: list[str] = []
        self.failed: list[tuple[int, str, bool]] = []

    async def start_idea(self, batch_id, ordinal):
        self.started.append(ordinal)

    async def complete_idea(self, batch_id, value):
        self.completed.append(value.title)

    async def fail_idea(self, batch_id, ordinal, error, retryable):
        self.failed.append((ordinal, error, retryable))


def run_detail(answer, *, title: str = "Cand spui da si regreti") -> tuple[bool, Drafts]:
    coord = G.GenerationCoordinator.__new__(G.GenerationCoordinator)
    coord._conversations = None

    async def fake_run_agent(agent, prompt, output_type, label, group):
        if isinstance(answer, BaseException):
            raise answer
        return answer

    coord._run_agent = fake_run_agent
    drafts = Drafts()
    written = asyncio.run(
        coord._generate_one_detail(
            uuid4(),
            GenerationBatchRequest(format="Reel", pillar="Educație", source="Memorie"),
            "profile",
            IdeaTitle(ordinal=3, title=title, angle="Unghi scurt pentru test"),
            SimpleNamespace(),
            drafts,
        )
    )
    return written, drafts


class TheAnswerIsUsable(unittest.TestCase):
    def test_a_stored_idea_reports_success(self) -> None:
        """The bare-return bug: this was `None`, and `None` is falsy."""
        written, drafts = run_detail(details(3, "Cand spui da si regreti"))
        self.assertIs(written, True)
        self.assertEqual(drafts.completed, ["Cand spui da si regreti"])
        self.assertEqual(drafts.failed, [])

    def test_a_run_that_wrote_nothing_reports_failure(self) -> None:
        written, drafts = run_detail(G.MissingConfig("no key"))
        self.assertIs(written, False)
        self.assertEqual(drafts.completed, [])
        self.assertTrue(drafts.failed)

    def test_the_answer_is_a_real_boolean_either_way(self) -> None:
        """`written` decides between `close_run` and `failed`; None decides wrong."""
        for answer in (details(3, "Cand spui da si regreti"), ValueError("nope")):
            with self.subTest(answer=type(answer).__name__):
                written, _ = run_detail(answer)
                self.assertIsInstance(written, bool)

    def test_the_title_the_model_re_typed_still_counts_as_written(self) -> None:
        """`same_title` folds the punctuation; the run must not be called failed."""
        written, drafts = run_detail(
            details(3, '"Am prea multe pe lista"'),
            title="„Am prea multe pe lista”",
        )
        self.assertIs(written, True)
        # And the stored spelling wins over the model's re-typing.
        self.assertEqual(drafts.completed, ["„Am prea multe pe lista”"])


if __name__ == "__main__":
    unittest.main()
