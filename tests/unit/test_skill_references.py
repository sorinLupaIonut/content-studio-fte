"""The reference tool: the third step of progressive disclosure.

The fault these tests exist for is not a crash. It is a system prompt that
described tools the agent did not have: it said "nu ai fișiere: nu încerca să
deschizi nimic" while every SKILL.md still told the model to open
`references/...`. Nothing failed, nothing logged, and 126 KB of method was
simply never read. So what is asserted here is agreement between three things
that can drift apart silently - the note, the attached tools, and the files on
disk.
"""

import asyncio
import importlib.util
import json
import re
import unittest
from pathlib import Path

from agents.mcp import MCPServerStreamableHttp

from content_studio.config import SKILLS_DIR
from content_studio.worker import (
    REFERENCE_TOOL_NAME,
    build_worker,
    reference_index,
    reference_tool,
    skill_tools,
)


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


def call(tool, payload: str) -> str:
    """Invoke a FunctionTool the way the SDK does, with a JSON argument string."""

    return asyncio.run(tool.on_invoke_tool(None, payload))


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


class TestReferenceTool(unittest.TestCase):
    def setUp(self):
        self.tool = reference_tool()
        self.assertIsNotNone(self.tool, "no reference tool built from skills/")

    def test_it_is_named_the_way_the_prompt_names_it(self):
        self.assertEqual(self.tool.name, REFERENCE_TOOL_NAME)

    def test_the_enum_is_exactly_what_is_on_disk(self):
        enum = self.tool.params_json_schema["properties"]["fisier"]["enum"]
        self.assertEqual(enum, sorted(reference_index()))

    def test_it_returns_the_file_whole(self):
        name = "propune-postari/piloni.md"
        self.assertIn(name, reference_index())
        body = call(self.tool, json.dumps({"fisier": name}))
        self.assertEqual(body, reference_index()[name].read_text(encoding="utf-8"))

    def test_an_unknown_name_is_refused_and_does_not_end_the_run(self):
        # A raise here would kill a detail run that has nine siblings.
        answer = call(self.tool, json.dumps({"fisier": "nu-exista.md"}))
        self.assertIn("Nu există", answer)

    def test_a_traversal_is_not_a_key(self):
        answer = call(self.tool, json.dumps({"fisier": "../../.env"}))
        self.assertIn("Nu există", answer)

    def test_broken_arguments_are_refused_rather_than_raised(self):
        self.assertIn("Nu există", call(self.tool, "not json"))
        self.assertIn("Nu există", call(self.tool, ""))


class TestThePromptDescribesTheToolsThatExist(unittest.TestCase):
    """The regression itself: note and tools, agreeing."""

    @staticmethod
    def _stub_mcp() -> MCPServerStreamableHttp:
        # Never connected; build_worker only needs the object to hold onto.
        return MCPServerStreamableHttp(params={"url": "http://localhost:1/mcp"})

    def setUp(self):
        self.agent = build_worker("PROFILUL", self._stub_mcp())
        self.names = {tool.name for tool in self.agent.tools}

    def test_the_reference_tool_is_attached_next_to_the_skills(self):
        self.assertIn(REFERENCE_TOOL_NAME, self.names)
        for tool in skill_tools():
            self.assertIn(tool.name, self.names)

    def test_the_prompt_names_it(self):
        self.assertIn(REFERENCE_TOOL_NAME, self.agent.instructions)

    def test_the_prompt_no_longer_denies_having_files(self):
        # The exact sentence that contradicted every SKILL.md.
        self.assertNotIn("nu ai\nfișiere", self.agent.instructions)
        self.assertNotIn("nu ai fișiere", self.agent.instructions)

    def test_it_still_says_there_is_no_shell(self):
        # Removing the contradiction must not invite `exec_command` back.
        self.assertIn("Nu ai shell", self.agent.instructions)


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

    def test_the_names_it_declares_are_the_names_the_tool_accepts(self):
        enum = reference_tool().params_json_schema["properties"]["fisier"]["enum"]
        for entry in self.entries:
            self.assertIn(entry["file"], enum)

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


class TestEveryMentionIsCallable(unittest.TestCase):
    """A pointer to a reference has to be a call the tool would accept.

    Found by hand on 2026-08-24, in `surse.md`: it told the model to take the
    book titles from `references/carti.md` - the sandbox path, from when a shell
    opened files. That is not a key the tool accepts, so the call would come back
    "Nu există referința" and the model would carry on without the list. The
    SKILL.md bodies were rewritten and checked; the reference files pointing at
    EACH OTHER were not, and nothing would have said so.
    """

    #: `citeste-referinta("propune-postari/carti.md")`, however it is wrapped.
    CALL = re.compile(r'citeste-referinta\(\s*["\']([^"\']+)["\']\s*\)')

    def documents(self):
        """Every file the model can be handed: skill bodies and references."""

        for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
            skill_md = folder / "SKILL.md"
            if skill_md.is_file():
                yield skill_md
            yield from sorted((folder / "references").glob("*.md"))

    def test_every_call_names_a_reference_that_exists(self):
        index = reference_index()
        for path in self.documents():
            for name in self.CALL.findall(path.read_text(encoding="utf-8")):
                self.assertIn(name, index, f"{path.name} asks for {name!r}")

    def test_no_document_still_points_at_a_sandbox_path(self):
        # The bare filename is what makes this a pointer rather than prose: it
        # is the name of a file that really exists under some skill.
        filenames = {key.split("/", 1)[1] for key in reference_index()}
        stale = re.compile(r"references[/\\](" + "|".join(map(re.escape, filenames)) + r")")
        for path in self.documents():
            found = stale.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(found, [], f"{path.name} points at references/{found}")

    def test_a_bare_filename_is_never_offered_as_the_name_to_ask_for(self):
        """`filmare.md` is not a key; `dezvolta-postarea/filmare.md` is.

        The system prompt tells the model to ask "cu numele exact pe care ți-l dă"
        the skill body. A body that prints the bare filename is therefore handing
        it a name the tool refuses - and this very file shipped that way for a few
        minutes, in the one section listing the references it should ask for only
        when she brings the subject up.
        """
        filenames = {key.split("/", 1)[1] for key in reference_index()}
        quoted = re.compile(r"`([^`\n]+\.md)`")
        for path in self.documents():
            for mention in quoted.findall(path.read_text(encoding="utf-8")):
                if mention.split("/")[-1] not in filenames:
                    continue  # some other .md, not one of ours
                self.assertIn(mention, reference_index(), f"{path.name}: `{mention}`")
