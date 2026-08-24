"""What gets preloaded, and that the prompt never contradicts itself.

`content_studio.method` assembles the method ahead of the call for the
structured generation path, where the form has already answered every question
the skill body branches on. The risk it carries is not token count - it is a
body that says "cere structura-reel.md" sitting directly above the contents of
`structura-reel.md`. That is the same fault that left 126 KB of method unread
once already, pointing the other way: a model told to fetch what it has been
given spends a turn proving it already has it.
"""

from __future__ import annotations

import unittest

from content_studio import method as M
from content_studio.harness.generation import FormatChoice, SourceChoice
from content_studio.worker import reference_index

FORMATS = ("Reel", "Carusel", "Stories")
SOURCES = ("Cărți", "Internet", "Memorie", "Combinat")
SKILLS = ("propune-postari", "dezvolta-postarea")


class TestPreloadKeys(unittest.TestCase):
    def test_every_key_in_the_tables_exists_on_disk(self) -> None:
        # A key that does not exist is silently dropped by `method_block`, so
        # the failure would be a reference quietly missing from every prompt.
        index = reference_index()
        for table in (M.ALWAYS, M.BY_FORMAT, M.BY_SOURCE):
            for skill, value in table.items():
                groups = [value] if isinstance(value, tuple) else list(value.values())
                for group in groups:
                    for key in group:
                        self.assertIn(key, index, f"{skill}: {key}")

    def test_every_shape_the_form_can_produce_is_covered(self) -> None:
        # The tables are keyed by literal strings; a format or source added to
        # the contract and forgotten here would fall through to an empty tuple
        # and generate without its method.
        self.assertEqual(set(FORMATS), set(FormatChoice.__args__))
        self.assertEqual(set(SOURCES), set(SourceChoice.__args__))
        for skill in SKILLS:
            self.assertEqual(set(M.BY_FORMAT[skill]), set(FORMATS))
            self.assertEqual(set(M.BY_SOURCE[skill]), set(SOURCES))

    def test_reel_carries_its_three_writing_references(self) -> None:
        keys = M.preload_keys("dezvolta-postarea", "Reel", "Memorie")
        for name in ("structura-reel", "hookuri-si-scripturi", "b-roll"):
            self.assertIn(f"dezvolta-postarea/{name}.md", keys)

    def test_stories_gets_stories_and_reel_does_not(self) -> None:
        stories = M.preload_keys("dezvolta-postarea", "Stories", "Memorie")
        reel = M.preload_keys("dezvolta-postarea", "Reel", "Memorie")
        self.assertIn("dezvolta-postarea/stories.md", stories)
        self.assertNotIn("dezvolta-postarea/stories.md", reel)

    def test_books_add_the_shelf_only_in_phase_one(self) -> None:
        # Faza 2 reaches the shelf through `search_books` and never names
        # `carti.md`; preloading it there would be tokens with no instruction.
        self.assertIn(
            "propune-postari/carti.md",
            M.preload_keys("propune-postari", "Reel", "Cărți"),
        )
        self.assertNotIn(
            "propune-postari/carti.md",
            M.preload_keys("propune-postari", "Reel", "Memorie"),
        )
        self.assertNotIn(
            "propune-postari/carti.md",
            M.preload_keys("dezvolta-postarea", "Reel", "Cărți"),
        )

    def test_production_references_are_never_preloaded(self) -> None:
        # These depend on what she asks in conversation, not on the form, and
        # they are long. Measured across two batches: zero calls in structured
        # generation.
        never = {
            "dezvolta-postarea/filmare.md",
            "dezvolta-postarea/editare.md",
            "dezvolta-postarea/distribuire.md",
            "dezvolta-postarea/intrebari-frecvente.md",
            "dezvolta-postarea/tipuri-de-reels.md",
        }
        for skill in SKILLS:
            for fmt in FORMATS:
                for source in SOURCES:
                    keys = set(M.preload_keys(skill, fmt, source))
                    self.assertEqual(keys & never, set(), f"{skill} {fmt} {source}")

    def test_keys_are_unique_and_ordered_stably(self) -> None:
        # These land in the cached prefix. An order that varied between
        # processes would buy a full prefix re-read on every request that
        # happened to land on the other one.
        for skill in SKILLS:
            for fmt in FORMATS:
                for source in SOURCES:
                    keys = M.preload_keys(skill, fmt, source)
                    self.assertEqual(len(keys), len(set(keys)))
                    self.assertEqual(keys, M.preload_keys(skill, fmt, source))


class TestMethodBlock(unittest.TestCase):
    def test_no_call_block_survives_for_a_preloaded_reference(self) -> None:
        # THE POINT OF THE MODULE. A block still telling the model to fetch a
        # file it is already reading costs a turn to disprove.
        for skill in SKILLS:
            for fmt in FORMATS:
                for source in SOURCES:
                    text, keys = M.method_block(skill, fmt, source)
                    asked = {m.group("key") for m in M.CALL_BLOCK.finditer(text)}
                    self.assertEqual(
                        asked & set(keys), set(), f"{skill} {fmt} {source}"
                    )

    def test_each_preloaded_reference_is_present_whole(self) -> None:
        index = reference_index()
        text, keys = M.method_block("dezvolta-postarea", "Reel", "Memorie")
        for key in keys:
            self.assertIn(f"--- REFERINȚA {key} ---", text)
            body = index[key].read_text(encoding="utf-8")
            # A distinctive slice rather than the whole file: whitespace at the
            # joins is not the contract, the content is.
            self.assertIn(body.strip()[:200], text)

    def test_the_block_says_not_to_ask(self) -> None:
        text, _ = M.method_block("dezvolta-postarea", "Reel", "Memorie")
        self.assertIn("Nu ceri niciuna dintre ele", text)

    def test_a_skill_with_no_matching_reference_still_builds(self) -> None:
        # Carusel has no method file, deliberately. It must not produce an empty
        # or broken block.
        text, keys = M.method_block("dezvolta-postarea", "Carusel", "Memorie")
        self.assertTrue(text.strip())
        self.assertIn("METODA TA, ÎNTREAGĂ", text)
        self.assertNotIn("dezvolta-postarea/structura-reel.md", keys)


if __name__ == "__main__":
    unittest.main()
