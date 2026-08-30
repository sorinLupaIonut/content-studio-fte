"""The search rule is one rule, written twice — these tests keep the copies equal.

Decided on 2026-08-30: both phases search the same way, so the "Cum cauti" block
is identical prose in both `SKILL.md` bodies. It lives in the body rather than in
a shared `references/` file because `propune-postari` has no references folder
at all, and that is why phase 1 is cheap: it opens nothing. The cost of that
choice is two copies, and the cost of two copies is drift — which is what this
file exists to make impossible.

The second test is the other half of the same decision: the rule belongs to the
method, so the tools must not carry one. A tool docstring says what a field is,
never when to call the tool or what to do with the answer.
"""

import re
import unittest
from pathlib import Path

from content_studio.config import SKILLS_DIR

HEADING = "### Cum cauți — aceeași regulă la amândouă uneltele"

#: What the rule has to keep saying. Each phase adds its own framing after the
#: block; these are the parts that must not diverge between them.
MUST_MENTION = ("formatul", "pilonul", "focusul", "Andreea", "description_en", "`source`")


def rule_of(skill: str) -> str:
    """The shared block, from its heading to the phase-specific paragraph."""
    body = (Path(SKILLS_DIR) / skill / "SKILL.md").read_text(encoding="utf-8")
    start = body.index(HEADING)
    end = body.index("\n**La faza asta", start)
    return body[start:end].strip()


class SearchRuleIsOneRule(unittest.TestCase):
    def test_both_skills_carry_the_identical_block(self):
        proposal = rule_of("propune-postari")
        detail = rule_of("dezvolta-postarea")
        self.assertEqual(proposal, detail, "the two copies of the search rule have drifted")

    def test_the_rule_names_what_a_search_must_account_for(self):
        rule = rule_of("propune-postari")
        for token in MUST_MENTION:
            self.assertIn(token, rule, f"the search rule stopped mentioning {token}")

    def test_each_phase_states_its_own_context(self):
        """Same rule, different job: ten distinct titles vs one idea in five."""
        proposal = (Path(SKILLS_DIR) / "propune-postari" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        detail = (Path(SKILLS_DIR) / "dezvolta-postarea" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("**La faza asta cauți o singură dată", proposal)
        self.assertIn("**La faza asta cauți pentru unghiul unei singure idei", detail)


class ToolsCarryNoMethod(unittest.TestCase):
    """The docstrings describe the data; the skill decides what to do with it."""

    #: Phrases that are method, not contract. Each one shipped in a docstring
    #: before 2026-08-30 and now lives in the skill instead.
    METHOD_PHRASES = ("Folosește-o DOAR", "Nu prelua", "0,45", "0,35", "regula 8")

    def docstring(self, name: str) -> str:
        source = Path("src/content_studio/mcp_server/server.py").read_text(encoding="utf-8")
        match = re.search(
            rf"async def {name}\(.*?\n\) -> .*?:\n    \"\"\"(.*?)\"\"\"",
            source,
            re.DOTALL,
        )
        assert match is not None, f"{name} not found"
        return match.group(1)

    def test_no_method_in_the_search_docstrings(self):
        for tool in ("search_books", "search_web"):
            doc = self.docstring(tool)
            for phrase in self.METHOD_PHRASES:
                self.assertNotIn(
                    phrase, doc, f"{tool}'s docstring carries method: {phrase!r}"
                )


if __name__ == "__main__":
    unittest.main()
