"""The English labels Python dictates are the ones the interface shows.

`ENGLISH_LABELS` in `conversations.py` is a second copy of pairs that already
exist in `ui/StudioViorela/Localization/Values.cs`, and a second copy is exactly
what this repository refuses everywhere else. It is kept because the sentence a
button dictates is composed on the server, where no C# runs — so the copy is
allowed only on the condition that a test reads the original and holds it to it.

That is what this file does: it parses `Values.cs` and compares, pair by pair.
The failure it prevents is silent — a pillar renamed in the interface and not
here would put one English word in the interface and a different one in the
transcript of the same click, and nothing would raise.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from content_studio.harness.conversations import ENGLISH_LABELS, english_label

VALUES_CS = (
    Path(__file__).resolve().parents[2]
    / "ui"
    / "StudioViorela"
    / "Localization"
    / "Values.cs"
)

#: The four switches that map a domain VALUE to a label. `Values.cs` calls
#: `t.Pick` elsewhere too — for status lines and button text — and those are
#: prose, not vocabulary, so they are deliberately not read here.
LABEL_METHODS = ("SourceLabel", "PillarLabel", "FormatLabel", "HookLabel")

ARM = re.compile(r'"([^"]+)"\s*=>\s*t\.Pick\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)')


def pairs_from_values_cs() -> dict[str, str]:
    """{romanian value: english label} exactly as the interface defines it."""

    text = VALUES_CS.read_text("utf-8")
    found: dict[str, str] = {}
    for method in LABEL_METHODS:
        start = text.index(f"public static string {method}(")
        # Each switch ends at its default arm; nothing after it is vocabulary.
        end = text.index("_ => value", start)
        for value, _romanian, english in ARM.findall(text[start:end]):
            found[value] = english
    return found


class TheDictatedLabels(unittest.TestCase):
    def test_the_file_the_interface_uses_is_still_there(self) -> None:
        """A moved `Values.cs` must fail loudly here, not skip the comparison."""
        self.assertTrue(VALUES_CS.is_file(), f"{VALUES_CS} is gone")

    def test_every_pair_matches_the_interface(self) -> None:
        interface = pairs_from_values_cs()
        self.assertTrue(interface, "no label arms parsed out of Values.cs")
        self.assertEqual(ENGLISH_LABELS, interface)

    def test_all_four_vocabularies_are_covered(self) -> None:
        """Sources, pillars, formats and hook types — 17 values in total."""
        interface = pairs_from_values_cs()
        for value in ("Memorie", "Educație", "Carusel", "PROVOCARE"):
            self.assertIn(value, interface)
        self.assertEqual(len(interface), 17)


class TheHelper(unittest.TestCase):
    def test_it_translates_what_it_knows(self) -> None:
        self.assertEqual(english_label("Educație"), "Education")
        self.assertEqual(english_label("PROVOCARE"), "Challenge")

    def test_an_unknown_value_passes_through(self) -> None:
        """A new pillar should read oddly in one sentence, never break a click."""
        self.assertEqual(english_label("Ceva Nou"), "Ceva Nou")


if __name__ == "__main__":
    unittest.main()
