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

## Where each truth lives

| Thing | Owner | Do not duplicate it |
|---|---|---|
| The ten output rules | `worker.py` → `BASE_INSTRUCTIONS` | docs paraphrase, never restate |
| The two-phase flow | `skills/*/SKILL.md` | |
| Pillars, hooks, sources | `skills/propune-postari/references/` | the method travels with the skill |
| Database shape | `db/schema.sql` | |
| Environment and paths | `config.py` | no other module calls `os.getenv` |
| Tool contract | `mcp_server/server.py` | |

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
