"""The output language: how it is parsed, and where it reaches the agent.

The point of these tests is the seam, not the wording of the override. The
method stays Romanian on disk; only the appended block changes, and only when
something asked for a language that is not the default.
"""

import unittest

from agents.mcp import MCPServerStreamableHttp

from content_studio.harness.chat import ChatRunRequest, chat_prompt
from content_studio.harness.generation import (
    GenerationBatchRequest,
    GenerationStartRequest,
    IdeaTitle,
    detail_prompt,
    title_prompt,
)
from content_studio.harness.models import DecisionsRequest, RunRequest
from content_studio.language import (
    DEFAULT_LANGUAGE,
    ENGLISH_OVERRIDE,
    instruction_suffix,
    normalise,
)
from content_studio.worker import build_worker


class TestNormalise(unittest.TestCase):
    def test_nothing_asked_means_romanian(self):
        self.assertEqual(normalise(None), "ro")
        self.assertEqual(DEFAULT_LANGUAGE, "ro")

    def test_case_and_region_are_ignored(self):
        for value in ("EN", "en", "en-US", "en_GB", "  En  "):
            self.assertEqual(normalise(value), "en", value)

    def test_a_language_this_build_does_not_have_falls_back(self):
        # A stale browser tab must still get an answer, not a 422.
        self.assertEqual(normalise("de"), "ro")
        self.assertEqual(normalise(""), "ro")


class TestInstructionSuffix(unittest.TestCase):
    def test_romanian_appends_nothing(self):
        # The base instructions already say Romanian; repeating it would only
        # spend context.
        self.assertEqual(instruction_suffix("ro"), "")
        self.assertEqual(instruction_suffix(None), "")

    def test_english_appends_the_override(self):
        suffix = instruction_suffix("en")
        self.assertIn(ENGLISH_OVERRIDE, suffix)
        self.assertTrue(suffix.startswith("\n\n"))

    def test_the_override_contradicts_the_romanian_rule_in_as_many_words(self):
        # Half-measures make the model split the difference and answer in both.
        self.assertIn("overrides the Romanian-language rule", ENGLISH_OVERRIDE)
        self.assertIn("does not apply", ENGLISH_OVERRIDE)

    def test_the_override_protects_the_controlled_values(self):
        # A translated pillar or hook type is a rejected write, not a nicer
        # reading experience - the database and the tools match on these.
        self.assertIn("are NOT translated", ENGLISH_OVERRIDE)
        for value in ("PROVOCARE", "Poziționare", "Carusel", "Memorie"):
            self.assertIn(value, ENGLISH_OVERRIDE, value)


class TestRequestContracts(unittest.TestCase):
    """Every body that can start or resume agent work carries a language."""

    def test_each_entry_point_defaults_to_romanian(self):
        self.assertEqual(RunRequest(message="salut").language, "ro")
        self.assertEqual(ChatRunRequest(message="salut").language, "ro")
        self.assertEqual(
            GenerationStartRequest(
                format="Reel", pillar="Educație", source="Memorie"
            ).language,
            "ro",
        )

    def test_english_is_accepted_on_each_entry_point(self):
        self.assertEqual(RunRequest(message="hi", language="en").language, "en")
        self.assertEqual(ChatRunRequest(message="hi", language="en").language, "en")
        self.assertEqual(
            DecisionsRequest(
                session_id="s1",
                decisions=[{"call_id": "c1", "approved": True}],
                language="en",
            ).language,
            "en",
        )

    def test_the_generation_language_never_reaches_the_mcp_tool_arguments(self):
        # GenerationBatchRequest is serialised straight into the tool call, so a
        # language field there would be an unexpected argument.
        start = GenerationStartRequest(
            format="Reel", pillar="Educație", source="Memorie", language="en"
        )
        payload = start.model_dump(exclude={"replace_current", "language"})
        self.assertNotIn("language", payload)


class TestTheAgentActuallyGetsIt(unittest.TestCase):
    """The seam that matters: what `build_worker` hands the model.

    No network and no model call - the agent is only constructed, never run.
    """

    @staticmethod
    def _stub_mcp() -> MCPServerStreamableHttp:
        # Never connected; build_worker only needs the object to hold onto.
        return MCPServerStreamableHttp(params={"url": "http://localhost:1/mcp"})

    def test_romanian_is_the_untouched_default(self):
        agent = build_worker("PROFILUL", self._stub_mcp())
        self.assertNotIn("OUTPUT LANGUAGE: ENGLISH", agent.instructions)

    def test_english_appends_the_override_and_keeps_the_method(self):
        agent = build_worker("PROFILUL", self._stub_mcp(), language="en")
        self.assertIn("OUTPUT LANGUAGE: ENGLISH", agent.instructions)
        # The Romanian prompt is still there - the override adds, never replaces.
        # It used to check for "REGULI OBLIGATORII"; those moved out of the prompt
        # on 2026-08-24 (the orphaned OUTPUT_RULES constant was deleted on
        # 2026-08-26 - the contract lives in the skills and the generation
        # schemas now). What the test is really about is that the method note
        # survives the override, so that is what it asks for now.
        self.assertIn("APLICAREA METODEI ESTE OBLIGATORIE", agent.instructions)
        self.assertIn("CU CINE VORBE", agent.instructions)
        self.assertIn("PROFILUL", agent.instructions)

    def test_the_override_comes_last(self):
        # Closest contradiction wins, so it has to sit after rule 1 and after
        # the profile rather than anywhere earlier.
        agent = build_worker("PROFILUL", self._stub_mcp(), language="en")
        self.assertLess(
            agent.instructions.index("PROFILUL"),
            agent.instructions.index("OUTPUT LANGUAGE: ENGLISH"),
        )


class TestTaskPromptsCarryTheLanguage(unittest.TestCase):
    """The regression that cost a deploy.

    The system-prompt override was in place and correct, and the first English
    chat still came back in Romanian: `chat_prompt` said "răspunde în română"
    inside the *user message*, which sits closer to the answer than any system
    prompt and therefore wins. Every task prompt in this codebase is written in
    Romanian, so each one has to restate the language.
    """

    @staticmethod
    def _request() -> GenerationBatchRequest:
        return GenerationBatchRequest(
            format="Reel", pillar="Educație", source="Memorie"
        )

    def test_the_chat_prompt_no_longer_hard_codes_romanian(self):
        english = chat_prompt("hi", None, "en")
        self.assertIn("IN ENGLISH", english)
        self.assertNotIn("Răspunde natural, în română", english)

    def test_the_chat_prompt_is_unchanged_for_romanian(self):
        romanian = chat_prompt("salut", None)
        self.assertIn("Răspunde natural, în română", romanian)
        self.assertNotIn("IN ENGLISH", romanian)

    def test_both_generation_prompts_restate_the_language(self):
        idea = IdeaTitle(ordinal=1, title="Un titlu", angle="un unghi")
        for prompt in (
            title_prompt(self._request(), language="en"),
            detail_prompt(self._request(), idea, language="en"),
        ):
            self.assertIn("ANSWER IN ENGLISH", prompt)

    def test_romanian_generation_prompts_are_byte_identical_to_before(self):
        idea = IdeaTitle(ordinal=1, title="Un titlu", angle="un unghi")
        self.assertNotIn("ENGLISH", title_prompt(self._request()))
        self.assertNotIn("ENGLISH", detail_prompt(self._request(), idea))

    def test_the_language_arrives_positionally_the_way_the_engine_sends_it(self):
        # EVERY OTHER TEST HERE PASSES `language=` BY KEYWORD, and that is how
        # this shipped broken: `title_prompt` kept a dead `book_titles`
        # parameter on position three after the 2026-08-27 refactor, while
        # `generator.py` had always called it positionally. The language landed
        # in `book_titles`, the prompt stayed Romanian, and 375 keyword-passing
        # tests saw nothing. Both prompts are called exactly as the engine calls
        # them.
        idea = IdeaTitle(ordinal=1, title="Un titlu", angle="un unghi")
        self.assertIn("ANSWER IN ENGLISH", title_prompt(self._request(), "", "en"))
        self.assertIn(
            "ANSWER IN ENGLISH", detail_prompt(self._request(), idea, "", "en")
        )

    def test_the_task_note_protects_the_controlled_values_too(self):
        # The note lands in the same message as `Pilon: Educație`; without this
        # the model is being shown a Romanian value and told to write English.
        note = title_prompt(self._request(), language="en")
        self.assertIn("keep their Romanian spelling", note)


if __name__ == "__main__":
    unittest.main()
