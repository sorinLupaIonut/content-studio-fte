"""References: the third step of progressive disclosure, and whether it can fire.

The fault these tests exist for is not a crash. It is a prompt that describes a
way of reaching the method which does not match the way the method is actually
reachable. This project has shipped that fault twice, in both directions: a
prompt saying "nu ai fisiere" over skills that said "open `references/...`",
and later skill bodies calling `citeste-referinta(...)` after that tool had been
detached. Nothing failed, nothing logged, and the method was simply not read.

Since 2026-08-27 the method is files in a sandbox, opened by the model with the
shell. So the agreement that has to hold is between the files on disk, the
pointers the skill bodies write, and the manifest that says when each one should
fire. There is no tool of ours in that chain any more, which is the point.
"""

import importlib.util
import re
import unittest
from pathlib import Path

from agents.mcp import MCPServerStreamableHttp

from content_studio.config import SKILLS_DIR
from content_studio.sandbox import SANDBOX_INSTRUCTIONS, SKILLS_PATH, sandbox_manifest
from content_studio.worker import build_worker, parse_skill, reference_index


def load_audit():
    """`evals/references.py` by path - `evals/` is a folder of scripts, not a package."""

    path = Path(__file__).resolve().parents[2] / "evals" / "references.py"
    spec = importlib.util.spec_from_file_location("evals_references", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = load_audit()
manifest = AUDIT.manifest
named_in_skill = AUDIT.named_in_skill


class TestReferenceIndex(unittest.TestCase):
    def test_it_finds_every_reference_on_disk(self):
        index = reference_index()
        on_disk = {
            f"{folder.name}/{path.name}"
            for folder in SKILLS_DIR.iterdir()
            if folder.is_dir()
            for path in (folder / "references").glob("*.md")
        }
        self.assertEqual(set(index), on_disk)
        self.assertTrue(on_disk, "no references on disk - the fixture is gone")

    def test_keys_carry_the_skill_so_two_skills_can_share_a_filename(self):
        for key in reference_index():
            self.assertIn("/", key)

    def test_the_order_is_stable(self):
        # The keys become an enum in the cached prefix. An order that varied
        # between processes would invalidate it on every request.
        self.assertEqual(list(reference_index()), sorted(reference_index()))


class TestTheSandboxCarriesTheMethod(unittest.TestCase):
    """The manifest is what puts `skills/` inside the container.

    And its absence is silent: with no manifest the runtime never runs the
    capabilities, the container comes up empty, the skills index never reaches
    the prompt, and the model answers from memory after running `find` over
    nothing. That happened on the first spike of 2026-08-27 and raised nothing.
    """

    def test_the_skills_root_is_mounted(self):
        keys = {str(key) for key in sandbox_manifest().entries}
        self.assertIn(SKILLS_PATH, keys)

    def test_every_skill_has_the_frontmatter_the_index_is_built_from(self):
        # Not asserting the SDK's wording - asserting that what it renders the
        # index from is the skill's own frontmatter, which is rule 4.
        found = 0
        for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
            skill_md = folder / "SKILL.md"
            if not skill_md.is_file():
                continue
            name, description, _ = parse_skill(skill_md)
            self.assertTrue(name.strip(), folder.name)
            self.assertTrue(description.strip(), folder.name)
            found += 1
        self.assertTrue(found, "no skills on disk - the fixture is gone")


class TestThePromptDescribesTheMethodThatExists(unittest.TestCase):
    """The regression itself: what the prompt says, and what is actually there."""

    @staticmethod
    def _stub_mcp() -> MCPServerStreamableHttp:
        # Never connected; build_worker only needs the object to hold onto.
        return MCPServerStreamableHttp(params={"url": "http://localhost:1/mcp"})

    def setUp(self):
        self.agent = build_worker("PROFILUL", self._stub_mcp())

    def test_it_brings_no_tools_of_its_own(self):
        # The skill tools and `citeste-referinta` are gone. Anything left here
        # would be a second way to reach the method, which is the drift.
        self.assertEqual(self.agent.tools, [])

    def test_it_carries_a_manifest_so_the_skills_are_mounted(self):
        self.assertIsNotNone(self.agent.default_manifest)

    def test_it_replaces_the_sdk_coding_agent_prompt(self):
        # The default is Codex's 16.9 KB prompt, which tells the model to write
        # preambles and to structure a final answer - the opposite of both
        # BASE_INSTRUCTIONS and the generation schemas.
        self.assertEqual(self.agent.base_instructions, SANDBOX_INSTRUCTIONS)

    def test_the_capabilities_are_shell_and_skills_only(self):
        kinds = {capability.type for capability in self.agent.capabilities}
        self.assertEqual(kinds, {"shell", "skills"})

    def test_it_no_longer_names_a_tool_of_ours(self):
        self.assertNotIn("citeste-referinta", self.agent.instructions)

    def test_it_no_longer_denies_having_files_or_a_shell(self):
        # Both sentences were true once and are contradictions now.
        self.assertNotIn("nu ai fișiere", self.agent.instructions)
        self.assertNotIn("Nu ai shell", self.agent.instructions)

    def test_it_still_says_the_method_is_mandatory(self):
        self.assertIn("APLICAREA METODEI ESTE OBLIGATORIE", self.agent.instructions)


class TestTheManifestMatchesDisk(unittest.TestCase):
    """`evals/references.json` says when each reference should fire.

    A manifest nobody checks is the same failure one level up: it would keep
    declaring a trigger for a file that was renamed, and keep silent about one
    that was added. Either way the audit reports success over a hole.
    """

    STATES = {"required", "forbidden", "optional"}
    SCENARIOS = {
        "titluri",
        "detalii-reel",
        "detalii-carusel",
        "detalii-stories",
        "chat-faza1",
        "chat-productie",
    }

    def setUp(self):
        self.entries = manifest()

    def test_every_reference_on_disk_has_a_declared_trigger(self):
        self.assertEqual({e["file"] for e in self.entries}, set(reference_index()))

    def test_the_names_it_declares_are_files_that_exist(self):
        for entry in self.entries:
            self.assertIn(entry["file"], reference_index())

    def test_every_entry_says_when_in_romanian_prose(self):
        for entry in self.entries:
            self.assertTrue(entry.get("when", "").strip(), entry["file"])

    def test_states_and_scenarios_are_from_the_documented_sets(self):
        for entry in self.entries:
            for scenario, state in entry.get("expect", {}).items():
                self.assertIn(scenario, self.SCENARIOS, entry["file"])
                self.assertIn(state, self.STATES, entry["file"])

    def test_named_in_skill_agrees_with_the_skill_bodies(self):
        # The audit's own claim, checked against the files rather than trusted.
        pointed = {e["file"] for e in self.entries if named_in_skill(e["file"])}
        expected = set()
        for name in reference_index():
            skill, _, filename = name.partition("/")
            body = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
            if filename in body:
                expected.add(name)
        self.assertEqual(pointed, expected)


class TestEveryMentionIsOpenable(unittest.TestCase):
    """A pointer to a reference has to be a path the model can actually open.

    THIS TEST INVERTED ON 2026-08-27, and the inversion is the whole story. It
    used to assert that no document wrote `references/<file>` - because back
    then that was the stale sandbox path, left over from when a shell opened
    files, while the live shape was `citeste-referinta("skill/file.md")`. The
    method is files in a sandbox again, so `references/<file>` is once more the
    correct form and the tool-call form is the stale one.

    What did NOT change is why it exists: found by hand on 2026-08-24 in
    `surse.md`, which pointed the model at a name nothing would accept. The call
    came back empty and the model carried on without the list - no error, no
    log. The skill bodies had been rewritten and checked; the reference files
    pointing at EACH OTHER had not.
    """

    #: `references/structura-reel.md`, wherever it appears - fenced, inline or
    #: in prose. The `references/` prefix is what makes it a pointer.
    POINTER = re.compile(r"references/([\w.-]+\.md)")

    #: The tool that used to serve them. Any survivor is an instruction to call
    #: something that is not attached.
    STALE_TOOL = re.compile(r"citeste-referinta\s*\(")

    def documents(self):
        """Every file the model can be handed: skill bodies and references."""

        for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
            skill_md = folder / "SKILL.md"
            if skill_md.is_file():
                yield folder.name, skill_md
            for path in sorted((folder / "references").glob("*.md")):
                yield folder.name, path

    def test_every_pointer_names_a_file_in_the_same_skill(self):
        """`references/x.md` is resolved next to the document that wrote it.

        Relative, not absolute, because that is what it means inside the
        container: the skill is one directory, and `references/` is its own
        subfolder. A body pointing at another skill's reference would resolve
        to nothing there, and read perfectly well here.
        """
        index = reference_index()
        for skill, path in self.documents():
            for filename in self.POINTER.findall(path.read_text(encoding="utf-8")):
                self.assertIn(f"{skill}/{filename}", index, f"{path.name} -> {filename}")

    def test_no_document_still_calls_the_tool_that_is_gone(self):
        for _, path in self.documents():
            found = self.STALE_TOOL.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(found, [], f"{path.name} still calls citeste-referinta")

    def test_a_reference_is_never_named_without_its_folder(self):
        """`structura-reel.md` on its own is not a path; `references/...` is.

        A body that prints the bare filename is handing the model something it
        has to guess the location of, and a guess that lands wrong is a file
        silently not read - which is the failure this whole module is about.
        """
        filenames = {key.split("/", 1)[1] for key in reference_index()}
        quoted = re.compile(r"`([^`\n]+\.md)`")
        for _, path in self.documents():
            for mention in quoted.findall(path.read_text(encoding="utf-8")):
                if mention.split("/")[-1] not in filenames:
                    continue  # some other .md, not one of ours
                self.assertTrue(
                    mention.startswith("references/"),
                    f"{path.name}: `{mention}` is not a path the model can open",
                )
