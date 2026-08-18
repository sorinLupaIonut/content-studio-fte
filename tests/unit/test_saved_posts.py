"""Saved-post contracts, the Markdown body and the prepared-run fidelity check.

No database, no MCP server and no model call: every assertion here is about the
shapes that cross those boundaries.
"""

import unittest

from pydantic import ValidationError

from content_studio.harness.models import RunResponse, ToolApprovalRequest
from content_studio.harness.posts import (
    HOOK_TYPE_CODES,
    HOOK_TYPE_LABELS,
    PostUpdateRequest,
    SavedPostContent,
    SavePostsRequest,
    public_post,
)
from content_studio.harness.service import HarnessService
from content_studio.mcp_server.posts_store import _columns, as_markdown

CONTENT = {
    "title": "Când te alegi și pe tine",
    "pillar": "Conexiune",
    "format": "Reel",
    "hook": "Ai grijă de toți, dar de tine cine are?",
    "hook_type": "INTREBARE",
    "script": "Prima linie.\nA doua linie.",
    "caption": "Un caption scurt și cald.",
    "hashtags": ["#burnout", "#limite", "#peoplepleasing"],
    "cta": "Scrie-mi „limite” în DM.",
    "source": "din memorie 🧠 (profil + avatar), fără sursă externă",
    "format_details": {
        "content_blocks": ["Cadru 1: privirea în oglindă", "Cadru 2: textul pe ecran"],
        "visual_direction": "Lumină naturală, cadru fix, fără muzică tare.",
        "duration_or_count": "35–45 secunde",
    },
}


class TestSavedPostContent(unittest.TestCase):
    def test_a_complete_post_validates(self) -> None:
        content = SavedPostContent.model_validate(CONTENT)

        self.assertEqual(content.hook_type, "INTREBARE")
        self.assertEqual(len(content.hashtags), 3)

    def test_hashtags_must_be_single_tokens_beginning_with_hash(self) -> None:
        for bad in (["burnout", "#limite", "#x"], ["#doua cuvinte", "#a", "#b"]):
            with self.assertRaises(ValidationError):
                SavedPostContent.model_validate({**CONTENT, "hashtags": bad})

    def test_hashtags_must_be_unique(self) -> None:
        with self.assertRaises(ValidationError):
            SavedPostContent.model_validate(
                {**CONTENT, "hashtags": ["#a", "#a", "#b"]}
            )

    def test_a_field_the_editor_invented_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            SavedPostContent.model_validate({**CONTENT, "scheduled_for": "mâine"})

    def test_the_browser_draft_is_the_same_contract(self) -> None:
        draft = PostUpdateRequest.model_validate(CONTENT)

        self.assertEqual(draft.title, CONTENT["title"])


class TestSaveRequest(unittest.TestCase):
    def test_the_same_variant_cannot_be_saved_twice(self) -> None:
        variant = "11111111-1111-1111-1111-111111111111"
        with self.assertRaises(ValidationError):
            SavePostsRequest.model_validate({"variant_ids": [variant, variant]})

    def test_a_batch_is_capped_at_ten(self) -> None:
        with self.assertRaises(ValidationError):
            SavePostsRequest.model_validate(
                {"variant_ids": [f"1111111{i}-1111-1111-1111-111111111111" for i in range(11)]}
            )


class TestHookVocabulary(unittest.TestCase):
    def test_the_map_is_a_bijection(self) -> None:
        self.assertEqual(len(HOOK_TYPE_LABELS), len(HOOK_TYPE_CODES))
        for code, label in HOOK_TYPE_LABELS.items():
            self.assertEqual(HOOK_TYPE_CODES[label], code)

    def test_the_column_keeps_the_clients_own_spelling(self) -> None:
        fields, _, _ = _columns(SavedPostContent.model_validate(CONTENT))

        self.assertEqual(fields["hook_type"], "ÎNTREBARE")

    def test_reading_a_saved_post_gives_the_code_back(self) -> None:
        post = public_post({"id": "x", "hook_type": "CIFRĂ", "hashtags": "#a #b"})

        self.assertEqual(post["hook_type"], "CIFRA")
        self.assertEqual(post["hashtags"], ["#a", "#b"])


class TestPublicPost(unittest.TestCase):
    def test_implementation_columns_do_not_reach_the_browser(self) -> None:
        post = public_post(
            {
                "id": "x",
                "title": "T",
                "client_id": "secret",
                "conversation_id": "session",
                "body_md": "# T",
                "source_file": "2026-07-09-t.md",
            }
        )

        self.assertEqual(set(post), {"id", "title"})


class TestPostMarkdown(unittest.TestCase):
    def test_the_body_carries_the_production_block(self) -> None:
        fields, details, body = _columns(SavedPostContent.model_validate(CONTENT))

        self.assertIn("# Când te alegi și pe tine", body)
        self.assertIn("## Producție (35–45 secunde)", body)
        self.assertIn("1. Cadru 1: privirea în oglindă", body)
        self.assertIn("**Hashtaguri:** #burnout #limite #peoplepleasing", body)
        self.assertEqual(details["duration_or_count"], "35–45 secunde")
        self.assertEqual(fields["hashtags"], "#burnout #limite #peoplepleasing")

    def test_a_silent_reel_has_no_script_and_no_production_headings(self) -> None:
        """`body_md` has to be exactly what the columns hold, never a promise."""

        silent = {key: value for key, value in CONTENT.items()}
        del silent["script"]
        del silent["format_details"]
        silent["caption"] = "Un caption lung, care duce tot ce ar fi fost spus."

        _, details, body = _columns(SavedPostContent.model_validate(silent))

        self.assertIsNone(details)
        self.assertNotIn("## Script", body)
        self.assertNotIn("## Producție", body)
        self.assertIn("## Caption", body)
        self.assertIn("Un caption lung", body)

    def test_a_post_without_production_details_is_unchanged(self) -> None:
        fields = {
            "title": "T",
            "pillar": "Educație",
            "format": "Reel",
            "hook": "H",
            "hook_type": "SECRET",
            "script": "S",
            "caption": "C",
            "hashtags": "#a #b",
            "cta": "CTA",
            "source": "memorie",
        }

        self.assertNotIn("## Producție", as_markdown(fields))


def pending(tool_name: str, arguments: dict) -> RunResponse:
    return RunResponse(
        run_id="run-1",
        session_id="posts-save-abc",
        status="pending",
        requests=[
            ToolApprovalRequest(
                call_id="call-1", tool_name=tool_name, arguments=arguments
            )
        ],
    )


class TestPreparedRunFidelity(unittest.TestCase):
    """The gate stops an unwanted write; this stops a write of the wrong thing."""

    def test_an_exact_preparation_passes(self) -> None:
        expected = {"variant_ids": ["a", "b"]}

        self.assertIsNone(
            HarnessService._mismatch(
                pending("save_posts_batch", expected), "save_posts_batch", expected
            )
        )

    def test_a_changed_argument_is_caught(self) -> None:
        result = pending("save_posts_batch", {"variant_ids": ["a"]})

        self.assertIn(
            "variant_ids",
            HarnessService._mismatch(
                result, "save_posts_batch", {"variant_ids": ["a", "b"]}
            ),
        )

    def test_a_reworded_post_is_caught(self) -> None:
        asked = {"post_id": "p1", **CONTENT}
        drifted = {**asked, "caption": "Un caption pe care l-am îmbunătățit eu."}

        self.assertIn(
            "caption",
            HarnessService._mismatch(
                pending("update_post", drifted), "update_post", asked
            ),
        )

    def test_another_tool_is_caught(self) -> None:
        result = pending("save_post", {"title": "T"})

        self.assertIn(
            "save_post",
            HarnessService._mismatch(result, "save_posts_batch", {"variant_ids": []}),
        )

    def test_a_run_that_did_not_stop_at_the_gate_is_caught(self) -> None:
        finished = RunResponse(
            run_id="run-1", session_id="s", status="completed", output="gata"
        )

        self.assertIsNotNone(
            HarnessService._mismatch(finished, "save_posts_batch", {})
        )

    def test_two_prepared_calls_are_caught(self) -> None:
        result = pending("save_posts_batch", {"variant_ids": ["a"]})
        result.requests.append(
            ToolApprovalRequest(
                call_id="call-2", tool_name="save_posts_batch", arguments={}
            )
        )

        self.assertIsNotNone(
            HarnessService._mismatch(
                result, "save_posts_batch", {"variant_ids": ["a"]}
            )
        )


if __name__ == "__main__":
    unittest.main()
