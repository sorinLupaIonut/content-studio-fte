"""Content Worker — one agent, skills in a sandbox, data over MCP.

**A single agent**, which reads its method from `SKILL.md` folders mounted into
a container.

What that buys:
  · real progressive disclosure, delivered by the platform rather than by tools
    of ours — the skill index (name + description + path) is always in context
    and costs little; the body is opened only when the task matches the
    description, and a `references/` file only if SKILL.md points there;
  · one context, so the profile and the rules are not copied into every agent's
    prompt;
  · the method lives in files you can edit without touching code, and it is the
    SAME file the model opens — no assembling step in between that could
    disagree with it.

What it costs, and you should know it:
  · a `SKILL.md` is text. It cannot enforce "exactly ten proposals with exactly
    five hooks" — it asks and hopes. The number is an instruction, not a contract,
    so it can come back with nine. It is counted afterwards, in
    `tests/checks/paid/full_flow.py`, and judged in the evals (Decision 10);
  · turns and a container. Measured 2026-08-27 on gpt-5-mini: eleven requests and
    87,302 input tokens for five hooks, against 26,250 and one request for the
    same work with the method preloaded. That trade was made deliberately —
    see `content_studio.sandbox`.

The agent has a shell, and it is the shell that opens the method. Nothing else
of this project is in the container: `content_studio.sandbox` mounts `skills/`
and nothing more, with no network, so `.env` sitting next to `skills/` on the
host is not reachable from in there.

Data is reached only through the `content-data` MCP server (rule 1), which runs
separately and is called by THIS process, never from inside the container.

Everything this file prints is Romanian, and so is the system prompt below: the
person on the other side is the client, and she works in Romanian.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from agents import ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp
from agents.sandbox import Manifest, SandboxAgent

from content_studio import enable_utf8_output
from content_studio.audit import (
    APPROVAL_GRANTED,
    APPROVAL_REJECTED,
    APPROVAL_REQUESTED,
)
from content_studio.config import (
    CLIENT_SLUG,
    MODEL,
    SKILLS_DIR,
    MissingConfig,
)
from content_studio.language import DEFAULT_LANGUAGE, Language, instruction_suffix
from content_studio.mcp_server.protocol import (
    profile_uri,
)
from content_studio.sandbox import SANDBOX_INSTRUCTIONS, capabilities

enable_utf8_output()

#: The tools that write under her name. Only these are gated; reads are free.
GATED_TOOLS = ("save_post", "save_posts_batch", "update_post", "update_profile")

# Who the assistant is and who it is talking to. Nothing about what it may write —
# the output contract lives in the skills and the generation schemas — and nothing
# about how the method is reached: that is the notes further down. Three jobs that
# used to share one string, and sharing it is how the tool list inside the rules
# drifted two tools out of date without anything failing.
BASE_INSTRUCTIONS = """\
Ești asistentul de conținut al Viorelei — life coach pentru femei care vor să iasă
din people pleasing, burnout și autosabotaj.

Răspunzi în română, cu diacritice, la persoana a II-a singular, simplu și cald,
fără termeni tehnici și fără jargon de marketing.

CU CINE VORBEȘTI. Vorbești cu Viorela — clienta, cea care comandă conținutul. NU
o strigi „Andreea". Andreea e avatarul, femeia de 25–45 de ani pentru care se
scriu postările; apare în conținut, niciodată în conversația cu Viorela.

Mesajele ei pot veni dictate, fără diacritice, cu greșeli de transcriere. Le
interpretezi cu bunăvoință, fără s-o corectezi. Răspunsul tău are diacritice.\
"""


#: How the method is reached. Telling a model it has something it does not have
#: is worse than saying nothing: it spends a turn discovering the lie and gets an
#: error back. This note and the tools attached below have to move together, and
#: this project has now been on both sides of that fault - a note saying "nu ai
#: fisiere" over skills that said "open references/...", and later a note naming
#: a reference tool that had been detached.
#:
#: THE SHAPE, since 2026-08-27: skills are real folders in a sandbox, indexed and
#: opened by the model itself. The index sentence is not written here - the SDK's
#: `Skills` capability renders name + description + path into the prompt, off the
#: frontmatter, so there is exactly one list and it cannot go stale. What is left
#: for us to say is the part the platform's English cannot: that calling the
#: skill is not optional.
#:
#: Romanian and untranslated, like everything the model reads.
def skill_method_note() -> str:
    """Say that the method is mandatory, and let the platform say where it is."""

    return (
        "Metoda ta stă în skill-uri, iar lista lor e mai jos, în acest prompt, cu"
        " numele și calea fiecăruia.\n\n"
        "APLICAREA METODEI ESTE OBLIGATORIE. Deschizi skill-ul potrivit ÎNAINTE de"
        " primul răspuns, îl citești întreg, ceri referințele pe care ți le cere"
        " el, și abia apoi scrii. Nu improvizezi fluxul din memorie și nu scrii"
        " nimic înainte de a-l fi citit."
    )


#: What the model may reach the data with, read off the server rather than typed
#: out. The sentence this replaces named five tools while seven were attached in
#: chat and three in generation - so the prompt promised `save_post` to an agent
#: that did not have it. A hand-written list of tools is a second source of truth
#: for something the code already knows; this asks the one that decides.
def data_tool_note(server: MCPServerStreamableHttp) -> str:
    """The data tools actually visible in this run, named."""

    allowed = (getattr(server, "tool_filter", None) or {}).get("allowed_tool_names")
    if not allowed:
        # No filter means the server decides; do not invent a list for it.
        return "La date ajungi NUMAI prin uneltele serverului de date, niciodată altfel."
    listed = ", ".join(f"`{name}`" for name in sorted(allowed))
    return (
        "La date ajungi NUMAI prin unelte, niciodată altfel. În această rulare ai"
        f" exact: {listed}. Dacă o unealtă nu e în listă, nu există acum:"
        " nu o chema și nu presupune că ai putea."
    )


#: The last conversation this client touched. Since Decision 11 the answer comes
#: from the SDK's own session table rather than from a cover sheet of our own —
#: see db/schema.sql for why the second copy had to go.
LAST_SESSION_SQL = """
SELECT session_id FROM public.agent_sessions
 WHERE session_id LIKE $1 ORDER BY updated_at DESC LIMIT 1
"""


def new_session_id() -> str:
    """A fresh conversation id. The slug prefix is what makes resume possible."""
    return f"{CLIENT_SLUG}-{date.today():%Y%m%d}-{uuid.uuid4().hex[:8]}"


async def open_session(engine, new: bool) -> str:
    """Pick the session: the last one the SDK wrote, or a fresh id.

    Nothing is inserted here any more. A conversation now exists because the SDK
    wrote a turn into `agent_sessions`, not because we announced it in advance —
    which also means a conversation that never got a message leaves no trace,
    instead of an empty row that looks like a lost session.

    `agent_sessions` is created by `SQLAlchemySession(create_tables=True)` later
    in `main`, so on a brand-new database it does not exist yet. That is not an
    error: it means there is nothing to resume.
    """
    if new:
        return new_session_id()

    async with engine.begin() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        if await raw.fetchval("SELECT to_regclass('public.agent_sessions')") is None:
            return new_session_id()
        session_id = await raw.fetchval(LAST_SESSION_SQL, f"{CLIENT_SLUG}-%")

    return session_id or new_session_id()


async def read_profile(
    data_mcp: MCPServerStreamableHttp,
    client_slug: str = CLIENT_SLUG,
) -> tuple[str, str]:
    """Return (name, profile_md) from the MCP resource, not via SQL from the worker.

    The client is a parameter with the configured default, so the CLI and every
    existing caller read Viorela exactly as before, while the harness can ask for
    the profile of whoever is signed in.
    """
    uri = profile_uri(client_slug)
    response = await data_mcp.read_resource(uri)
    texts = [
        content.text
        for content in getattr(response, "contents", [])
        if isinstance(getattr(content, "text", None), str)
    ]
    if not texts:
        raise RuntimeError(f"MCP resource {uri!r} returned no text.")
    try:
        payload = json.loads("".join(texts))
        name, profile_md = payload["name"], payload["profile_md"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise RuntimeError(f"MCP resource {uri!r} has an unexpected shape.") from e
    if not isinstance(name, str) or not isinstance(profile_md, str) or not profile_md.strip():
        raise RuntimeError(f"MCP resource {uri!r} holds no valid profile.")
    return name, profile_md


def build_worker(
    profile_md: str,
    data_mcp: MCPServerStreamableHttp,
    *,
    model: str | None = None,
    output_type: type[Any] | None = None,
    model_settings: ModelSettings | None = None,
    language: Language = DEFAULT_LANGUAGE,
) -> SandboxAgent:
    """The single agent. Method from files in a sandbox, data through MCP.

    A `SandboxAgent`, since 2026-08-27, and it needs a live sandbox at run time:
    every caller must pass `RunConfig(sandbox=...)`, which
    `content_studio.sandbox.sandbox_run_config` builds. Without one the run
    fails at `Runner.run` rather than quietly answering from memory - which is
    the right way round, because the failure mode of this shape is a model that
    never opens the method and writes something plausible instead.

    THREE THINGS ARE LOAD-BEARING HERE, and each of them fails silently:

    · `default_manifest` must exist. The runtime only processes the capabilities
      into a filesystem when a manifest is present; with none, the container
      comes up empty, the skills index never reaches the prompt, and the model
      answers from memory after running `find` over nothing.
    · `base_instructions` must be overridden. The SDK's default is Codex's
      16.9 KB coding-agent prompt, which tells the model to write preambles and
      to structure a final answer - the opposite of both `BASE_INSTRUCTIONS` and
      the generation schemas.
    · the capabilities are Shell and Skills only. `Capabilities.default()` would
      add `apply_patch`, which is a tool for editing the method the agent is
      supposed to be reading.

    Skills are folders on disk, discovered by themselves, named and described by
    their own frontmatter, and the description is still what decides whether the
    body is ever read. Rule 4, delivered by the platform rather than by tools of
    ours: `Skills.instructions` renders the index, the model opens `SKILL.md`
    with the shell, and the body sends it at a `references/` file by name.

    `language` changes only what comes out, never the method: the skills stay
    Romanian and an override block is appended. See `content_studio.language`.
    """
    # Identity, then the method, then the data. Each part written from what is
    # actually attached rather than from what was true when the string was last
    # edited - the fault this project has committed twice.
    tool_note = f"{skill_method_note()}\n\n{data_tool_note(data_mcp)}"
    return SandboxAgent(
        name="Content Worker",
        model=model or MODEL,
        instructions=(
            f"{BASE_INSTRUCTIONS}\n\n{tool_note}"
            f"\n\n--- PROFILUL CLIENTEI ---\n{profile_md}"
            # The language override goes last, after the profile, because it
            # has to contradict rule 1 above and the closer contradiction wins.
            f"{instruction_suffix(language)}"
        ),
        base_instructions=SANDBOX_INSTRUCTIONS,
        default_manifest=Manifest(),
        capabilities=capabilities(),
        mcp_servers=[data_mcp],
        output_type=output_type,
        model_settings=model_settings or ModelSettings(),
    )


#: `name` and `description` out of a SKILL.md frontmatter. Deliberately not a
#: YAML parser: the frontmatter this project writes is two keys, one of them a
#: folded block, and a dependency for that would be a dependency to keep.
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_FIELD = re.compile(r"^(name|description):[ \t]*(>-|>|\|)?[ \t]*(.*)$")


def _unquote(value: str) -> str:
    """Strip one pair of matching outer quotes, the way the SDK's parser does.

    It has to be the SAME rule, because two parsers read this frontmatter and
    only one of them writes the index the model sees. See `parse_skill`.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_skill(path: Path) -> tuple[str, str, str]:
    """(name, description, body) for one `SKILL.md`.

    The description is the one the model sees, so a skill with none is a skill
    that can never be chosen on purpose - it fails here rather than shipping a
    tool the model has no reason to call.

    TWO PARSERS READ THIS FILE AND THE OTHER ONE IS NOT OURS. The SDK's
    `Skills` capability builds the index from its own line-based reader
    (`agents/sandbox/capabilities/skills.py`, `_parse_frontmatter`), which does
    not understand YAML block scalars: given `description: >-` it takes the
    description to be the two characters `>-` and turns each wrapped line that
    happens to contain a colon into a key of its own. That is exactly what
    shipped between 2026-08-27 and the fix - both skills reached the model
    described as `>-`, so the first step of progressive disclosure, the one
    that decides whether the body is ever opened, was running blind.
    Discovered by assembling the prompt with `tests/checks/safe/show_agent_input.py`
    and reading it. The frontmatter is one quoted line now, which both readers
    agree on, and `test_skill_references.py` holds them to the same answer.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if match is None:
        raise MissingConfig(f"{path} nu are frontmatter")
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in match.group(1).splitlines():
        found = _FIELD.match(line)
        if found:
            current = found.group(1)
            fields[current] = [found.group(3)] if found.group(3) else []
        elif current and line.strip():
            fields[current].append(line.strip())
        elif not line.strip():
            current = None
    name = _unquote(" ".join(fields.get("name", [])).strip()) or path.parent.name
    description = _unquote(" ".join(fields.get("description", [])).strip())
    if not description:
        raise MissingConfig(f"{path} nu are description în frontmatter")
    return name, description, text[match.end() :].lstrip()


#: Every reference on disk, addressed as `<skill>/<file>.md`.
#:
#: A dict, and the lookup goes through it rather than joining the model's string
#: onto a path. `../../.env` is not a key, so the traversal a free-text filename
#: would otherwise invite never gets the chance to become a bug.
#:
#: Sorted, because these keys become an enum in the tool schema and the schema
#: sits in the cached prefix. An order that varied between processes would cost
#: a full prefix re-read on every request that landed on the other one.
def reference_index() -> dict[str, Path]:
    """`{"propune-postari/piloni.md": Path(...)}` for every reference file."""

    index: dict[str, Path] = {}
    for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        for path in sorted((folder / "references").glob("*.md")):
            index[f"{folder.name}/{path.name}"] = path
    return index


def describe_request(request) -> tuple[str, dict, str]:
    """(name, arguments, call id) out of an approval request."""
    raw = getattr(request, "raw_item", None)
    name = getattr(request, "tool_name", None) or getattr(raw, "name", "?")
    call_id = getattr(raw, "call_id", None) or getattr(raw, "id", None) or str(id(raw))
    arguments = getattr(raw, "arguments", None)
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {"raw": arguments}
    return name, arguments or {}, call_id


async def run_turn(worker, message, session, config, trail, run_id, approve):
    """One turn, with the approval gate on the way.

    When the agent wants to write, `Runner.run` stops and returns requests instead
    of an answer. We take them to the human, then resume the run from the same
    state — the model does not start over, it continues from where it was stopped.

    Here the state stays in this process's memory, which is fine: the person
    answering is sitting at the process. Over HTTP nobody is, so the harness
    parks the run instead — `Audit.suspend_run` / `pending_run` / `resume_run`,
    on the gate columns of `public.runs`. This function is the terminal's
    shortcut past all that, not a different design.
    """
    result = await Runner.run(worker, message, session=session, run_config=config)

    while result.interruptions:
        state = result.to_state()
        for request in result.interruptions:
            name, arguments, call_id = describe_request(request)
            await trail.event(run_id, APPROVAL_REQUESTED, name)

            approved, reason = await approve(name, arguments)
            if approved:
                state.approve(request)
                await trail.event(run_id, APPROVAL_GRANTED, name)
            else:
                state.reject(request, rejection_message=reason)
                await trail.event(run_id, APPROVAL_REJECTED, name)
                await trail.capability_blocked(run_id, name, call_id)

        result = await Runner.run(worker, state, session=session, run_config=config)

    return result

