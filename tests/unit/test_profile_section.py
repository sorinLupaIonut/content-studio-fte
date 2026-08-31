"""Section replacement is the one function that can damage the client's profile.

It is pure, so it is cheap to pin down: no database, no model, no network.
"""

import unittest

from content_studio.mcp_server.server import replace_section

PROFILE = """# Profil

## 1. Cine ești

Life coach.

## 6. Oferte și CTA ⚠️

Nimic încă.

## 7. Vocea ta

Caldă, directă.
"""


class TestReplaceSection(unittest.TestCase):
    def test_replaces_only_the_matched_section(self) -> None:
        result = replace_section(PROFILE, "Oferte", "Pachet 1:1, 6 sesiuni.")

        self.assertIn("Pachet 1:1, 6 sesiuni.", result)
        self.assertNotIn("Nimic încă.", result)
        self.assertIn("Life coach.", result)
        self.assertIn("Caldă, directă.", result)

    def test_keeps_the_heading_as_the_profile_wrote_it(self) -> None:
        result = replace_section(PROFILE, "oferte", "Text nou.")

        # Including the ⚠️ and the numbering the model did not send.
        self.assertIn("## 6. Oferte și CTA ⚠️", result)

    def test_the_last_section_can_be_replaced_too(self) -> None:
        result = replace_section(PROFILE, "Vocea", "Blândă.")

        self.assertIn("Blândă.", result)
        self.assertNotIn("Caldă, directă.", result)

    def test_an_unknown_section_raises_and_lists_the_real_ones(self) -> None:
        with self.assertRaises(ValueError) as caught:
            replace_section(PROFILE, "Tarife", "…")

        self.assertIn("Vocea ta", str(caught.exception))


#: The shape the CLIENT'S profile actually has: six numbered `##` parts with the
#: real sections as `###` inside them. The fixture above has no `###` at all,
#: which is exactly why nothing here failed while every save in the interface was
#: raising - `replace_section` matched `^##` only, and every editable card on the
#: page is a `###`. A test document that does not look like the real document is
#: a test that agrees with itself.
REAL_SHAPE = """# Profilul tău — Fundația

## 1. Brandul tău

Introducerea părții.

### Numele tău

Viorela Lupa

### Nișa ta

Life coaching.

## 2. Nișa ta — în detaliu

### Cine este clienta ideală?

Femei 25–45.
"""


class TestTheTwoHeadingLevels(unittest.TestCase):
    def test_a_subsection_can_be_replaced(self) -> None:
        result = replace_section(REAL_SHAPE, "Numele tău", "Viorela Lupa (nou)")

        self.assertIn("### Numele tău\n\nViorela Lupa (nou)", result)
        self.assertNotIn("\nViorela Lupa\n", result)
        # Its neighbours are untouched, above and below.
        self.assertIn("Introducerea părții.", result)
        self.assertIn("Life coaching.", result)
        self.assertIn("Femei 25–45.", result)

    def test_replacing_a_part_does_not_swallow_its_subsections(self) -> None:
        """A `##` body ends at the first `###` under it, not at the next `##`."""
        result = replace_section(REAL_SHAPE, "1. Brandul tău", "Altă introducere.")

        self.assertIn("Altă introducere.", result)
        self.assertNotIn("Introducerea părții.", result)
        self.assertIn("### Numele tău", result)
        self.assertIn("Viorela Lupa", result)

    def test_an_exact_title_beats_a_substring_elsewhere(self) -> None:
        """`Nișa ta` is a `###` and is also inside `## 2. Nișa ta — în detaliu`."""
        result = replace_section(REAL_SHAPE, "Nișa ta", "Altceva.")

        self.assertIn("### Nișa ta\n\nAltceva.", result)
        self.assertIn("## 2. Nișa ta — în detaliu", result)
        self.assertIn("Femei 25–45.", result)

    def test_the_harness_scaffolding_never_reaches_the_document(self) -> None:
        """The prompt wraps the exact text in `<profile-section>` tags so the
        model can see where it starts. The model copied them into the profile
        the first time a save ever got this far - the heading bug above had
        hidden it. A prompt asks; this makes sure."""
        result = replace_section(
            REAL_SHAPE,
            "Numele tău",
            "<profile-section>\nViorela Lupa\n</profile-section>",
        )

        self.assertNotIn("profile-section", result)
        self.assertIn("### Numele tău\n\nViorela Lupa\n", result)

    def test_the_error_lists_both_levels(self) -> None:
        with self.assertRaises(ValueError) as caught:
            replace_section(REAL_SHAPE, "Tarife", "…")

        message = str(caught.exception)
        self.assertIn("Numele tău", message)
        self.assertIn("1. Brandul tău", message)


if __name__ == "__main__":
    unittest.main()
