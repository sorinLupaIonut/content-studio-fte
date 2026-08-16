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


if __name__ == "__main__":
    unittest.main()
