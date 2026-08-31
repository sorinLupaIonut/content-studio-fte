"""A profile written in English has to be readable by the code that matches it.

Two matchers read a profile by its heading text, and both were Romanian-only
until 2026-08-31, when the first English profile arrived. Neither raises when it
matches nothing - `sections_of` skips, `category_for` falls through to
`identity` - so the whole failure was silent, and the symptom was worse writing
and wrong tabs rather than an error.

Measured on that first English profile, before the fix: 5 of 5 avatar sections
found in Romanian and 0 of 5 in English, 8,923 characters of material against 0.
"""

import unittest

from content_studio.avatar import AVATAR_SECTIONS, AVATAR_SECTIONS_EN, excerpt, sections_of
from content_studio.harness.profile import category_for

RO = "\n\n".join(
    f"### {title}\n\n- o linie despre asta\n- încă una" for title in AVATAR_SECTIONS
)
EN = "\n\n".join(
    f"### {title}\n\n- one line about it\n- another one" for title in AVATAR_SECTIONS_EN
)


class TheAvatarBlock(unittest.TestCase):
    def test_both_languages_find_all_five(self) -> None:
        self.assertEqual(len(sections_of(RO)), 5)
        self.assertEqual(len(sections_of(EN)), 5)

    def test_the_two_lists_are_the_same_length(self) -> None:
        """Five archetypal sections; a language with four is a language with a
        silent hole in the prompt."""
        self.assertEqual(len(AVATAR_SECTIONS), len(AVATAR_SECTIONS_EN))

    def test_the_excerpt_is_not_empty_in_english(self) -> None:
        self.assertTrue(excerpt(EN).strip())
        self.assertIn("Her strongest fears", excerpt(EN))

    def test_a_profile_in_neither_language_still_returns_empty(self) -> None:
        """The old contract: a restructured profile must not stop a run."""
        self.assertEqual(sections_of("### Etwas ganz anderes\n\nText."), [])


class TheTabs(unittest.TestCase):
    #: (parent, romanian title, english title, expected group)
    PAIRS = (
        ("5. Master Business Brain", "Vocea ta", "Your voice", "voice"),
        ("5. Master Business Brain", "Tonul tău", "Your tone", "voice"),
        (
            "5. Master Business Brain",
            "Expresii pe care le folosești des",
            "Expressions you use often",
            "voice",
        ),
        (
            "5. Master Business Brain",
            "Povestea ta de început",
            "Your origin story",
            "voice",
        ),
        (
            "5. Master Business Brain",
            "Lucruri pe care nu le spui niciodată",
            "Things you never say",
            "restrictions",
        ),
        (
            "1. Brandul tău",
            "Servicii / produse principale",
            "Main services / products",
            "offer",
        ),
        ("2. Nișa ta", "Care este soluția ta?", "What is your solution?", "offer"),
        (
            "1. Brandul tău",
            "USP-ul tău (ce te face diferită)",
            "Your USP (what makes you different)",
            "offer",
        ),
        (
            "1. Brandul tău",
            "Rezultatul principal pe care îl oferi",
            "The main result you deliver",
            "results",
        ),
        (
            "5. Master Business Brain",
            "Rezultate cheie și dovezi",
            "Key results and proof",
            "results",
        ),
    )

    def test_each_heading_lands_in_the_same_tab_in_both_languages(self) -> None:
        for parent, ro, en, expected in self.PAIRS:
            with self.subTest(section=en):
                self.assertEqual(category_for(parent, ro), expected)
                self.assertEqual(category_for(parent, en), expected)

    def test_no_english_keyword_moves_a_romanian_heading(self) -> None:
        """The Romanian behaviour is exactly what it was; only additions were
        made. `usp` is the one token both languages share."""
        self.assertEqual(category_for("1. Brandul tău", "Valorile brandului"), "identity")
        self.assertEqual(category_for("1. Brandul tău", "Numele tău"), "identity")
        self.assertEqual(category_for("3. Audiența ta", "Platformele principale"), "ideal_client")

    def test_the_numbered_parents_still_win_where_they_did(self) -> None:
        self.assertEqual(category_for("6. CTA-uri", "orice"), "ctas")
        self.assertEqual(category_for("4. Rezultatele clientelor tale", "x"), "results")


if __name__ == "__main__":
    unittest.main()
