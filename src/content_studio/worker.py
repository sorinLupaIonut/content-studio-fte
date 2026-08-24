"""Content Worker — one agent, skills as tools, data over MCP.

**A single agent**, which loads its instructions from `SKILL.md` folders.

What that buys:
  · real progressive disclosure — the skill index (name + description + path) is
    always in context and costs little; the body opens only when the task matches
    the description, and `references/` only if SKILL.md points there;
  · one context, so the profile and the rules are not copied into every agent's
    prompt;
  · the method lives in files you can edit without touching code.

What it costs, and you should know it:
  · a `SKILL.md` is text. It cannot enforce "exactly ten proposals with exactly
    five hooks" — it asks and hopes. The number is an instruction, not a contract,
    so it can come back with nine. It is counted afterwards, in
    `tests/checks/full_flow.py`, and judged in the evals (Decision 10).

The agent has no shell and no filesystem. Each skill folder is a `FunctionTool`
named and described by its own frontmatter, and each `references/` file is fetched
by name through one more tool — see `skill_tools` and `reference_tool`. Nothing
from this project is reachable except what those two return, which is why `.env`
being next to `skills/` is not a problem any more.

Data is reached only through the `content-data` MCP server (rule 1), which runs
separately.

Everything this file prints is Romanian, and so is the system prompt below: the
person on the other side of the terminal is the client, and she works in Romanian.

Run it, in two terminals:
          uv run content-studio-server
          uv run content-studio          (resumes the last conversation)
          uv run content-studio --new    (starts a new one)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from agents import Agent, FunctionTool, ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp

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

enable_utf8_output()

#: The tools that write under her name. Only these are gated; reads are free.
GATED_TOOLS = ("save_post", "save_posts_batch", "update_post", "update_profile")

# Who the assistant is and who it is talking to. Nothing about what it may write:
# that is OUTPUT_RULES below, and nothing about how the method is reached: that is
# the notes further down. Three jobs that used to share one string, and sharing it
# is how the tool list inside the rules drifted two tools out of date without
# anything failing.
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

#: The output contract, cut out of BASE_INSTRUCTIONS on 2026-08-24 and NOT
#: ATTACHED ANYWHERE YET. Kept verbatim rather than deleted: `evals/cases.json`
#: asserts on rules 7, 8 and 10, and losing the text would lose the assertions'
#: subject. Where it goes next - back into the prompt, into the skills, or into a
#: reference - is the open decision this split exists to make possible.
OUTPUT_RULES = """\
REGULI OBLIGATORII — contractul de ieșire, nu preferințe de stil:

1. Vocea Viorelei, nu vocea unui robot. Tonul și expresiile din „Vocea ta",
   „Expresii pe care le folosești des" și „Tonul tău", din profil. Cald, blând,
   empatic, vulnerabil dar ferm, cu perspectivă creștină autentică.
   FĂRĂ empowerment agresiv. FĂRĂ jargon de marketing. FĂRĂ fraze generice de
   AI („în lumea agitată de azi", „haide să descoperim").
2. Respectă „Lucruri pe care nu le spui niciodată" din profil. Dacă tema cerută
   intră în conflict cu ele, NU generezi ce e afectat: spui care e conflictul și
   ceri decizia ei.
3. Specific, nu generic. Durerile, dorințele, fricile și credințele limitative
   REALE din profil. O postare bună pentru oricine e o postare bună pentru nimeni.
4. Conținutul se scrie CĂTRE Andreea, dar nu o strigi pe nume în text —
   „Andreea, știu cum te simți" sună a reclamă. Vorbești cu ea, nu despre ea.
5. Fiecare postare completă include: hook ales, script, caption, 3–5 hashtaguri,
   CTA din profil.
6. Dacă profilul are ⚠️ în ceva de care depinde sarcina, semnalezi scurt și
   generezi totuși ce se poate.
7. Testimonialele și cifrele se folosesc DOAR dacă există în profil. Nu inventezi
   niciodată rezultate, cifre sau dovezi — nici măcar prezentate ca experiență
   personală a ei. Dacă ți se cere o cifră care nu există, refuzi și propui
   altceva la persoana a II-a, fără cuantificări mascate precum „multe femei",
   „majoritatea” sau „din experiența mea”.
8. Sursa de inspirație rămâne în culise. Cartea, autorul, pagina sau linkul se
   notează DOAR pe câmpul `source` al postării salvate — NU în hook, în script sau
   în caption. E conținut de social media, nu lucrare cu bibliografie.
9. Întrebările se pun, răspunsurile nu se presupun. Dacă răspunde ambiguu sau
   sare peste una, reîntrebi. Nu alegi în locul ei și nu pornești „pe o variantă
   până răspunde". NU oferi variante implicite: fraza „dacă nu răspunzi, folosesc
   X" e interzisă — aștepți răspunsul, atât. Sursa o alege ea dintr-o listă
   închisă; n-o inventezi tu. După ce a ales-o, nu aduci material din alta.
10. Nimic nu se salvează fără confirmarea ei. Uneltele de scriere se cheamă doar
    după „da"-ul ei, niciodată din proprie inițiativă.

MODUL INTERNET — verificare obligatorie înainte de răspuns. Când sursa aleasă este
Internet sau Combinat cu Internet, folosești `search_web` înainte să scrii
propunerile. Din rezultat iei numai unghiuri; cifrele, studiile, citatele și
afirmațiile găsite pe web nu intră în postare ca fapte. Dacă unealta web dă
eroare, te oprești și spui asta; nu generezi din memorie și nu schimbi sursa fără
răspunsul ei.

Sunt permise întrebări de reflecție („ce observi?”, „ce ai putea refuza?”),
situații obișnuite și formulări de limite sprijinite de profil. Sunt interzise
afirmațiile generale de forma „X cauzează / previne / arată / înseamnă Y”,
listele de simptome sau „semne”, diagnosticele, recomandările medicale și reguli
inventate precum „50–50”. Un hook CIFRĂ poate număra întrebări, pași ori
formulări create de tine („3 întrebări”), dar nu oameni, rezultate, simptome,
efecte, procente, raporturi sau durate precum „48h” ori „în 2 minute”. Ca regulă
simplă, în modul Internet fiecare idee și hook este o întrebare, un îndemn către
ea sau descrierea formei postării — nu o propoziție declarativă care promite un
rezultat. Dacă un bloc nu trece verificarea, îl rescrii înainte să-l arăți.\
"""

#: The name the model calls. A constant because the note, the tool and every
#: SKILL.md have to agree on it, and a typo in one of them is a tool the model
#: asks for and never receives.
REFERENCE_TOOL_NAME = "citeste-referinta"


#: How the method is reached. Telling a model it has a shell it does not have is
#: worse than saying nothing: it spends a turn calling `exec_command` and gets an
#: error back.
#:
#: Measured on 2026-08-23, and the reason the shape changed: of 148 KB of skills
#: mounted into an E2B sandbox, a generation run opened exactly one file -
#: SKILL.md - and never touched `references/`. The sandbox charged 5,448 tokens of
#: instructions and tool schemas, plus a turn of flailing at a directory, to hand
#: over a file a single tool call can return. It was removed on 2026-08-24.
#:
#: Progressive disclosure survived it, and gained a third step: the skill's own
#: frontmatter description decides whether the body is ever paid for, and the
#: body decides whether a `references/` file is - see `reference_tool`.
#:
#: Romanian and untranslated, like everything the model reads.
def skill_tool_method_note(*, references: bool) -> str:
    """The method note for the tools shape, told the truth about what exists.

    Two versions, not one. This note is the only place the model learns which
    tools it has, and its first version said "nu ai fișiere" while every
    SKILL.md still told it to open `references/...`. A contradiction inside one
    context window, nothing logged, and 126 KB of method never read. Naming a
    reference tool that is not attached would be the same fault pointing the
    other way, so the sentence exists only when the tool does.
    """

    parts = [
        "Metoda ta stă în unelte, câte una pentru fiecare skill, numite exact ca el."
        " Chemi unealta potrivită și primești metoda întreagă."
    ]
    if references:
        parts.append(
            "Când corpul skill-ului te trimite la o referință, o ceri cu"
            f" `{REFERENCE_TOOL_NAME}`, cu numele exact pe care ți-l dă el."
            " Ceri numai referința de care ai nevoie, când ai nevoie de ea."
        )
    parts.append("Nu ai shell: nu deschizi fișiere singur și nu inventa unelte.")
    parts.append(
        "APLICAREA METODEI ESTE OBLIGATORIE. Chemi unealta ÎNAINTE de primul răspuns,"
        " citești ce întoarce și abia apoi scrii. Nu improvizezi fluxul din memorie."
    )
    return "\n\n".join(parts)


def preloaded_method_note(*, references: bool) -> str:
    """The method note for the shape where the method is already in the prompt.

    A second note rather than a flag inside the first one, for the same reason
    the first one has two versions: this is where the model learns which tools
    exist, and a sentence that describes a tool it does not have costs a turn to
    disprove. Here there is no skill tool at all, so nothing may say there is.
    """

    parts = [
        "Metoda ta e mai jos, în acest mesaj, întreagă - corpul ei și fiecare"
        " referință de care are nevoie. Nu o ceri și nu o cauți: o citești și o"
        " aplici, pas cu pas, în ordinea în care e scrisă."
    ]
    if references:
        parts.append(
            f"`{REFERENCE_TOOL_NAME}` rămâne pentru referințele care NU sunt mai"
            " jos - alea depind de ce te întreabă ea, nu de ce a ales în"
            " formular. Nu o chema pentru ceva ce ai deja."
        )
    parts.append("Nu ai shell: nu deschizi fișiere singur și nu inventa unelte.")
    parts.append(
        "APLICAREA METODEI ESTE OBLIGATORIE. Un pas sărit e metodă neaplicată,"
        " nu timp economisit."
    )
    return "\n\n".join(parts)


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
    method: str | None = None,
) -> Agent:
    """The single agent. Skills from `skills/`, data through MCP.

    One `FunctionTool` per skill folder, described by the skill's own frontmatter,
    plus one tool that returns a `references/` file by name. No shell, no
    `apply_patch`, no `view_image`, and none of the SDK's 3,472-token coding-agent
    prompt.

    Skills are still folders on disk, discovered by themselves, named and described
    by their own frontmatter, and the description is still what decides whether the
    body is ever loaded. That was the point of rule 4, and the delivery changing
    from a mounted folder to a tool did not cost it.

    `language` changes only what comes out, never the method: the skills stay
    Romanian and an override block is appended. See `content_studio.language`.

    `method`, when given, is the whole method already assembled - body plus the
    references this run was always going to need - and it changes three things
    together, which is why it is one parameter and not three. The skill tools
    come off (the body is already here, so a tool that returns it can only cost
    a turn), the note stops telling the model to call one, and the block goes
    into the prompt ahead of the profile so it lands in the cached prefix. The
    reference tool stays on: `content_studio.method` preloads only what the form
    determines, and the rest must still be reachable. See that module's header
    for why this path is not the same situation as chat.
    """
    # Built before the prompt, because the prompt has to describe the tools that
    # are actually attached. These lines are the whole fix: one place decides
    # whether the reference tool exists, and the note is written from that answer
    # rather than from what happened to be true when it was last edited.
    references = reference_tool()
    method_note = (
        preloaded_method_note(references=references is not None)
        if method is not None
        else skill_tool_method_note(references=references is not None)
    )
    # Identity, then the method, then the data, then the contract. Each part
    # written from what is actually attached rather than from what was true
    # when the string was last edited.
    tool_note = f"{method_note}\n\n{data_tool_note(data_mcp)}"
    common: dict[str, Any] = {
        "name": "Content Worker",
        "model": model or MODEL,
        "instructions": (
            f"{BASE_INSTRUCTIONS}\n\n{tool_note}"
            # Ahead of the profile, and never after the request: everything up to
            # the profile is identical for every idea in a batch, which is what
            # makes it one cached prefix read ten times instead of ten reads.
            f"{'' if method is None else chr(10) * 2 + method}"
            f"\n\n--- PROFILUL CLIENTEI ---\n{profile_md}"
            # The language override goes last, after the profile, because it
            # has to contradict rule 1 above and the closer contradiction wins.
            f"{instruction_suffix(language)}"
        ),
        "mcp_servers": [data_mcp],
        "output_type": output_type,
        "model_settings": model_settings or ModelSettings(),
    }
    # No skill tool when the body is already in the prompt. Leaving it attached
    # would offer the model a turn whose only possible result is a copy of what
    # it is already reading - and a model that is told to call its method first
    # will take that offer.
    tools = [] if method is not None else skill_tools()
    if references is not None:
        tools.append(references)
    return Agent(tools=tools, **common)


#: `name` and `description` out of a SKILL.md frontmatter. Deliberately not a
#: YAML parser: the frontmatter this project writes is two keys, one of them a
#: folded block, and a dependency for that would be a dependency to keep.
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_FIELD = re.compile(r"^(name|description):[ \t]*(>-|>|\|)?[ \t]*(.*)$")


def parse_skill(path: Path) -> tuple[str, str, str]:
    """(name, description, body) for one `SKILL.md`.

    The description is the one the model sees, so a skill with none is a skill
    that can never be chosen on purpose - it fails here rather than shipping a
    tool the model has no reason to call.
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
    name = " ".join(fields.get("name", [])).strip() or path.parent.name
    description = " ".join(fields.get("description", [])).strip()
    if not description:
        raise MissingConfig(f"{path} nu are description în frontmatter")
    return name, description, text[match.end() :].lstrip()


#: A tool takes no arguments: it returns one whole method, and there is nothing
#: to choose. Spelled out because strict mode rejects a bare `{}`.
_NO_ARGS = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def skill_tools() -> list[FunctionTool]:
    """One tool per skill folder, described by the skill's own frontmatter.

    This is what replaces the sandbox mount. The important part is not that it is
    cheaper - it is that progressive disclosure survives: the description is still
    what decides whether the body is ever paid for, and it still lives in the
    skill, so the method is still edited without touching code (rule 4).

    Read at build time, not at import: a skill edited on disk reaches the next
    conversation without a restart, exactly as the mounted folder did.
    """
    tools: list[FunctionTool] = []
    for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            continue
        name, description, body = parse_skill(skill_md)

        async def invoke(_ctx: Any, _args: str, body: str = body) -> str:
            return body

        tools.append(
            FunctionTool(
                name=name,
                description=description,
                params_json_schema=_NO_ARGS,
                on_invoke_tool=invoke,
            )
        )
    if not tools:
        raise MissingConfig(f"Niciun skill în {SKILLS_DIR}")
    return tools


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


#: What the model reads before deciding to spend a turn on a reference. It says
#: "only when the skill sends you", because the skill body is the index: the
#: schema knows the names, and only SKILL.md knows what each one is for.
REFERENCE_TOOL_DESCRIPTION = """
Întoarce, întreg, un fișier de referință al metodei — detaliul pe care corpul
unui skill îl are doar ca trimitere. Îl chemi numai când skill-ul te trimite
explicit acolo, cu numele exact pe care ți-l dă, și ceri numai fișierul de care
ai nevoie: sunt materiale lungi, se citesc pe rând, nu toate.
""".strip()


def reference_tool() -> FunctionTool | None:
    """The one tool that opens a `references/` file. None when there are none.

    This is the third step of progressive disclosure, and the step the sandbox
    used to serve with a shell: the description decides whether the skill body
    is loaded, the body decides whether a reference is. Nothing is in context
    until something upstream asked for it by name.

    None rather than an empty enum: strict mode cannot spell "a string from
    nowhere", and a tool that can never succeed spends schema tokens on every
    request to teach the model a dead end. `build_worker` drops the sentence
    about it from the system prompt in the same breath.

    The file is read when the tool is CALLED, not when it is built, so a
    reference edited on disk reaches the next call - the same contract the
    mounted folder had, one level further in.
    """

    index = reference_index()
    if not index:
        return None
    schema = {
        "type": "object",
        "properties": {
            "fisier": {
                "type": "string",
                "description": "Numele referinței, exact cum îl scrie skill-ul.",
                "enum": sorted(index),
            }
        },
        "required": ["fisier"],
        "additionalProperties": False,
    }

    async def invoke(_ctx: Any, args: str) -> str:
        # The enum makes an unknown name a schema violation, so this guard is
        # for the model that answers around its own schema, and for the file
        # deleted between build and call. It returns the refusal as a result
        # rather than raising: a raise ends the run, and a detail run is one of
        # ten that were meant to come back together.
        try:
            name = json.loads(args or "{}").get("fisier", "")
        except json.JSONDecodeError:
            name = ""
        path = index.get(name)
        if path is None or not path.is_file():
            return f"Nu există referința {name!r}. Alege una din lista uneltei."
        return path.read_text(encoding="utf-8")

    return FunctionTool(
        name=REFERENCE_TOOL_NAME,
        description=REFERENCE_TOOL_DESCRIPTION,
        params_json_schema=schema,
        on_invoke_tool=invoke,
    )


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

