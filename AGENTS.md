# AGENTS.md — the contract

For anyone editing this repository, human or agent. Short on purpose: it holds the
rules that are expensive to rediscover, and points at the file that owns each truth
instead of repeating it.

## What changed since the deployment brief

Verified on 2026-08-17 against the installed `openai-agents` 0.20.0 package. One
behavioral difference matters: `RunState.to_string()` is synchronous and returns
`str`; only `RunState.from_string(...)` is asynchronous. Do not
`await state.to_string()`. All other SDK names used by this repository passed the
import probe; the complete record is in
[plans/DEPLOYMENT.md](plans/DEPLOYMENT.md#d0-findings--read-these-before-writing-harness-code).
Its sandbox-resume findings are history now — see rule 4.

Domain spec — pillars, hook types, sources, the two phases — is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Architecture rules

Six rules a new session must respect without asking again.

1. **Business data is read and written only through the `content-data` MCP server** —
   never raw SQL from the running worker. There is no `run_sql` tool, no DDL, and no
   free-text parameter that a query is built from.
2. **The audit has its own direct connection** to the database, outside the MCP
   boundary, and every action commits **together** with its audit row, in one
   transaction.
3. **Embeddings use the same model to store and to search** — `text-embedding-3-small`.
   Different models at the two ends means a search that returns garbage without
   complaining.
4. **Folder-shaped skills, read from a sandbox.** The method lives in
   `skills/<name>/SKILL.md` plus `references/`, and it is edited without touching
   code. Since 2026-08-27 it is *delivered* by the SDK's own `Skills` capability:
   the folders are mounted into an E2B container under `.agents/`, and the model
   opens them itself with the shell. Nothing in this project builds a tool for
   it. See [sandbox.py](src/content_studio/sandbox.py).

   **The three steps are the platform's**, on both doors, and they are the same
   three they always were: `Skills.instructions` renders name + description +
   path into the system prompt off the frontmatter, so the description still
   decides whether the body is ever paid for; the model opens `SKILL.md` when
   the task matches; the body names a `references/` file and it opens that too.
   The skill is the one that decides which references a format needs — that
   table is prose in the body ("o ceri de fiecare dată la Reel"), never a
   dictionary in Python.

   **This shape has been in and out twice, and the numbers are why.** An E2B
   sandbox delivered these same folders until 2026-08-24 and was removed after
   measurement: of 148 KB mounted, a generation run opened one file and never
   touched `references/`, while the SDK's default prompt and tool schemas
   charged 5,448 tokens per call. Tools replaced it, then `method.py` preloaded
   the whole method on the generation path — one turn and 26,250 input tokens
   for a Reel detail run, against five turns and 84,269 fetching it. What that
   bought was a duplicate of the format→references table, in Python, that had to
   keep agreeing with the skill body. Sorin chose the standard shape back on
   2026-08-27 with those numbers on the table.

   **Two things stop it costing what it cost the first time.**
   `base_instructions` is overridden — the SDK's default is Codex's 16.9 KB
   coding-agent prompt, which tells the model to write preambles and structure a
   final answer, the opposite of both `BASE_INSTRUCTIONS` and the generation
   schemas. And the capabilities are Shell + Skills only: `Capabilities.default()`
   adds `apply_patch`, a tool for editing the method the agent is meant to be
   reading.

   **The manifest is load-bearing and its absence is silent.** The runtime only
   processes capabilities into a filesystem when a manifest exists, so
   `SandboxAgent(default_manifest=Manifest())` is not decoration: without it the
   container comes up empty, the skills index never reaches the prompt, and the
   model answers from memory after running `find` over nothing.

   **The frontmatter is read by two parsers and only one of them is ours.**
   The SDK builds the index with its own line-based reader, which does not
   understand YAML block scalars: `description: >-` is taken to be the two
   characters `>-`, and every wrapped line containing a colon becomes a key of
   its own. That shipped from 2026-08-27 until the same day — both skills were
   indexed as `>-`, so step 1 above, the step that decides whether the body is
   ever opened, was running blind. Descriptions are one quoted line now;
   `tests/unit/test_skill_references.py` holds both readers to the same answer.
   Found by assembling the prompt and reading it —
   `uv run python tests/checks/safe/show_agent_input.py --live`, which is the only
   way to see the whole input without paying for a run.

   **THE FAILURE MODE IS NOW A MODEL THAT NEVER OPENS THE FILE**, and it does
   not raise. Measured on the first live run, 2026-08-27: `gpt-5-nano` called
   `exec_command` twice with the command `bash`, read nothing, and produced ten
   plausible titles. `gpt-5-mini`, same request minutes later, ran
   `sed -n '1,200p'` over the whole `SKILL.md`. **Nano cannot drive this shape.**
   `generator.py` logs a warning when a run wrote without opening the method.
   The same question is asked three more ways, and each catches something the
   others cannot: `evals/route/references.py --traces` reads it back off
   `public.traces` for runs that already happened, free and after the fact;
   `evals/route/tool_usage.py` asks it of every square of the domain grid before
   anything ships; and `evals/route/fidelity.py` opens a real container and
   compares every file byte for byte, which is what catches a mount that arrives
   truncated or re-encoded.

   **AND THE PROMPT IS NOT WHERE YOU FIX IT.** A generation run has to fetch two
   things before it writes — the format's reference file, and the source's tool
   — and on 2026-08-28 it did exactly one of them: 15 runs out of 16, across
   every format and every source, opened the file OR called the tool, never
   both, and none did neither. Every run that skipped something took exactly
   nine items; the one that did both took twelve. `GENERATION_MAX_TURNS` is 20,
   so nothing was cut off — the model stopped itself. The cause was
   `reasoning={"effort": "minimal"}`, the lowest setting there is, kept from the
   2026-08-24 cost work: measured `reasoning_tokens: 0` on every span. A
   four-step errand asked of a model told not to plan. `"low"` on the detail
   phase took the spine from 3/12 to **12/12**, took "did both" from 1-in-16 to
   9-of-9, and ended six straight `Invalid JSON` failures — all of which had
   been at Reel, the format with the largest reference file. It cost 640
   reasoning tokens, about $0.0013 a run, and **the prompt cache survived
   intact**: 98% cached on the first call against 97% at `minimal`, because
   effort is a request parameter and caching matches the input prefix.
   Phase 1 stays `minimal` — it opens no files, so it has nothing to buy.

   The hours before that fix were spent rewriting the skill, and the pattern
   that should have ended them sooner is written here for whoever meets it next:
   **when every repair trades one score for another, the budget is exhausted,
   and a budget is a setting, not a wording.** `parallel_tool_calls` belongs to
   the same lesson — its default is `None`, and `None` omits the field, so the
   model was never invited to batch. It batches tool with tool *and* shell with
   tool once asked, which is a turn back.

   The five production references (filmare, editare, distribuire,
   întrebări-frecvente, tipuri-de-reels) left the tree on 2026-08-27, moved to
   `nefolosite/` — the skill declines production questions rather than
   answering them from a file.
5. **What a `SKILL.md` cannot enforce, a schema can — and the schema is where
   it goes.** Rule 5 below accepts that a skill body cannot demand "exactly ten
   proposals, really different from each other". Measured on 2026-08-24 with
   that sentence 3,800 tokens above the schema: batch `a16a3f94` proposed
   delegation twice and boundaries twice, closest title pair 0.629. Ten
   archetypes for ten slots — `ANGLE_TYPES`, written before the title, one
   each — took the closest pair to 0.475. Proven the same day, three ways:
   OpenAI enforces `enum`, `pattern` and `minLength` **while the model writes**,
   not afterwards, so a structural rule costs no retry. The corollary is a
   discipline, not a licence: a rule that belongs to the method still lives in
   the skill; only what has a field to sit next to moves into a contract, and
   the glossary rides on that field's `description`.

5. **One agent.** The two phases are skills, not separate agents. The cost, accepted
   with open eyes: a `SKILL.md` is text, not a schema. It cannot enforce "exactly ten
   proposals with exactly five hooks" — that is asked for, counted afterwards, and
   judged in the evals.
6. **Nothing is saved without the client's confirmation.** The approval gate sits on
   the MCP server registration, so it protects the write whoever calls the tool.
7. **The client is resolved from the connection, never from a tool argument.**
   `save_post` is model-visible, and a client the model can name is a client the
   model can get wrong. `client_of(ctx)` reads a header, falls back to the
   principal in `app_users`, then to `CLIENT_SLUG` — see §Multi-user below.

## One conversation, two doors (2026-08-27)

The studio has ONE conversation, and the buttons are a way of speaking into it.
Decided with Sorin on 2026-08-27; the rules that hold it together:

- **The chat window IS the agent's session.** `GET /api/conversation` reads the
  SDK's own session storage verbatim — dialogue whole, tool calls as collapsed
  rows, plumbing absent. There is no separate rendering that could drift from
  the model's input, which is what makes copy-paste testing possible: the
  sentence a button dictates, typed by hand, must behave identically.
- **A button press is dictation.** `harness/conversations.py` owns the exact
  sentences („Vreau 10 idei de postare: format Reel, pilon Educație, sursă
  Memorie.") and they are asserted whole in `tests/unit/test_conversations.py`.
  Changing a word there changes the conversation everywhere — treat those
  strings as contract.
- **One conversation carries at most one lot.** `public.conversations` holds
  the active pointer per account (NOT the messages — that near-duplicate is
  what Decision 11 removed; this table stores what `agent_sessions` cannot:
  which session is active, and the batch born in it). A new lot archives the
  conversation and retires its batch in the same transaction; saved posts are
  untouched. This is also the cost story: history cannot grow unbounded.
- **The chat agent never writes her content.** Three model-visible tools —
  `start_generation`, `develop_idea` (intent recorders) and `select_variant`
  (a data write) — close the loop. The MCP tool validates and audits; the
  harness executes the same pipeline the buttons use (`ChatCoordinator` scans
  the finished run in `trigger_calls`, `service._execute_chat_trigger` runs
  it). A tool that refused is never executed: the scan reads the tool's own
  output. None of the three is gated — they make drafts; rule 6's one
  confirmation stays on saving a post.
- **The engine runs stay stateless.** A generation run carries no conversation
  history; its result is *witnessed* into the conversation afterwards
  (`ConversationLog.witness`, best-effort by contract — a failed witness is a
  display gap, never a failed batch). The 2026-08-24 cost work survives intact.

## Multi-user, budgets and the admin page

Since 2026-08-21 the studio is multi-tenant in fact, not only in the schema.

- **One account = one `clients` row.** It owns the profile, the lifetime budget
  and the usage. `app_users` maps principals to it, and it is a *link* table:
  several principals may point at one client, because a principal id belongs to
  the identity provider, not to the person.
- **The budget is a lifetime allowance, in integer micro-dollars, and Sorin
  edits it.** No reset period, no cron; that is a decision, not an omission.
- **A stop-gate, not a ceiling.** Cost is known only after a call returns, so the
  gate refuses to *start* — before a batch, before each idea she opens, and
  again inside the task that writes it.
- **The user is shown a percentage and nothing else.** The split is server-side,
  in `/api/me/usage`; hiding a figure in the interface would not hide it. The
  model picker used to follow the same rule — its labels said how carefully the
  thing was written, never what it cost — and it came down on 2026-08-27 when
  nano was removed and it was left offering one option. The rule is written
  where the picker was, in `Values.cs`, for whoever brings a second model.
- **A run that fails still spent the money, and the meter has to see it.** Until
  2026-08-24 metering happened only after `Runner.run` returned, so a missed
  structured contract or a turn limit left no `usage_events` row. Measured
  against `public.traces`, which records spans either way: a nano batch consumed
  $0.0195 and recorded $0.0061, a mini batch $0.1019 against $0.0770. The gap
  scales with the failure rate, which is backwards for a gate meant to stop
  runaway spending. The usage is taken off a `RunHooks` and **not** off
  `exception.run_data` — the SDK detaches that on its redaction path, which is
  exactly the path a structured-output failure takes.
- **The first admin is made from the terminal**, `db/provision.py`, and only
  there. An admin page that can mint admins is one stolen session from being
  somebody else's admin page.
- **Only the owner may fall through, and she stops falling.** An authenticated
  principal with no `app_users` row used to land on `CLIENT_SLUG` — which is how
  the client kept working before accounts existed, and also how a tester who was
  allowlisted but never provisioned would land on *her* profile, library and
  allowance. `CLIENT_OWNER_EMAIL` names the one address that may; everyone else
  is told their account is not set up yet. Empty keeps the old behaviour, and
  development mode is exempt. Since 2026-08-23 that fall-through also **writes
  her row**, bound to the `clients` record she already has — never a new one —
  so the admin page can see and suspend her like anybody else; before it, the
  one account that page could not act on was the actual client's. A failure
  there lets her through rather than refusing: the fallback is her own studio,
  so bookkeeping does not get to lock her out. A row that exists and is
  suspended does refuse, which is what makes the button mean something.
- **`provisioned()` has three answers, not two.** True, False, and None when the
  data plane could not be asked. Refusing on None would turn one bad minute into
  everybody locked out of their own studio.
- **The admin page lists clients, not sign-ins.** The account *is* the `clients`
  row; listing `app_users` would hide any client nobody has signed in as — such
  as the original one, whose budget would then be unreachable from the only page
  that can change it.
- **Two doors, and they are strangers.** Since 2026-08-23 a second identity
  provider is supported: an Entra external tenant only Sorin can add people to,
  named in `AUTH_SELF_PROVISION_PROVIDERS`. A principal from it skips the
  `.env` allowlist — membership of that directory *is* the allowlist — and gets
  a `clients` row written on its first request, always role `user`, always the
  default allowance. **Addresses are never matched across providers.** The same
  string arriving from Google and from the tenant is two people with two
  studios; linking them by email would be the one quiet way to hand somebody
  else's profile over. See [plans/ACCOUNTS-OIDC.md](plans/ACCOUNTS-OIDC.md).
- **Self-provisioning is safe for that provider and no other.** It rests
  entirely on nobody being able to enrol themselves, which in an external tenant
  is off by default and has no portal control — one Graph call sets
  `isSignUpAllowed: false`. Adding Google to that setting would hand a studio to
  anyone with an email address.
- **The library is scoped too, since 2026-08-21.** `documents.client_id` is NOT
  NULL and both readers — `ui_list_library` and `search_books` — join through
  `clients` on the slug from the connection. The books are licensed material;
  before this, any account's agent could quote from any other's shelf. A new
  account starts with an empty library on purpose: copying somebody's licensed
  books onto a tester's shelf should take a decision, not a checkbox.

## Observability, limits and the runbook

Decision 7 of the deployment course, wired on 2026-08-21 and adapted to what
this project already had.

- **One `run_id`, four things carry it.** The id is born in `Audit.open_run`,
  bound once with `bind_run`, and from there it reaches every log line, the
  OpenTelemetry span, the rows in Neon, and — since 2026-08-23 — the agent's own
  spans, collected by `RunTraceProcessor` into `public.traces`. Nothing passes it
  as a parameter; the processor reads the ContextVar like everything else does.
- **`public.traces` holds two kinds of row per run.** What was answered, written
  by `close_run`, and how it was reached, written by `sdk_trace`. Same `run_id`,
  which is what makes them one story rather than two tables.
- **The log id is a record factory, not a handler filter.** A filter attached to
  the handlers that exist at configure time misses the one Application Insights
  installs afterwards, and the id was absent from exactly the surface you search
  when the container is gone. See `install_run_id_factory` — the comment there is
  the evidence, not a guess.
- **Phoenix was refused, then asked for, and is wired since 2026-08-23.** It was
  left out because `public.traces` plus `replay.py` already give a durable,
  replayable record — an account, a key and a bill for a second copy. That stays
  true: **Neon is the record, Phoenix is the sample**, and the second one is what
  evaluators read. The feared dependency conflict did not happen — alongside
  `azure-monitor-opentelemetry`, the OpenTelemetry stack resolves to the same
  1.43.0 / 0.64b0 it was already on.
- **Phoenix gets its own `TracerProvider`, never the global one.** The global
  provider belongs to `configure_azure_monitor`, and OpenTelemetry refuses to
  replace one silently. A second provider also bounds the damage: a Phoenix
  outage backs up its own batch processor, not Application Insights'.
- **`exclusive_processor=False` is load-bearing.** The default is True, and True
  calls `agents.set_trace_processors([...])` — which would delete
  `RunTraceProcessor` and stop `public.traces` receiving another span. Check that
  line first if `openinference-instrumentation-openai-agents` is ever upgraded.
- **Sampling is 100%, and it has to be asked for.** The course samples a tenth of
  successes because it assumes production traffic. Three accounts is not
  production traffic, and dropping nine runs in ten would discard the only
  evidence of a weekly fault. This was a claim before it was a fact:
  `configure_azure_monitor` with no sampling argument installs a
  `RateLimitedSampler` at five spans per second, which on 2026-08-23 was keeping
  319 records for 490 requests. `sampling_ratio=1.0`, and a unit test holds it.
- **The harness names itself.** Without an explicit `resource`, every row arrives
  as `cloud_RoleName: unknown_service` — the field Application Map and the Roles
  tab group by. Two container apps and no way to tell them apart is not a map.
- **Telemetry never gates a request.** `/health` reports `observability` but
  never requires it. Monitoring that can cause an outage is worse than none.
- **The rate limit and the budget gate are different mechanisms.** The limit
  bounds accidents per minute, in memory, per replica; the budget bounds
  deliberate spending, in the database, per account. Neither can do the other's
  job, and merging them would need a price known before the request is served.

## Language policy

This is not a style preference; it is how the project stays usable by the person it
was built for.

**Romanian, and never translated:**

- `BASE_INSTRUCTIONS` in [worker.py](src/content_studio/worker.py) — identity and
  voice. **Not the ten output rules**: those left the prompt on 2026-08-24 and
  were deleted on 2026-08-26, because a schema enforces them while the model
  writes. The output contract is the skills plus `harness/generation.py`
- `skill_method_note()` and `data_tool_note()` in the same file — the other two
  parts of the system prompt
- every file under `skills/` — the skill bodies, frontmatter and references
- the MCP tool **descriptions and docstrings** in
  [mcp_server/server.py](src/content_studio/mcp_server/server.py)
- everything the interface shows her — the Blazor UI is the product now; there is
  no terminal loop left in `worker.py`, only the agent definition the harness
  builds from
- `content/` — the profile, the posts, the books
- the dictated sentences in
  [harness/conversations.py](src/content_studio/harness/conversations.py) — a button
  press is dictation, and those strings are contract
- what an eval prints and the labelled prose in its dataset — the terminal is read
  by the client too

**English, everywhere else:** identifiers, comments, docstrings that are not read by
the model, database names, tool *names* and parameter *names*, the docs, the tests,
the check scripts, and anything printed by a developer tool.

A Romanian docstring on a function with an English name is correct here, and so is
an English identifier quoted inside Romanian prose.

### The language switch

Since 2026-08-21 the studio can also be *used* in English, so the product can be
shown to someone who does not read Romanian. This does not weaken anything above.

- The **interface** is bilingual, and both languages sit on the same line in
  [ui/StudioViorela/Localization/Copy.cs](ui/StudioViorela/Localization/Copy.cs).
  Split into two files or two dictionaries and they drift silently.
- The **method stays Romanian and untranslated** — `BASE_INSTRUCTIONS`, every
  `SKILL.md`, every `references/`. What changes the output language is one
  appended block in [language.py](src/content_studio/language.py), never a second
  copy of the method.
- **Domain values never translate.** `Pilon`, `Sursă`, `Format` and the hook types
  are the API contract; only their labels change. See
  [Values.cs](ui/StudioViorela/Localization/Values.cs).
- Profile **section titles are her content**, parsed out of the profile itself, so
  they stay Romanian in both languages. That is correct, not an omission.
- The **evals still assert Romanian only**. Extending them to English is open work,
  deliberately deferred.

## Where each truth lives

| Thing | Owner | Do not duplicate it |
|---|---|---|
| The output contract | the skills + the generation schemas (`harness/generation.py`) | the ten-rule string was cut from the prompt on 2026-08-24 and deleted on 2026-08-26; `worker.py` → `BASE_INSTRUCTIONS` keeps only identity and voice |
| The two-phase flow | `skills/*/SKILL.md` | |
| Pillars, sources | the two `SKILL.md` bodies | always-required method is body, not reference — folded in on 2026-08-27 |
| Hooks, the shelf, per-format detail | `skills/*/references/` | conditional method travels as references |
| Database shape | `db/schema.sql` | |
| Environment and paths | `config.py` | no other module calls `os.getenv` |
| Tool contract | `mcp_server/server.py` | |
| Interface text, both languages | `ui/.../Localization/Copy.cs` | one line per phrase, never two files |
| Output-language override | `language.py` | the skills stay Romanian |
| Model prices | `pricing.py` | one table; a copy drifts silently |
| How many errands a run gets before it writes | `generator.py` → `ModelSettings.reasoning` | it is a setting, never a sentence in the skill |
| Which model wrote a batch | `generation_batches.model` | resolved in `generator.py` before the row is written, so both doors record a name |
| Which references a format needs | the `SKILL.md` body | prose in the skill, never a table in Python |
| How the method reaches the model | `sandbox.py` | one container per run; the manifest is not optional |
| That the ten proposals differ | `generation.py` → `ANGLE_TYPES` | ten archetypes, ten slots |
| What a correct route is, per square of the domain grid | `evals/route/references.json` (format half) + `evals/route/tool-usage-grid.json` (source half) | two manifests, neither copying the other |
| What to do when it breaks | [docs/RUNBOOK.md](docs/RUNBOOK.md) | each failure has one named response |
| Telemetry wiring | `observability.py` | one `run_id`, everywhere it goes |
| Phoenix export and its key | `observability.py` → `configure_phoenix` | the key lives in `.env`, never in a template |
| Who owns which client | `app_users` + `client_of(ctx)` | never a tool argument |
| Which providers carry their own allowlist | `config.py` → `AUTH_SELF_PROVISION_PROVIDERS` | decided once, in `auth.py` |
| Who owns which books | `documents.client_id` | scoped in the SQL, not in the caller |

## Conventions

- Python 3.13, `uv` for everything. Never invoke `pip` or a global interpreter.
- Ruff is the floor: `uv run ruff check .` must be clean before a commit.
- Entry points call `enable_utf8_output()` before printing. The Windows console is
  cp1252 and every answer is Romanian.
- New long-lived engines get `pool_pre_ping=True`. Neon closes idle connections, and
  without it the failure lands on the client's second question, not the first.
- SQL constants live at module level in `UPPER_SNAKE`, near the function that uses them.
- Comments explain *why*, and are worth writing when the reason is not in the code.

## Before you commit

```bash
uv run ruff check .
```

```bash
uv run python -m unittest discover -s tests/unit
```

Anything touching the MCP tools, the gate or the audit also needs the server running
and:

```bash
uv run python tests/checks/safe/bootstrap.py
```

Changing a skill, a tool description or the system prompt means the evals are
the only real proof. Three groups are live — `route/` (did it reach the method and
call the right tools), `skill/` (did the search bring back usable material) and
`path/` (does one request said ten ways walk one path) — and
[`evals/experiment.py`](evals/experiment.py) runs all six of their scores against
one Phoenix dataset in one pass. It **imports** the three rather than restating
them, so a label lives in exactly one place. [evals/README.md](evals/README.md) is
the map. Three older groups (`runs/`, `retrieval/`, `output/`) were removed on
2026-08-30, deliberately and with their numbers already stale; the README records
what each measured, so a rebuild starts from the question rather than from the
code. **Nothing grades what the studio *writes*** until `output/` comes back.

The method reaches the container whole - one container, no model, no cost:

```bash
uv run python evals/route/fidelity.py
```

What a real run actually opened, off `public.traces`:

```bash
uv run python evals/route/references.py --traces --minutes 15
```

Which square of the domain grid a change broke - what a correct route is for
every format × pillar × source × focus, free and before paying for anything:

```bash
uv run python evals/route/tool_usage.py --dry-run
```

Then the same labels against real runs. The default is the spine, 24 of the 240
squares; `--all` is the whole grid and costs hours:

```bash
uv run python evals/route/tool_usage.py
```

All six scores at once, against the Phoenix dataset, so two runs a week apart are
a comparison rather than two report files. `--dry-run` builds the dataset and
every label for free:

```bash
uv run python evals/experiment.py --dry-run
```

Do not commit or push unless asked. The client's books stay out of git.
