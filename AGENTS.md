# AGENTS.md — the contract

For anyone editing this repository, human or agent. Short on purpose: it holds the
rules that are expensive to rediscover, and points at the file that owns each truth
instead of repeating it.

## What changed since the deployment brief

Verified on 2026-08-17 against the installed `openai-agents` 0.20.0 package and
the live OpenAI Sandbox Agents documentation. One behavioral difference matters:
`RunState.to_string()` is synchronous and returns `str`; only
`RunState.from_string(...)` is asynchronous. Do not `await state.to_string()`.
All other SDK names used by this repository passed the import probe. The complete
probe record and sandbox-resume findings live in
[plans/DEPLOYMENT.md](plans/DEPLOYMENT.md#d0-findings--read-these-before-writing-harness-code).

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
4. **Sandbox with folder-shaped skills.** `SandboxAgent`, not a plain `Agent`. The
   method lives in `skills/<name>/SKILL.md` plus `references/`, mounted into the
   sandbox and disclosed progressively. They are edited without touching code.
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

## Multi-user, budgets and the admin page

Since 2026-08-21 the studio is multi-tenant in fact, not only in the schema.

- **One account = one `clients` row.** It owns the profile, the lifetime budget
  and the usage. `app_users` maps principals to it, and it is a *link* table:
  several principals may point at one client, because a principal id belongs to
  the identity provider, not to the person.
- **The budget is a lifetime allowance, in integer micro-dollars, and Sorin
  edits it.** No reset period, no cron; that is a decision, not an omission.
- **A stop-gate, not a ceiling.** Cost is known only after a call returns, so the
  gate refuses to *start* — before a run, and again between ideas in a batch.
- **The user is shown a percentage and nothing else.** The split is server-side,
  in `/api/me/usage`; hiding a figure in the interface would not hide it.
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

- **One `run_id`, three surfaces.** The id is born in `Audit.open_run`, bound
  once with `bind_run`, and from there it reaches every log line, the
  OpenTelemetry span, and the rows in Neon. Nothing passes it as a parameter.
- **The fourth surface, Phoenix, is deliberately absent.** `public.traces` plus
  `replay.py` already give a durable, replayable record of a run; Phoenix would
  add an account, a key and a bill for a second copy of it.
- **Sampling is 100%.** The course samples a tenth of successes because it
  assumes production traffic. Three accounts is not production traffic, and
  dropping nine runs in ten would discard the only evidence of a weekly fault.
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

- `BASE_INSTRUCTIONS` in [worker.py](src/content_studio/worker.py) — the ten output rules
- every file under `skills/` — the skill bodies, frontmatter and references
- the MCP tool **descriptions and docstrings** in
  [mcp_server/server.py](src/content_studio/mcp_server/server.py)
- everything `worker.py` prints — that terminal is the product
- `content/` — the profile, the posts, the books
- the conversation summary in [conversation.py](src/content_studio/conversation.py)
- the turns and regex patterns in `evals/cases.json`

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
- `evals/cases.json` still asserts Romanian only. Extending it to English is open
  work, deliberately deferred.

## Where each truth lives

| Thing | Owner | Do not duplicate it |
|---|---|---|
| The ten output rules | `worker.py` → `BASE_INSTRUCTIONS` | docs paraphrase, never restate |
| The two-phase flow | `skills/*/SKILL.md` | |
| Pillars, hooks, sources | `skills/propune-postari/references/` | the method travels with the skill |
| Database shape | `db/schema.sql` | |
| Environment and paths | `config.py` | no other module calls `os.getenv` |
| Tool contract | `mcp_server/server.py` | |
| Interface text, both languages | `ui/.../Localization/Copy.cs` | one line per phrase, never two files |
| Output-language override | `language.py` | the skills stay Romanian |
| Model prices | `pricing.py` | one table; a copy drifts silently |
| What to do when it breaks | [docs/RUNBOOK.md](docs/RUNBOOK.md) | each failure has one named response |
| Telemetry wiring | `observability.py` | one `run_id`, three surfaces |
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
uv run python tests/checks/bootstrap.py
```

Changing a skill, a tool description or the system prompt means the evals are the
only real proof. Run at least the affected case:

```bash
uv run python evals/run.py --id 13
```

Do not commit or push unless asked. The client's books stay out of git.
