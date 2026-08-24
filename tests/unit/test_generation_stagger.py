"""The staggered fan-out, and the deadlock it must never cause.

Slot zero writes the prompt-cache prefix and the other four read it. That makes
four coroutines wait on one event, which is exactly the shape that strands a
batch when the leader dies. These tests are about the release, not the saving.
"""

from __future__ import annotations

import asyncio
import unittest
from contextlib import suppress
from unittest.mock import patch
from uuid import uuid4

from content_studio.harness.generation import GenerationBatchRequest, IdeaTitle, IdeaTitles
from content_studio.harness.generator import GenerationCoordinator


class _Agent:
    """Enough of an Agent to be cloned. The fan-out never looks inside."""

    def clone(self, **_kwargs):
        return _Agent()


class _Drafts:
    async def start_idea(self, *_a, **_k):
        return None

    async def complete_idea(self, *_a, **_k):
        return None

    async def fail_idea(self, *_a, **_k):
        return None


def _titles(count: int) -> IdeaTitles:
    return IdeaTitles(
        ideas=[
            IdeaTitle(ordinal=i, title=f"Ideea {i}", angle="unghi")
            for i in range(1, count + 1)
        ]
    )


def _request() -> GenerationBatchRequest:
    return GenerationBatchRequest(
        pillar="Educație", source="Memorie", format="Reel", focus=None
    )


class StaggerTests(unittest.TestCase):
    def _run(self, *, warms: bool, raises: bool) -> list[int]:
        """Drive _generate_details with fake slots; return which ideas started.

        The leader's first call is held open until the assertion has been made,
        so a slot that failed to wait would visibly overtake it.
        """
        coordinator = GenerationCoordinator(lambda _s: None, lambda _s: None)
        started: list[int] = []
        release = asyncio.Event()
        leader_done = asyncio.Event()

        async def fake_detail(_b, _r, _s, idea, _a, _c, _sb, _d, _l, hooks=None):
            started.append(idea.ordinal)
            if hooks is None:
                return
            if raises:
                raise RuntimeError("leader's first idea failed")
            if warms:
                await hooks.on_llm_end(None, None, None)
            await release.wait()
            leader_done.set()

        async def fake_slot(agent):
            return agent.clone(), object(), _Sandbox()

        async def drive() -> list[int]:
            task = asyncio.create_task(
                coordinator._generate_details(
                    uuid4(), _request(), {}, _titles(10), _Agent(), _Drafts()
                )
            )
            await asyncio.sleep(0.05)  # ample for five slots to fan out
            observed = list(started)
            release.set()
            # The batch may end in the exception the fake raised; what is being
            # asserted is what happened to the OTHER slots before it did.
            with suppress(RuntimeError):
                await task
            return observed

        with (
            patch.object(coordinator, "_generate_one_detail", fake_detail),
            patch.object(GenerationCoordinator, "_create_slot", staticmethod(fake_slot)),
        ):
            return asyncio.run(drive())

    def test_nobody_starts_before_the_leader_has_written_the_prefix(self) -> None:
        # The leader is still waiting for its first response, so the other four
        # slots must be parked. Before the stagger, all five started at once.
        self.assertEqual(self._run(warms=False, raises=False), [1])

    def test_the_first_response_releases_the_rest(self) -> None:
        # on_llm_end fires the moment the prefix exists - not when the idea is
        # finished. The other slots go then, not fifteen seconds later.
        self.assertGreater(len(self._run(warms=True, raises=False)), 1)

    def test_a_failed_leader_releases_the_others_instead_of_stranding_them(self) -> None:
        # The whole risk of the change in one assertion: the event is set in a
        # `finally`, so a leader that dies on its first idea does not take the
        # batch with it.
        self.assertGreater(len(self._run(warms=False, raises=True)), 1)


class _Sandbox:
    async def aclose(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
