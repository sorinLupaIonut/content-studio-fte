"""A profile read from the harness has to name whose profile it is.

The profile is an MCP *resource*, not a tool. `client_of(ctx)` scopes every tool
off the connection header, which is why no tool takes a client argument - but
`profile_uri(slug)` carries its subject in the URI, so a resource read ignores
that header and a call naming no slug silently gets `CLIENT_SLUG`.

All seven harness call sites named no slug, from 2026-08-21 to 2026-08-31. Every
account read - and every agent wrote from - Viorela's profile. It could not have
raised: the read succeeded and returned a real profile. And it could not have
been seen: the four clients were seeded from one file and held byte-identical
profiles, 28,639 characters each, so the wrong answer and the right one were the
same text. Translating one of them into English made the two differ, and the bug
surfaced within minutes.

The AST walk below is the check. Reading the diff is not: the failure is an
argument that is ABSENT, and absence is what review misses.
"""

from __future__ import annotations

import ast
import unittest
from contextvars import copy_context
from pathlib import Path

from content_studio.config import CLIENT_SLUG
from content_studio.harness.accounts import CURRENT_CLIENT, current_client

#: Only the harness. `evals/` and `tests/checks/` run as the owner from a
#: terminal, with nothing bound, and `CLIENT_SLUG` is the right answer there.
HARNESS = Path(__file__).resolve().parents[2] / "src" / "content_studio" / "harness"


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


class EveryHarnessReadNamesItsClient(unittest.TestCase):
    def test_no_call_site_relies_on_the_default(self) -> None:
        unscoped: list[str] = []
        seen = 0
        for path in sorted(HARNESS.glob("*.py")):
            tree = ast.parse(path.read_text("utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or _called_name(node) != "read_profile":
                    continue
                seen += 1
                named = len(node.args) >= 2 or any(
                    kw.arg == "client_slug" for kw in node.keywords
                )
                if not named:
                    unscoped.append(f"{path.name}:{node.lineno}")
        self.assertTrue(seen, "no read_profile call found - has it been renamed?")
        self.assertEqual(
            unscoped,
            [],
            "these read the profile of whoever CLIENT_SLUG names, not the "
            f"signed-in account: {unscoped}",
        )


class TheHelper(unittest.TestCase):
    def test_it_answers_the_bound_client(self) -> None:
        def bound() -> str:
            CURRENT_CLIENT.set("dan-preda")
            return current_client()

        self.assertEqual(copy_context().run(bound), "dan-preda")

    def test_nothing_bound_still_answers_the_default(self) -> None:
        """The CLI, a health probe and every existing test bind nothing, and
        they read the configured client exactly as they always did."""
        self.assertEqual(copy_context().run(current_client), CLIENT_SLUG)

    def test_a_spawned_task_inherits_the_binding(self) -> None:
        """Generation runs in a task started from the request, and the whole
        design rests on the value following it there."""
        import asyncio

        async def outer() -> str:
            CURRENT_CLIENT.set("elena-rusu")
            return await asyncio.create_task(inner())

        async def inner() -> str:
            return current_client()

        self.assertEqual(copy_context().run(asyncio.run, outer()), "elena-rusu")


if __name__ == "__main__":
    unittest.main()
