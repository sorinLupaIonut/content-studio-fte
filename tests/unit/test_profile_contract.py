"""Profile Markdown stays behind a structured browser contract."""

import unittest

from content_studio.harness.models import ProfileBlock
from content_studio.harness.profile import parse_profile, serialize_blocks

PROFILE = """# Profil

## 1. Brandul tău

### Vocea ta

> Cald și direct.

- Fără jargon
- Cu empatie

### Servicii

Coaching individual.
"""


class TestProfileContract(unittest.TestCase):
    def test_returns_subsections_without_markdown_markers(self) -> None:
        sections = parse_profile(PROFILE)
        self.assertEqual([section.title for section in sections], ["Vocea ta", "Servicii"])
        self.assertEqual(sections[0].group, "voice")
        self.assertEqual(sections[0].blocks[0].text, "Cald și direct.")
        self.assertEqual(sections[0].blocks[1].text, "Fără jargon")
        self.assertNotIn(">", sections[0].blocks[0].text)

    def test_serializes_structured_blocks_only_at_the_write_boundary(self) -> None:
        value = serialize_blocks(
            [
                ProfileBlock(kind="quote", text="Cald și direct."),
                ProfileBlock(kind="bullet", text="Fără jargon"),
            ]
        )
        self.assertEqual(value, "> Cald și direct.\n- Fără jargon")


if __name__ == "__main__":
    unittest.main()
