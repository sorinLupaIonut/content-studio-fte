"""Her corpus is split three ways, and the slices must not touch.

`content/corpus/` holds 56 posts she wrote and published. Three different things
read it, and each one is spoiled by seeing what another was given:

  · ANCHOR   — shown to the JUDGE, as what her writing (and this medium) looks
               like. `cases.anchor_examples`.
  · SPECIMEN — shown to the WRITER, out of the „Postări scrise de tine" section
               of her profile. `cases.shown_to_the_writer`.
  · CONTROL  — what is left, and the only slice `cases.her_own` returns.

A judge handed the text it is about to grade is measuring recall. A writer
graded on text it was handed is measuring copying. Neither failure raises, and
neither is visible in a score — a metric that leaks reads BETTER, which is why
this is a test and not a comment.

The specimen slice is DERIVED, not listed: it is whatever her profile carries,
so she can swap an example without anybody updating a constant. That is also why
an empty specimen section is not a failure here — a client who has put no
finished posts in her profile is a supported state, and it leaks nothing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.output.cases import (  # noqa: E402
    ANCHORS_PER_THEME,
    _corpus_blocks,
    anchor_block,
    anchor_examples,
    her_own,
    shown_to_the_writer,
)

#: Long enough to identify one post and short enough to survive the whitespace
#: differences between a corpus file and a profile section.
FINGERPRINT = 120


class CorpusSlices(unittest.TestCase):
    def test_the_corpus_is_there(self) -> None:
        blocks = _corpus_blocks()
        self.assertGreater(len(blocks), 20, "her corpus did not load")

    def test_the_judge_is_shown_something(self) -> None:
        anchors = anchor_examples()
        self.assertTrue(anchors)
        themes = {theme for theme, _, _, _ in _corpus_blocks()}
        self.assertEqual(len(anchors), len(themes) * ANCHORS_PER_THEME)
        block = anchor_block()
        for hook, _ in anchors:
            self.assertIn(hook, block)

    def test_no_anchor_is_a_control(self) -> None:
        # The judge would be recognising a string it was handed, not grading.
        anchored = {caption[:FINGERPRINT] for _, caption in anchor_examples()}
        anchored |= {hook for hook, _ in anchor_examples()}
        for case in her_own():
            self.assertNotIn(
                case.text[:FINGERPRINT],
                anchored,
                f"{case.case_id} is both a control and an anchor",
            )

    def test_no_specimen_is_a_control(self) -> None:
        # The writer was given this one; grading it measures copying.
        shown = shown_to_the_writer()
        if not shown:
            self.skipTest("her profile carries no specimens")
        for case in her_own():
            self.assertNotIn(
                case.text[:FINGERPRINT],
                shown,
                f"{case.case_id} was shown to the writer and is graded as a control",
            )

    def test_no_specimen_is_an_anchor(self) -> None:
        # Not a leak on its own, but it wastes the two slices that cost the
        # most: the judge and the writer would be looking at the same posts,
        # and the metric would stop being able to tell them apart.
        shown = shown_to_the_writer()
        if not shown:
            self.skipTest("her profile carries no specimens")
        for _, caption in anchor_examples():
            self.assertNotIn(
                caption[:FINGERPRINT],
                shown,
                "an anchor is also a specimen",
            )

    def test_specimens_carry_no_hashtags(self) -> None:
        """Her real captions end in hashtags; the schema says captions do not.

        On Instagram it is one box, so all 56 of her published captions carry a
        row of #tags and a run of bare keywords at the end. The application
        keeps `caption`, `hashtags` and `source` apart — `generation.
        CAPTION_SHAPE` says so on the field — so a specimen pasted whole would
        show the writer exactly what the schema forbids, and the specimen is the
        louder of the two.
        """
        shown = shown_to_the_writer()
        if not shown:
            self.skipTest("her profile carries no specimens")
        self.assertNotIn("#", shown, "a specimen still carries its hashtag tail")


if __name__ == "__main__":
    unittest.main()
