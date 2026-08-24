"""Content Worker — one agent in a sandbox, skills on disk, data over MCP.

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

What is NOT mounted into the sandbox: anything from this project except `skills/`.
`.env` holds the Neon password and the agent has a shell — so it has no business
being in there.

The sandbox is E2B: needs `E2B_API_KEY` in `.env`, free Hobby tier.

Data is reached only through the `content-data` MCP server (rule 1), which runs
separately. The sandbox has nothing to do with it: MCP tools are called from this
process, not from inside the sandbox.

Everything this file prints is Romanian, and so is the system prompt below: the
person on the other side of the terminal is the client, and she works in Romanian.

Run it, in two terminals:
          uv run content-studio-server
          uv run content-studio          (resumes the last conversation)
          uv run content-studio --new    (starts a new one)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from agents import Agent, FunctionTool, ModelSettings, Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.extensions.sandbox.e2b import E2BSandboxClient, E2BSandboxClientOptions
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig
from agents.sandbox import SandboxAgent
from agents.sandbox.capabilities import Capabilities
from agents.sandbox.capabilities.skills import Skills
from agents.sandbox.entries import LocalDir
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import (
    APPROVAL_GRANTED,
    APPROVAL_REJECTED,
    APPROVAL_REQUESTED,
    Audit,
)
from content_studio.config import (
    CLIENT_SLUG,
    MCP_TIMEOUT,
    MCP_URL,
    MODEL,
    SKILLS_DIR,
    USE_SANDBOX,
    MissingConfig,
    database_url,
    describe_database,
)
from content_studio.language import DEFAULT_LANGUAGE, Language, instruction_suffix
from content_studio.mcp_server.protocol import (
    CONVERSATION_HEADER,
    MODEL_VISIBLE_TOOLS,
    profile_uri,
)

enable_utf8_output()

#: The tools that write under her name. Only these are gated; reads are free.
GATED_TOOLS = ("save_post", "save_posts_batch", "update_post", "update_profile")

# The rules live in the system prompt rather than in a skill, because they are
# always in force. Progressive disclosure is for what is needed sometimes — the
# method, the pillars, the hook types. An output contract that loads "when needed"
# is a contract the model may not read exactly when it is breaking it.
BASE_INSTRUCTIONS = """\
Ești asistentul de conținut al Viorelei — life coach pentru femei care vor să iasă
din people pleasing, burnout și autosabotaj.

Răspunzi în română, cu diacritice, la persoana a II-a singular, simplu și cald,
fără termeni tehnici și fără jargon de marketing.

CU CINE VORBEȘTI. Vorbești cu Viorela — clienta, cea care comandă conținutul. NU
o strigi „Andreea". Andreea e avatarul, femeia de 25–45 de ani pentru care se
scriu postările; apare în conținut, niciodată în conversația cu Viorela.

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
10. Nimic nu se salvează fără confirmarea ei.

Mesajele ei pot veni dictate, fără diacritice, cu greșeli de transcriere. Le
interpretezi cu bunăvoință, fără s-o corectezi. Răspunsul tău are diacritice.

UNDE EȘTI ACUM — Deciziile 0–10. Ai skill-urile `propune-postari` și
`dezvolta-postarea`, și cinci unelte: `search_books`, `search_web`,
`list_posts`, `save_post`, `update_profile`. Când sursa aleasă este
Internet sau Combinat cu Internet, folosești `search_web` înainte să
scrii propunerile. Din rezultat iei numai unghiuri; cifrele, studiile, citatele
și afirmațiile găsite pe web nu intră în postare ca fapte. Unghiul poate decide
despre ce vorbești, dar conținutul concret se sprijină numai pe profilul aflat
deja în context și pe exemple obișnuite formulate ca posibilități, nu ca adevăruri
generale, cauze sau sfaturi medicale. Dacă unealta web dă eroare, te oprești și
spui asta; nu generezi din memorie și nu schimbi sursa fără răspunsul ei.

MODUL INTERNET — verificare obligatorie înainte de răspuns. Sunt permise
întrebări de reflecție („ce observi?”, „ce ai putea refuza?”), situații obișnuite
și formulări de limite sprijinite de profil. Sunt interzise afirmațiile generale
de forma „X cauzează / previne / arată / înseamnă Y”, listele de simptome sau
„semne”, diagnosticele, recomandările medicale și reguli inventate precum
„50–50”. Un hook CIFRĂ poate număra întrebări, pași ori formulări create de tine
(„3 întrebări”), dar nu oameni, rezultate, simptome, efecte, procente, raporturi
sau durate precum „48h” ori „în 2 minute”. Ca regulă simplă, în modul Internet
fiecare idee și hook este o întrebare, un îndemn către ea sau descrierea formei
postării — nu o propoziție declarativă care promite un rezultat. Dacă un bloc nu
trece verificarea, îl rescrii înainte să-l arăți.

Uneltele de scriere se cheamă doar după „da"-ul ei, niciodată din proprie
inițiativă (regula 10).\
"""

#: The two paragraphs that were the tail of BASE_INSTRUCTIONS until 2026-08-24.
#: They are about HOW the method is reached, not about what comes out, and the
#: two are now different depending on where the method lives. Split out rather
#: than duplicated: the ten output rules stay in one place, and only this changes.
#:
#: Romanian and untranslated, like everything the model reads.
SANDBOX_METHOD_NOTE = """
Ai un sandbox cu shell și fișiere. Îl folosești ca să citești skill-urile, nu ca
să inventezi unelte. La date ajungi NUMAI prin unelte — nu încerca să te conectezi
la baza de date din sandbox.

ACTIVAREA SKILL-URILOR ESTE OBLIGATORIE. La orice cerere de conținut nou, deschizi
`propune-postari` ÎNAINTE de primul răspuns — inclusiv dacă ea a dat deja formatul,
pilonul sau sursa. Când alege o propunere dintr-o listă existentă, deschizi
`dezvolta-postarea` înainte s-o scrii. Nu improvizezi fluxul din memorie. O cerere
de raport despre postările existente nu activează niciunul dintre aceste skill-uri.
""".strip()

#: The same instruction for an agent with NO sandbox, where each skill is a tool.
#: Telling a model it has a shell it does not have is worse than saying nothing:
#: it spends a turn calling `exec_command` and gets an error back.
#:
#: Measured on 2026-08-23, this is why the alternative exists at all: of 148 KB of
#: skills mounted into the sandbox, a generation run opened exactly one file -
#: SKILL.md - and never touched `references/`. The sandbox charged 5,448 tokens of
#: instructions and tool schemas, plus a turn of flailing at a directory, to hand
#: over a file a single tool call can return.
#:
#: Progressive disclosure survives this, which is the point: the skill's own
#: frontmatter description becomes the tool description, so it is still the
#: description that decides whether the body is ever paid for.
SKILL_TOOL_METHOD_NOTE = """
Metoda ta stă în unelte, câte una pentru fiecare skill, numite exact ca el.
Chemi unealta potrivită și primești metoda întreagă. Nu ai shell și nu ai
fișiere: nu încerca să deschizi nimic și nu inventa unelte.

APLICAREA METODEI ESTE OBLIGATORIE. Chemi unealta ÎNAINTE de primul răspuns,
citești ce întoarce și abia apoi scrii. Nu improvizezi fluxul din memorie.
""".strip()


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
) -> SandboxAgent | Agent:
    """The single agent. Skills from `skills/`, data through MCP, either way.

    Two shapes, one flag — see `USE_SANDBOX` in `config.py`:

    · **sandbox** — `Skills(from_=LocalDir(...))` mounts every folder and the model
      reads `SKILL.md` with a shell. This is what rule 4 described.
    · **tools** — one `FunctionTool` per skill, described by the skill's own
      frontmatter. No shell, no `apply_patch`, no `view_image`, and none of the
      SDK's 3,472-token coding-agent prompt.

    What does NOT change between them: skills are folders on disk, discovered by
    themselves, named and described by their own frontmatter, and the description
    is what decides whether the body is ever loaded. That was the point of rule 4,
    and it survives both shapes. What changes is only the delivery.

    The MCP tools are untouched in both, and so is rule 1.

    `language` changes only what comes out, never the method: the skills stay
    Romanian and an override block is appended. See `content_studio.language`.
    """
    method_note = SANDBOX_METHOD_NOTE if USE_SANDBOX else SKILL_TOOL_METHOD_NOTE
    common: dict[str, Any] = {
        "name": "Content Worker",
        "model": model or MODEL,
        "instructions": (
            f"{BASE_INSTRUCTIONS}\n\n{method_note}"
            f"\n\n--- PROFILUL CLIENTEI ---\n{profile_md}"
            # The language override goes last, after the profile, because it
            # has to contradict rule 1 above and the closer contradiction wins.
            f"{instruction_suffix(language)}"
        ),
        "mcp_servers": [data_mcp],
        "output_type": output_type,
        "model_settings": model_settings or ModelSettings(),
    }
    if not USE_SANDBOX:
        return Agent(tools=skill_tools(), **common)
    return SandboxAgent(
        capabilities=[*Capabilities.default(), Skills(from_=LocalDir(src=SKILLS_DIR))],
        **common,
    )


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


def build_sandbox() -> tuple[E2BSandboxClient, E2BSandboxClientOptions]:
    """The E2B client and its options. The key is read from `E2B_API_KEY`."""
    return E2BSandboxClient(), E2BSandboxClientOptions(sandbox_type="e2b")


async def open_sandbox():
    """`(client, session)` when the sandbox is on, `(None, None)` when it is not.

    One place decides, so no caller has to branch on the flag before it can start
    a run - and no caller can forget to.
    """
    if not USE_SANDBOX:
        return None, None
    client, options = build_sandbox()
    return client, await client.create(options=options)


def sandbox_run_kwargs(client=None, session=None, options=None) -> dict[str, Any]:
    """The `sandbox=` argument for `RunConfig`, or nothing at all.

    Absent rather than None: passing an empty `SandboxRunConfig` would ask the SDK
    to prepare a sandbox for an agent that has no capabilities to use it.
    """
    if not USE_SANDBOX:
        return {}
    if client is None:
        client, options = build_sandbox()
    return {
        "sandbox": SandboxRunConfig(
            client=client,
            **({"session": session} if session is not None else {"options": options}),
        )
    }


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


async def ask_in_terminal(name: str, arguments: dict) -> tuple[bool, str]:
    """The gate, as the client sees it: what is about to be written, and a yes/no."""
    print(f"\n  ⚠ Vrea să cheme `{name}`:")
    for key, value in arguments.items():
        text = " ".join(str(value).split())
        print(f"      {key:<12} {text[:80]}{'…' if len(text) > 80 else ''}")

    answer = input("  Îi dai voie? (da / nu) ").strip().lower()
    if answer in {"da", "d", "yes", "y"}:
        return True, ""
    return False, "Viorela n-a aprobat scrierea. Nu insista; întreab-o ce vrea schimbat."


async def main() -> int:
    for key in ("OPENAI_API_KEY", "E2B_API_KEY"):
        if not os.getenv(key):
            print(f"Lipsește {key}. Copiază .env.example în .env.", file=sys.stderr)
            return 1

    if not SKILLS_DIR.is_dir():
        print(f"Lipsește folderul de skill-uri: {SKILLS_DIR}", file=sys.stderr)
        return 1

    try:
        url, connect_args = database_url()
    except (MissingConfig, RuntimeError) as e:
        print(f"{e}", file=sys.stderr)
        return 1

    # `--nou` still works: it is what the Romanian version answered to, and muscle
    # memory outlives a rename.
    new = bool({"--new", "--nou"} & set(sys.argv))
    # `pool_pre_ping`: a conversation sits idle for minutes between messages, and
    # Neon closes idle connections. Without the ping, the conversation memory dies
    # on resume.
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)

    try:
        session_id = await open_session(engine, new)
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        await engine.dispose()
        return 1

    data_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {CONVERSATION_HEADER: session_id},
        },
        name="content-data",
        cache_tools_list=True,
        tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
        client_session_timeout_seconds=MCP_TIMEOUT,
        # The approval gate sits on the server REGISTRATION, not inside the tool
        # (Decision 9). That way it protects every call the agent makes through
        # this registration, whatever the prompt says. Reads stay free.
        require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
    )
    try:
        await data_mcp.connect()
        tools = [t.name for t in await data_mcp.list_tools()]
        name, profile_md = await read_profile(data_mcp)
    except Exception as e:  # noqa: BLE001
        print(
            f"Nu pot inițializa datele prin MCP la {MCP_URL} ({type(e).__name__}: {e}).",
            file=sys.stderr,
        )
        print("Pornește serverul în alt terminal:", file=sys.stderr)
        print("  uv run content-studio-server", file=sys.stderr)
        await data_mcp.cleanup()
        await engine.dispose()
        return 1

    worker = build_worker(profile_md, data_mcp)

    # A separate engine from the business one: rule 2 wants the trail to have its
    # own connection, outside any transaction that might fail.
    trail = Audit(url, connect_args)

    shape = "sandbox" if USE_SANDBOX else "skill-uri ca unelte"
    print(f"Content Worker · {MODEL} · Deciziile 0–10 · {shape} + MCP + audit + poartă")
    print(f"Bază     : {describe_database(url)}")
    print(f"Clientă  : {name} · profil {len(profile_md):,} caractere în system prompt")
    print(f"Sesiune  : {session_id}{'  (nouă)' if new else '  (reluată)'}")
    print(f"Unelte   : {', '.join(tools)}")
    # The sandbox, when there is one, is created ONCE and reused for every turn.
    # Otherwise a new one would start on every message, skill mounting included —
    # seconds lost for nothing.
    #
    # It is created empty, without a manifest: given a live session, the SDK
    # applies the entries its capabilities ask for, so the skills mount on the
    # first run. Since the session is developer-owned, its full lifecycle ends
    # through `aclose()`; E2BSandboxClient.delete() is intentionally a no-op.
    client = sandbox_session = None
    if USE_SANDBOX:
        print("Sandbox  : pornesc E2B…", end="", flush=True)
        try:
            client, sandbox_session = await open_sandbox()
        except Exception as e:  # noqa: BLE001
            print(" a picat.")
            print(f"{type(e).__name__}: {e}", file=sys.stderr)
            await data_mcp.cleanup()
            await engine.dispose()
            return 1
        print(" gata.")

    config = RunConfig(
        # Every message stays its own trace, but all traces of one conversation can
        # be filtered and seen together in the OpenAI dashboard.
        group_id=session_id,
        **sandbox_run_kwargs(client, sandbox_session),
    )

    session = SQLAlchemySession(
        session_id,
        engine=engine,
        create_tables=True,
        ensure_ascii=False,
    )

    print("Scrie un mesaj, sau „iesire” ca să termini.\n")

    try:
        while True:
            try:
                message = input("tu> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not message:
                continue
            if message.lower() in {"iesire", "ieșire", "exit", "quit"}:
                break

            # The run row opens BEFORE the model is called: if the turn dies, you
            # can see that it existed. Since D4 that is also what makes a dead
            # turn visible without counting — `output_message` simply stays NULL.
            run_id = await trail.open_run(session_id, message)

            print("\n  …lucrez\r", end="", flush=True)
            try:
                result = await run_turn(
                    worker, message, session, config, trail, run_id,
                    ask_in_terminal,
                )
            except Exception as e:  # noqa: BLE001
                await trail.failed(run_id, e)
                print(f"\nworker> Ceva n-a mers ({type(e).__name__}). Mai încercăm?\n")
                continue

            await trail.turn(run_id, result)
            await trail.close_run(run_id, str(result.final_output))

            print(f"\nworker> {result.final_output}\n")
    finally:
        try:
            if sandbox_session is not None:
                await sandbox_session.aclose()
        except Exception:  # noqa: BLE001
            pass
        await data_mcp.cleanup()
        await trail.close()
        await engine.dispose()

    print(f"Conversația a rămas în bază: session_id = {session_id}")
    print(f"Ce a făcut, rejucat:  uv run python -m content_studio.replay {session_id}")
    return 0


def cli() -> int:
    """Console script entry point: `uv run content-studio`."""
    return asyncio.run(main())


if __name__ == "__main__":
    raise SystemExit(cli())
