"""A failure explains itself, or admits it cannot.

The bug this holds. `run_like_production.py` printed one hint under every
exception - "is `uv run content-studio-server` running?" - and on 2026-08-28
E2B blocked the team for reaching its billing limit. The MCP server was running,
had answered two requests, and both 200s were on screen directly above the hint
that said to check it. A wrong hint is read as a diagnosis, so it costs more
than no hint: it decides where the next twenty minutes are spent.

Two properties matter and both are tested: the recognised failures name the
thing that has to be fixed, and an unrecognised one says so instead of guessing.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from agents.exceptions import ModelBehaviorError

CHECK = (
    Path(__file__).resolve().parents[2] / "tests" / "checks" / "paid" / "run_like_production.py"
)


def _load():
    """Import the check script by path - `tests/checks` is not a package."""
    spec = importlib.util.spec_from_file_location("run_like_production", CHECK)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SandboxException(Exception):
    """Stands in for E2B's own, which needs the client to construct."""


class DiagnosisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.diagnose = _load().diagnose

    def test_the_billing_block_is_named_as_billing_and_not_as_the_mcp_server(self) -> None:
        lines = self.diagnose(SandboxException("403: team is blocked: Billing limit reached"))
        joined = " ".join(lines)
        self.assertIn("e2b.dev", joined)
        self.assertIn("facturare", joined)
        # The regression itself: the hint that used to be printed here.
        self.assertNotIn("content-studio-server", joined)

    def test_a_refused_connection_still_points_at_the_mcp_server(self) -> None:
        lines = self.diagnose(ConnectionRefusedError("connect to 127.0.0.1:8765 refused"))
        self.assertIn("8765", " ".join(lines))

    def test_a_broken_contract_says_production_would_have_retried(self) -> None:
        lines = self.diagnose(ModelBehaviorError("Invalid JSON when parsing output"))
        self.assertIn("reincearca", " ".join(lines))

    def test_an_unknown_failure_admits_it_rather_than_guessing(self) -> None:
        lines = self.diagnose(ValueError("something nobody has seen before"))
        self.assertEqual(len(lines), 1)
        self.assertIn("nerecunoscuta", lines[0])

    def test_every_diagnosis_is_reachable_by_its_own_needles(self) -> None:
        """A needle that matches nothing is a diagnosis that never prints."""
        module = _load()
        for needles, text in module.DIAGNOSES:
            for needle in needles:
                self.assertIn(text, module.diagnose(ValueError(needle.upper())))


if __name__ == "__main__":
    unittest.main()
