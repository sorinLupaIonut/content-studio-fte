# Content Studio FTE

A **Digital FTE** — a digital full-time employee — rather than a chatbot with a
prompt. One sandboxed agent does the work of a content assistant for a real
coaching business: it asks what it needs to know, gathers material from a private
library of 17 books or from the web, proposes ten posts, develops the one that is
chosen, and saves it only after a human says yes.

Built on the OpenAI Agents SDK, a purpose-built MCP server, and Neon Postgres with
pgvector. It runs in production for one client.

> **A note on language.** The agent works in Romanian, because the person it works
> for does. Everything the model reads at runtime — the system prompt, the tool
> descriptions, every file under `skills/` — is Romanian, and so is the terminal
> the client types into. Everything a developer reads — code, comments, docs,
> tests — is English. That split is deliberate and enforced throughout.

---

## What makes it more than a wrapper

Six architecture rules hold the design together. They are in [AGENTS.md](AGENTS.md),
and every one of them is visible in the code:

1. **Business data moves only through the MCP server.** The worker never runs SQL
   against the business tables. There is no `run_sql` tool, no DDL, and no tool
   takes free text that a query is built from. Five tools, and that is the whole
   surface.
2. **The audit trail has its own connection.** A write and its audit row commit in
   the *same transaction* — a saved post with no trail cannot happen, even if the
   connection dies between the two statements.
3. **One embedding model at both ends.** Store and search with
   `text-embedding-3-small`, always. Two different models return garbage without
   complaining, so every row carries the model it was made with.
4. **Skills are folders, not code.** `SKILL.md` plus a `references/` directory,
   mounted into an E2B sandbox and disclosed progressively: the index is always in
   context, the body opens when the task matches, the references open only when the
   skill points at them. The method can be edited without touching Python.
5. **One agent, not a crew.** The two phases are skills, not separate agents — one
   context, so the 30k-character client profile is not copied twice.
6. **Nothing is saved without human approval.** The gate sits on the MCP server
   *registration*, not inside the tool, so it protects every call the agent can
   make regardless of what the prompt says.

## How it fits together

```mermaid
flowchart TB
    U["The client<br/>(terminal, Romanian)"] --> W

    subgraph proc["worker.py — one process"]
        W["SandboxAgent<br/>profile + 10 output rules in the system prompt"]
        A["audit.py<br/>own connection"]
    end

    W -->|"skills mounted"| S["E2B sandbox<br/>propune-postari · dezvolta-postarea"]
    W -->|"5 tools, HTTP"| M["MCP server<br/>content-data"]
    W -.->|"gate: save_post · update_profile"| G{"approve?"}
    G -->|"no"| W

    M --> DB[("Neon Postgres<br/>+ pgvector")]
    A -.->|"trail only"| DB
    W -.->|"conversation memory only"| DB
```

The dotted lines are the only direct database access the worker keeps: its own
conversation state and the audit trail. The profile, the books and the posts — the
business data — all travel through MCP.

### The five tools

| Tool | Kind | What it does |
|---|---|---|
| `search_books` | read | meaning search over 4,778 chunks from 17 books, each with its page |
| `search_web` | read | current angles, with the links of the pages cited |
| `list_posts` | read | what has already been written — "have I covered this?" |
| `save_post` | **write, gated** | one post, plus its audit row, in one transaction |
| `update_profile` | **write, gated** | one profile section, plus its audit row |

Every passage returned by `search_books` carries its provenance — title, author,
page or chapter, rights basis, and whether the source was a summary rather than the
book. A quote with no page number never receives an invented one.

## Quickstart

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), a Neon Postgres database,
an OpenAI key, and an [E2B](https://e2b.dev) key (free tier).

```bash
git clone https://github.com/sorinLupaIonut/content-studio-fte
```

```bash
cd content-studio-fte && uv sync
```

Copy `.env.example` to `.env` and fill it in. The connection string from the Neon
console works as-is — `config.py` normalizes it for asyncpg.

```bash
uv run python -m content_studio.db.apply
```

```bash
uv run python -m content_studio.db.seed
```

Then two terminals. The MCP server in the first:

```bash
uv run content-studio-server
```

The worker in the second:

```bash
uv run content-studio
```

`content-studio` resumes the last conversation; `--new` starts a fresh one.

To fill the library, put Markdown files in `content/books/md/` and run
`uv run python -m content_studio.db.import_books`. The import is per-book and
content-addressed: unchanged books are skipped, so adding an eighteenth title only
embeds that one.

**Upgrading a database created before the English rename:**

```bash
uv run python -m content_studio.db.migrate rename --apply
```

It is idempotent, it moves tables, columns, constraints and JSONB keys, and it does
not touch the vectors.

## Layout

```
src/content_studio/
  worker.py            the agent and the conversation loop
  audit.py             the replayable trail, on its own connection
  conversation.py      the cover sheet: status, counters, summary
  replay.py            reconstructs a past conversation, no model involved
  config.py            environment, paths, DATABASE_URL normalization
  mcp_server/          the `content-data` server: five tools, one resource
  db/                  schema, migrations, seed, book import

skills/                mounted into the sandbox; Romanian, edited without code
  propune-postari/       phase 1: three questions, then 10 proposals × 5 hooks
  dezvolta-postarea/     phase 2: develop the chosen one, then save it

tests/unit/            free, no network — these run in CI
tests/checks/          checks against the real services, from cheapest to fullest
evals/                 15 cases: the ugly ones, plus three trigger evals
docs/                  architecture, testing, and a long illustrated tutorial
```

## Testing

Four rungs, from free to expensive. The ladder is described in
[docs/TESTING.md](docs/TESTING.md).

```bash
uv run python -m unittest discover -s tests/unit
```

```bash
uv run python tests/checks/bootstrap.py
```

```bash
uv run python evals/run.py --automatic-only
```

```bash
uv run python tests/checks/full_flow.py
```

The eval set is the interesting one: twelve cases chosen because they are the ways
this kind of agent fails quietly — an invented page number, a quote attributed to a
book that was only a summary, a figure that sounds like a study, a topic that
conflicts with what the client will not say — plus three trigger evals that check a
skill fires when it should and stays quiet when it should not.

## Where it stands

| # | Decision | State |
|---|---|---|
| 0 | Minimal chat agent — uv, Agents SDK, no sandbox | ✅ |
| 1 | The architecture rules | ✅ |
| 2 | Schema and flow planned, with the reason for each choice | ✅ |
| 3 | Neon + pgvector + schema, then `SQLAlchemySession` | ✅ 7 tables, memory across restarts |
| 4 | `propune-postari` as a sandboxed skill | ✅ 10 proposals × 5 hooks |
| 5 | Import + embedding of the 17 books | ✅ 4,778 chunks, search returns the page |
| 6 | `content-data` MCP server, five tools | ✅ books, web, posts, guarded writes |
| 7 | `dezvolta-postarea` + saving | ✅ full cycle, and a second post from the same list |
| 8 | Audit at every boundary + replay | ✅ trail tied to the conversation, replayable |
| 9 | Approval gate on both write tools | ✅ refused = `blocked`, approved = written |
| 10 | The eval set — 12 ugly cases + 3 trigger evals | ✅ real runner |

Next: deploy it to the cloud, widen the eval set, and give it an interface that is
not a terminal.

## Documentation

- [AGENTS.md](AGENTS.md) — the contract, for humans and for coding agents
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — why it is built this way
- [docs/TESTING.md](docs/TESTING.md) — how to verify it, rung by rung
- [docs/tutorial.html](docs/tutorial.html) — a long illustrated walkthrough of the
  whole system, diagrams included (open it in a browser)

Built following [Building a Digital FTE](https://agentfactory.panaversity.org/docs/digital-fte-crash-course),
Part 4.

## License

MIT — see [LICENSE](LICENSE). The client's profile, her published posts and the
book library are her material, not part of the license: the books are gitignored,
and `content/` holds only what she agreed to keep in the repository.
