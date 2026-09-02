"""Free tests for the guard that decides a detail run developed the right idea.

The bug these close, seen once in production on 2026-08-31: the guard compared
the model's echo of the title with `!=`, so a Carusel whose title came back with
straight quotes instead of the Romanian pair was declared a different idea, and
five variants that were already written and paid for were thrown away.

The line these hold is not "be lenient". It is that the ORDINAL is the identity
and the title is an echo: punctuation may move, the idea may not.
"""

import unittest

from content_studio.harness.generator import same_title


class SameTitle(unittest.TestCase):
    def test_identical(self) -> None:
        self.assertTrue(same_title("Trei pași pentru un NU blând",
                                   "Trei pași pentru un NU blând"))

    def test_the_quotes_that_caused_it(self) -> None:
        """„…” re-typed as "…" — the exact shape of the production failure."""
        self.assertTrue(
            same_title(
                '"Ritualul de 60 de secunde: înainte să spui «da»"',
                "„Ritualul de 60 de secunde: înainte să spui «da»”",
            )
        )

    def test_a_title_that_is_itself_a_quotation(self) -> None:
        """The marks dropped, not swapped — 3 of the 4 real failures, all of it."""
        self.assertTrue(
            same_title(
                "Dacă mă schimb, mă vor respinge",
                "„Dacă mă schimb, mă vor respinge”",
            )
        )
        self.assertTrue(
            same_title(
                "Ritualul de 60 de secunde: înainte să spui «da»",
                "„Ritualul de 60 de secunde: înainte să spui «da»”",
            )
        )

    def test_dash_and_ellipsis(self) -> None:
        self.assertTrue(same_title("Trei pași — blând", "Trei pași - blând"))
        self.assertTrue(same_title("Și apoi…", "Și apoi..."))

    def test_whitespace_and_case(self) -> None:
        self.assertTrue(same_title("  Trei   pași  ", "trei pași"))

    def test_diacritics_are_not_punctuation(self) -> None:
        """`pasi` is not `pași`. Folding that would hide a model writing without them."""
        self.assertFalse(same_title("Trei pasi blanzi", "Trei pași blânzi"))

    def test_a_different_idea_is_still_refused(self) -> None:
        """The guard has to keep working, or relaxing it would have removed it."""
        self.assertFalse(
            same_title("Cinci mituri despre odihnă", "Trei pași pentru un NU blând")
        )

    def test_a_prefix_is_not_the_title(self) -> None:
        self.assertFalse(same_title("Trei pași", "Trei pași pentru un NU blând"))


if __name__ == "__main__":
    unittest.main()
