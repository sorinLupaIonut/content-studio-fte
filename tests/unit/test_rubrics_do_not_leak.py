"""A rubric must not quote the controls that are supposed to test it.

Both output metrics are judged against a control set: her own published writing,
which must pass, and planted violations, which must fail. The rubric is allowed
to describe what a fault looks like — a judge with no anchors is inconsistent,
measured on 2026-09-01: stripping the examples out of `human` took the planted
set from 4/4 to 2/4.

But the anchors must not be the control texts themselves. A rubric that quotes
its own answer key does not measure whether the judge can recognise a fault; it
measures whether the judge can match a string it was handed three paragraphs
earlier. Both rubrics did exactly that when first written:

  · `human` quoted „mai puțin oboseală", which is inside `planted-human-4` — a
    caption taken verbatim from a real run. It scored 4/4 on the planted set.
    Replaced with a different specimen of the same fault („mai mult energie"),
    the same judge scored 2/4. The 4/4 was recall.
  · `voice` quoted „Porți epuizarea ca pe o medalie." and „Spuneam DA la toată
    lumea." — two of the eight hooks `her_own()` hands over as positive
    controls.

The replacements had to be checked too: the first pick for `voice`, „Tu ce voce
asculți cel mai des", is absent from the hook controls and present in a CAPTION
control, which the first check missed by only looking at hooks. Hence this test,
over the whole control set, both fields.

Five words is the window. Shorter matches ordinary Romanian („nu ești singură"),
longer would let a rubric quote most of a hook and still pass.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.output.cases import her_own, planted  # noqa: E402
from evals.output.human import JUDGE_PROMPT as HUMAN_PROMPT  # noqa: E402
from evals.output.voice import JUDGE_PROMPT as VOICE_PROMPT  # noqa: E402

#: Long enough that an ordinary Romanian phrase does not trip it, short enough
#: that quoting half a hook cannot slip through.
WINDOW = 5


def leaks(rubric: str, which: str) -> list[tuple[str, str]]:
    """(case id, fragment) for every control the rubric quotes verbatim."""

    found: list[tuple[str, str]] = []
    for case in her_own() + planted(which):
        words = case.text.split()
        for index in range(max(0, len(words) - WINDOW + 1)):
            fragment = " ".join(words[index : index + WINDOW]).strip(".,!?—:;")
            if fragment and fragment in rubric:
                found.append((case.case_id, fragment))
                break
    return found


class RubricsDoNotQuoteTheirControls(unittest.TestCase):
    def test_voice(self) -> None:
        found = leaks(VOICE_PROMPT, "voice")
        self.assertEqual(
            found,
            [],
            "the voice rubric quotes its own control set; pick an example from a "
            "post `her_own(limit=8)` does not reach",
        )

    def test_human(self) -> None:
        found = leaks(HUMAN_PROMPT, "human")
        self.assertEqual(
            found,
            [],
            "the human rubric quotes its own control set; name the same KIND of "
            "fault with a different specimen",
        )

    def test_the_check_can_actually_fail(self) -> None:
        # A guard nobody has seen fail is a guard nobody should trust. This is
        # the shape both rubrics really had.
        control = her_own()[0]
        planted_case = planted("human")[0]
        for case in (control, planted_case):
            with self.subTest(case=case.case_id):
                rigged = f"For example, avoid: {case.text}"
                self.assertTrue(leaks(rigged, "human"))


if __name__ == "__main__":
    unittest.main()
