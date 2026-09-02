"""Her voice reaches the writer, and the judge grades against the same text.

`content_studio/voice.py` lifts four sections out of the profile — the same
repair `avatar.py` made for the pains, one door down and eleven days later.
Three things have to hold, and each has failed once in this repository already:

  1. THE SECTIONS ARE FOUND. `avatar.py` records what it costs when they are
     not: an English profile scored 0 of 5, the block silently left the prompt,
     and the only symptom was the failure the module existed to fix. `excerpt`
     returns "" rather than raising, on purpose, so nothing else objects.
  2. BOTH LANGUAGES. A translated profile is a supported state, and the English
     headings are a separate list that can drift from the Romanian one.
  3. THE WRITER AND THE JUDGE READ ONE TEXT. `evals/output/voice.py` grades
     against her voice; if it kept its own copy of these sections, the metric
     would drift from the prompt and grade a specification the studio was never
     given. It has to IMPORT this module.

The third is checked by walking the eval's AST rather than by reading it,
because the defect is a copy that LOOKS right — the same reason
`test_profile_scope.py` walks for an argument that is absent.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from content_studio import voice
from content_studio.config import CONTENT_DIR

ROOT = Path(__file__).resolve().parents[2]
PROFILE = CONTENT_DIR / "profile.md"
EVAL = ROOT / "evals" / "output" / "voice.py"


class TheSectionsAreFound(unittest.TestCase):
    def test_the_real_profile_yields_every_section(self) -> None:
        found = voice.sections_of(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(
            len(found),
            len(voice.VOICE_SECTIONS),
            "a section moved or was renamed in content/profile.md",
        )

    def test_the_block_carries_material_and_its_instruction(self) -> None:
        brief = voice.brief(PROFILE.read_text(encoding="utf-8"))
        self.assertIn("HOW SHE WRITES", brief)
        self.assertIn(voice.VOICE_ASK, brief)
        # Roughly 3.7 KB of her own text on 2026-09-01. A floor, not a target:
        # it catches a heading regex that starts matching only the titles.
        self.assertGreater(len(brief), 2_000)

    def test_a_profile_without_them_is_empty_and_does_not_raise(self) -> None:
        # The client must not be stopped from generating by a profile she
        # restructured. The prompt drops the block; the eval is what notices.
        self.assertEqual(voice.excerpt("# nothing familiar here"), "")
        self.assertEqual(voice.brief("# nothing familiar here"), "")


class BothLanguages(unittest.TestCase):
    def test_the_two_lists_are_the_same_length(self) -> None:
        self.assertEqual(len(voice.VOICE_SECTIONS), len(voice.VOICE_SECTIONS_EN))

    def test_an_english_profile_yields_the_same_count(self) -> None:
        english = "\n\n".join(
            f"### {title}\nsomething she wrote here, at length."
            for title in voice.VOICE_SECTIONS_EN
        )
        self.assertEqual(
            len(voice.sections_of(english)), len(voice.VOICE_SECTIONS_EN)
        )

    def test_a_heading_that_is_not_hers_is_skipped_silently(self) -> None:
        partial = "### Vocea ta\nasa scriu eu.\n\n### Altceva\nnu conteaza."
        found = voice.sections_of(partial)
        self.assertEqual(len(found), 1)
        self.assertIn("Vocea ta", found[0])


class TheSpecimensReachTheWriterAndNotTheJudge(unittest.TestCase):
    """The mechanism, tested on a profile this file builds.

    NOT ON HERS, AND THAT IS THE POINT — twice over. Her profile carried three
    specimens for part of 2026-09-01, lifted from `content/posts/`, which turned
    out to be the STUDIO'S OWN OUTPUT rather than anything she published. A
    generator taught from its own writing has no way to stop sounding like
    itself. They came out the same day and were replaced with four real ones out
    of `content/corpus/`.

    The mechanism never moved: per client, out of her own profile, shown to the
    writer and never to the judge. Only the material was wrong. Testing it
    against a built profile is what keeps it from passing because HER profile
    happens to be in the right shape today — including the empty case, which is
    a supported state for every client who has not filled the section in.
    """

    DESCRIBED = "### Vocea ta\nasa scriu eu, pe indelete si cald."
    WITH_POSTS = (
        DESCRIBED
        + "\n\n### Postări scrise de tine\n"
        + "> O postare intreaga, asa cum a publicat-o ea.\n"
        + "\n### Altceva\nnu conteaza."
    )

    def test_the_writer_gets_them(self) -> None:
        brief = voice.brief(self.WITH_POSTS)
        self.assertIn(voice.specimens(self.WITH_POSTS), brief)
        self.assertIn(voice.SPECIMEN_ASK, brief)

    def test_the_judge_does_not(self) -> None:
        self.assertNotIn(
            voice.specimens(self.WITH_POSTS), voice.excerpt(self.WITH_POSTS)
        )

    def test_a_profile_with_no_examples_still_yields_a_block(self) -> None:
        # Three of the four accounts are in this state. Not a defect: the
        # description alone is what the writer had before specimens existed.
        self.assertEqual(voice.specimens(self.DESCRIBED), "")
        self.assertIn("HOW SHE WRITES", voice.brief(self.DESCRIBED))

    def test_nothing_shown_to_the_writer_is_also_a_control(self) -> None:
        # Walked rather than counted: a control set that silently contains text
        # the writer was handed reads as a perfect score. Vacuous only for a
        # client whose section is empty, and load-bearing for hers, which is not.
        import sys

        sys.path.insert(0, str(ROOT))
        from evals.output.cases import her_own, shown_to_the_writer

        shown = shown_to_the_writer()
        for case in her_own(limit=40):
            if shown:
                self.assertNotIn(case.text[:120], shown, case.case_id)


class TheJudgeReadsTheSameText(unittest.TestCase):
    def test_the_eval_imports_this_module_rather_than_copying_it(self) -> None:
        tree = ast.parse(EVAL.read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertIn(
            "content_studio.voice",
            imported,
            "evals/output/voice.py must import the voice block, not restate it",
        )

    def test_the_eval_holds_no_section_titles_of_its_own(self) -> None:
        # A copy would most likely arrive as a tuple of headings pasted in. The
        # rubric may NAME one section to tell the judge what to look at; two or
        # more is the set, and the set is a copy.
        text = EVAL.read_text(encoding="utf-8")
        carried = sum(1 for title in voice.VOICE_SECTIONS if title in text)
        self.assertLessEqual(
            carried,
            1,
            "evals/output/voice.py names more than one section title: that is a "
            "second copy of VOICE_SECTIONS waiting to drift",
        )


if __name__ == "__main__":
    unittest.main()
