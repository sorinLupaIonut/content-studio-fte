"""The gate compares what the model typed against what the application asked.

That comparison is the reason a person can trust the confirmation card: the gate
stops an unwanted write, and this stops a write of the WRONG thing reaching the
card at all. It has to be strict.

It also has to be right about absence. A Reel is silent, so its `script` has no
value, and the two ways of writing "no value" - `null` and `""` - are the same
value. On 2026-08-31 they were not: a saved Reel could not be edited from the
page, intermittently, depending on which shape the model echoed back. The user
saw "the agent did not prepare the application's exact request. Try again", and
trying again worked or did not, at random.
"""

import unittest

from content_studio.harness.models import RunResponse, ToolApprovalRequest
from content_studio.harness.service import HarnessService, same_value


def pending(tool: str, arguments: dict) -> RunResponse:
    return RunResponse(
        run_id="r",
        session_id="s",
        status="pending",
        requests=[
            ToolApprovalRequest(call_id="c", tool_name=tool, arguments=arguments)
        ],
    )


class TheTwoEmpties(unittest.TestCase):
    def test_null_and_empty_are_the_same_absence(self) -> None:
        self.assertTrue(same_value(None, ""))
        self.assertTrue(same_value("", None))
        self.assertTrue(same_value(None, None))
        self.assertTrue(same_value("", ""))

    def test_an_absent_value_is_not_a_present_one(self) -> None:
        self.assertFalse(same_value(None, "Scene 1: ..."))
        self.assertFalse(same_value("", "Scene 1: ..."))
        self.assertFalse(same_value("Scene 1: ...", None))

    def test_nothing_else_is_forgiven(self) -> None:
        """No trimming, no case folding: a rephrased word must still be caught."""
        self.assertFalse(same_value("Hook", "hook"))
        self.assertFalse(same_value("Hook ", "Hook"))
        self.assertFalse(same_value("Hook.", "Hook"))


class TheMismatch(unittest.TestCase):
    EXPECTED = {"post_id": "p1", "hook": "A hook", "script": ""}

    def test_a_silent_reel_passes_with_either_empty(self) -> None:
        for script in (None, ""):
            with self.subTest(script=script):
                result = pending(
                    "update_post", {"post_id": "p1", "hook": "A hook", "script": script}
                )
                self.assertIsNone(
                    HarnessService._mismatch(result, "update_post", self.EXPECTED)
                )

    def test_a_rewritten_field_is_still_caught(self) -> None:
        result = pending(
            "update_post", {"post_id": "p1", "hook": "A better hook", "script": ""}
        )
        self.assertEqual(
            HarnessService._mismatch(result, "update_post", self.EXPECTED),
            "the field 'hook' was modified",
        )

    def test_an_invented_script_is_caught(self) -> None:
        """A Reel is silent. A model that writes one has changed her post."""
        result = pending(
            "update_post",
            {"post_id": "p1", "hook": "A hook", "script": "Scene 1: she smiles"},
        )
        self.assertEqual(
            HarnessService._mismatch(result, "update_post", self.EXPECTED),
            "the field 'script' was modified",
        )

    def test_the_wrong_tool_is_caught(self) -> None:
        result = pending("save_post", {"post_id": "p1"})
        self.assertIn(
            "save_post", HarnessService._mismatch(result, "update_post", self.EXPECTED)
        )


class TheContractBehindTheTool(unittest.TestCase):
    """Why `update_post` has to normalise before it validates.

    `SavedPostContent.script` is `str | None` with a `min_length` of 3, and the
    MCP tool's own parameter is a required `str` — so a model that must send
    something sends `""`. That value is neither absent nor three characters
    long, and the tool raised on it every time a silent Reel was edited. The
    model read the error, called the tool again, hit the approval gate again,
    and the page said the change was cancelled.
    """

    BASE = {
        "title": "A title",
        "pillar": "Educație",
        "format": "Reel",
        "hook": "A hook",
        "hook_type": "PROVOCARE",
        "caption": "A caption long enough",
        "hashtags": ["#a", "#b", "#c"],
        "cta": "Book",
        "source": "from memory",
    }

    def test_an_empty_script_is_rejected(self) -> None:
        from pydantic import ValidationError

        from content_studio.harness.posts import SavedPostContent

        with self.assertRaises(ValidationError):
            SavedPostContent.model_validate({**self.BASE, "script": ""})

    def test_the_normalised_form_is_accepted(self) -> None:
        from content_studio.harness.posts import SavedPostContent

        script = ""
        content = SavedPostContent.model_validate(
            {**self.BASE, "script": script or None, "format_details": {} or None}
        )
        self.assertIsNone(content.script)
        self.assertIsNone(content.format_details)


if __name__ == "__main__":
    unittest.main()
