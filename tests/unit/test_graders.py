"""The deterministic half of the rubric, on fabricated runs.

No model and no network. That is the point of the split: a caption is 863
characters or it is not, and paying a judge to count them would be the most
expensive way to learn a number. Every threshold here comes from
`evals/trace-rubric.json`, so a rule changed there and not here fails loudly.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from evals.grade import (
    RUBRIC_FILE,
    grade_contract_quality,
    grade_tool_correctness,
    judge_criteria,
    load_rubric,
    run_kind,
    testing_criteria,
)
from evals.traces import GradedRun, ToolCall

RUBRIC = load_rubric()
NOW = datetime(2026, 8, 25, 6, 0, tzinfo=UTC)


def _run(
    session: str = "generation-abc",
    tools: list[str] | None = None,
    commands: list[str] | None = None,
) -> GradedRun:
    """A graded run. `tools` are bare names; `commands` are shell calls.

    Two parameters because the method and the data are reached differently now:
    data still goes through named MCP tools, the method goes through one shell
    tool whose argument is a command string.
    """
    calls = [ToolCall(name=n, input="{}", output="") for n in (tools or [])]
    calls += [
        ToolCall(name="exec_command", input=c, output="") for c in (commands or [])
    ]
    return GradedRun(
        run_id="run-1",
        session_id=session,
        started_at=NOW,
        status="completed",
        input_message="cerere",
        output_message="răspuns",
        tool_calls=calls,
    )


def _detail(captions: list[int], hashtags: list[list[str]] | None = None) -> dict:
    tags = hashtags or [["#a", "#b", "#c"] for _ in captions]
    return {
        "idea_ordinal": 1,
        "title": "T",
        "variants": [
            {"hook_type": "PROVOCARE", "caption": "x" * n, "hashtags": t}
            for n, t in zip(captions, tags, strict=True)
        ],
    }


def _titles(angle_types: list[str]) -> dict:
    return {
        "ideas": [
            {"ordinal": i, "angle_type": a, "title": f"T{i}", "angle": "u"}
            for i, a in enumerate(angle_types, start=1)
        ]
    }


class WhichBranchApplies(unittest.TestCase):
    def test_a_detail_run_is_recognised(self) -> None:
        self.assertEqual(run_kind(_run("generation-detail-abc-123")), "generation-detail")

    def test_a_title_run_is_recognised(self) -> None:
        self.assertEqual(run_kind(_run("generation-abc-123")), "generation-title")

    def test_anything_else_is_chat(self) -> None:
        self.assertEqual(run_kind(_run("chat-abc")), "chat")

    def test_the_kind_comes_from_the_session_not_the_prose(self) -> None:
        """`input_message` is Romanian prose and will be reworded one day. The
        session prefix is built by the harness and will not."""
        run = _run("chat-abc")
        run.input_message = "Dezvoltă ideea 1 din lotul abc"
        self.assertEqual(run_kind(run), "chat")


class ToolCorrectnessAsksOneQuestion(unittest.TestCase):
    """Did the run open the method before it wrote?

    It had two branches while the generation path was handed its method
    preloaded. Since the method moved into the sandbox on 2026-08-27 both doors
    take the same three steps, so there is one question again - and the answer
    is read off a shell command rather than off a tool name.
    """

    def test_a_run_that_opened_nothing_fails(self) -> None:
        """The silent failure this whole rubric exists for: no error, no log,
        and an answer written from memory."""
        finding = grade_tool_correctness(_run("generation-abc"), "generation-title")
        self.assertEqual(finding.score, 0.0)
        self.assertIn("nu a deschis metoda", finding.detail)

    def test_opening_the_skill_body_is_enough_to_pass(self) -> None:
        run = _run(
            "generation-abc",
            commands=["{\"cmd\": \"sed -n '1,200p' .agents/propune-postari/SKILL.md\"}"],
        )
        self.assertEqual(grade_tool_correctness(run, "generation-title").score, 1.0)

    def test_cat_counts_the_same_as_sed(self) -> None:
        """The check is deliberately loose about HOW the file was opened.

        A check that only understood `sed` would score zero for a run that used
        `cat` - and read exactly like a run that never opened the method.
        """
        run = _run(
            "chat-abc",
            commands=['{"cmd": "cat .agents/dezvolta-postarea/references/b-roll.md"}'],
        )
        self.assertEqual(grade_tool_correctness(run, "chat").score, 1.0)

    def test_a_data_tool_is_not_the_method(self) -> None:
        """`search_books` is data. Calling it says nothing about the method."""
        run = _run("generation-abc", tools=["search_books"])
        self.assertEqual(grade_tool_correctness(run, "generation-title").score, 0.0)

    def test_a_shell_call_that_is_not_about_the_method_does_not_count(self) -> None:
        run = _run("chat-abc", commands=['{"cmd": "ls -la /workspace"}'])
        self.assertEqual(grade_tool_correctness(run, "chat").score, 0.0)

    def test_it_counts_how_many_commands_opened_the_method(self) -> None:
        run = _run(
            "generation-abc",
            commands=[
                '{"cmd": "cat .agents/dezvolta-postarea/SKILL.md"}',
                '{"cmd": "cat .agents/dezvolta-postarea/references/b-roll.md"}',
            ],
        )
        self.assertIn("2", grade_tool_correctness(run, "generation-detail").detail)


class CaptionLength(unittest.TestCase):
    """Was the open one. Measured 2026-08-24: mini averaged 668 against
    900–1400, 0 of 50 in range. The window moved to 650–1200 on 2026-08-25 —
    set from the client's own twenty-one published captions, median 772 — and
    the schema floor with it; the next batch landed 5 of 5 inside. The fixtures
    below are the window's numbers, so moving it again fails here first."""

    def test_all_in_range_scores_one(self) -> None:
        findings = grade_contract_quality([_detail([700, 950, 1199])], RUBRIC)
        caption = next(f for f in findings if f.criterion == "caption_length")
        self.assertEqual(caption.score, 1.0)

    def test_the_real_measurement_scores_zero(self) -> None:
        findings = grade_contract_quality([_detail([627, 547, 579, 495, 543])], RUBRIC)
        caption = next(f for f in findings if f.criterion == "caption_length")
        self.assertEqual(caption.score, 0.0)
        self.assertIn("0/5", caption.detail)

    def test_too_long_counts_against_it_too(self) -> None:
        """The ceiling is not a suggestion — a caption nobody reads to the end
        is as much a failure as one that says nothing."""
        findings = grade_contract_quality([_detail([2000])], RUBRIC)
        caption = next(f for f in findings if f.criterion == "caption_length")
        self.assertEqual(caption.score, 0.0)

    def test_the_detail_carries_the_numbers_not_only_the_verdict(self) -> None:
        findings = grade_contract_quality([_detail([400, 1000])], RUBRIC)
        caption = next(f for f in findings if f.criterion == "caption_length")
        for fragment in ("medie", "min 400", "max 1000"):
            self.assertIn(fragment, caption.detail)


class DistinctAngles(unittest.TestCase):
    def test_ten_different_archetypes_score_one(self) -> None:
        from content_studio.harness.generation import ANGLE_TYPES

        findings = grade_contract_quality([_titles(list(ANGLE_TYPES))], RUBRIC)
        angles = next(f for f in findings if f.criterion == "distinct_angles")
        self.assertEqual(angles.score, 1.0)

    def test_a_repeat_shows_up(self) -> None:
        """Before ANGLE_TYPES, batch a16a3f94 proposed delegation twice. This is
        the criterion that would have said so without anyone reading ten titles."""
        findings = grade_contract_quality(
            [_titles(["DURERE", "MIT", "METODA", "POVESTE", "GRESEALA",
                      "INAINTE_DUPA", "CULISE", "DOVADA", "OBIECTIE", "DURERE"])],
            RUBRIC,
        )
        angles = next(f for f in findings if f.criterion == "distinct_angles")
        self.assertLess(angles.score, 1.0)
        self.assertIn("repetat", angles.detail)


class Hashtags(unittest.TestCase):
    def test_clean_tags_need_no_repair(self) -> None:
        findings = grade_contract_quality([_detail([500], [["#a", "#b", "#c"]])], RUBRIC)
        tags = next(f for f in findings if f.criterion == "hashtags")
        self.assertEqual(tags.score, 1.0)

    def test_the_repair_rate_is_visible(self) -> None:
        """39 of 44 failed turns died on this before the repair landed. The
        grader counts how often the net catches something, so a rise is seen."""
        findings = grade_contract_quality(
            [_detail([500], [["#bun", "#cu spatiu", "faraDiez"]])], RUBRIC
        )
        tags = next(f for f in findings if f.criterion == "hashtags")
        self.assertAlmostEqual(tags.score, 1 / 3)
        self.assertIn("2 din 3", tags.detail)


class NothingToGrade(unittest.TestCase):
    def test_no_answers_produces_no_findings(self) -> None:
        """A dry run has no fetched answers. Silence beats a zero nobody earned."""
        self.assertEqual(grade_contract_quality([], RUBRIC), [])

    def test_a_chat_reply_is_not_a_contract(self) -> None:
        self.assertEqual(grade_contract_quality([{"text": "salut"}], RUBRIC), [])


class TheJudgeSideOfTheRubric(unittest.TestCase):
    def test_attribution_is_left_out_when_nothing_was_retrieved(self) -> None:
        """The first live grading run scored attribution 1.0 on two batches
        written from memory — true, and useless. A criterion that always passes
        is one nobody will believe on the day it fails."""
        names = [c["name"] for c in testing_criteria(RUBRIC, any_retrieval=False)]
        self.assertIn("policy", names)
        self.assertNotIn("attribution", names)

    def test_attribution_returns_when_passages_came_back(self) -> None:
        names = [c["name"] for c in testing_criteria(RUBRIC, any_retrieval=True)]
        self.assertIn("attribution", names)

    def test_every_judge_criterion_is_a_score_model(self) -> None:
        """`score_model`, not `label_model`: a threshold you can move beats a
        pass/fail somebody has to re-argue."""
        for criterion in testing_criteria(RUBRIC, any_retrieval=True):
            self.assertEqual(criterion["type"], "score_model")
            self.assertIn("pass_threshold", criterion)

    def test_the_prompts_are_romanian(self) -> None:
        """She writes in Romanian and the judge reads her text. An English
        rubric grading Romanian prose grades the translation."""
        for criterion in judge_criteria(RUBRIC):
            joined = "\n".join(criterion["prompt"])
            self.assertTrue(
                any(word in joined for word in ("Notează", "penaliza", "textul")),
                criterion["id"],
            )


class TheRubricFileItself(unittest.TestCase):
    def test_it_parses_and_names_its_criteria(self) -> None:
        ids = {c["id"] for c in RUBRIC["criteria"]}
        self.assertEqual(
            ids, {"tool_correctness", "contract_quality", "policy", "attribution"}
        )

    def test_every_criterion_declares_how_it_is_read(self) -> None:
        for criterion in RUBRIC["criteria"]:
            self.assertIn(criterion["kind"], {"deterministic", "judge"})

    def test_it_lives_next_to_the_grader(self) -> None:
        self.assertTrue(Path(RUBRIC_FILE).is_file())


if __name__ == "__main__":
    unittest.main()
