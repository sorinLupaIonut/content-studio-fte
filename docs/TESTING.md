# Testing

Four rungs, from the ones that cost nothing to the one that exercises the whole
system with real money. You do not need to re-import the database to test an
installation that already works.

## Rung 0 — unit tests, free and offline

```bash
uv run python -m unittest discover -s tests/unit
```

No network, no database, no model. URL normalization, the conversation summary and
profile section replacement. These run in CI on every push.

```bash
uv run ruff check .
```

## Preparation for everything below

`.env` needs:

```text
OPENAI_API_KEY=...
DATABASE_URL=...
E2B_API_KEY=...
```

Optional: `MODEL`, `WEB_SEARCH_MODEL`, `MCP_HOST`, `MCP_PORT`, `MCP_URL`,
`MCP_TIMEOUT`, `CLIENT_SLUG`, `SKILLS_DIR`, `CONTENT_DIR`. They are explained in
`.env.example`.

On a fresh clone:

```bash
uv sync && uv run python -m content_studio.db.apply && uv run python -m content_studio.db.seed
```

`db.seed` is for installation or for refreshing the raw material. It is not needed
before every test.

## Start the server

In the first terminal:

```bash
uv run content-studio-server
```

Leave it open. A good start says:

```text
content-data · five tools · http://127.0.0.1:8765/mcp
```

Everything below uses a second terminal.

## Rung 1 — the safe check

```bash
uv run python tests/checks/bootstrap.py
```

No model call, no writes. It reads the profile over MCP without printing its
content. Expect four ticks: exactly five tools, no SQL tool, the client's name, and
roughly 30,000 characters of profile.

## Rung 2 — one service at a time

```bash
uv run python tests/checks/web.py
```

Sends only the generic topic written in the file. Reads nothing from Neon. Costs one
small web call.

```bash
uv run python tests/checks/write_gate.py
```

No model call. Creates a test conversation, simulates a refused write, saves one
dummy post, verifies the transactional audit, and deletes every row it created in a
`finally`. The last line must be `✓ the check rows were deleted`.

```bash
uv run python tests/checks/tools.py
```

All five tools: an embedding call, the passages read locally from Neon, a generic
web search, and the titles of the last three posts. It must end with `PASSED`. For
each passage it checks title, marker, authority class, version, rights, owner and
embedding model.

```bash
uv run python tests/checks/search.py
```

Decision 5's criterion: ranked passages, each with its page or chapter.

## Rung 3 — the automated evals

One case:

```bash
uv run python evals/run.py --id 10
```

Only the mechanically checkable ones:

```bash
uv run python evals/run.py --automatic-only
```

All fifteen:

```bash
uv run python evals/run.py
```

The evals start E2B and call the model, so they take minutes and consume API budget.
Every write attempt is refused automatically. The report lands in
`evals/report-latest.json` and is not committed.

A verdict of `BY_EYE` is not a failure: it means the patterns cannot judge this one.
Read `final_answer` in the report and decide yourself.

## Rung 4 — the full flow

```bash
uv run python tests/checks/full_flow.py
```

The most expensive and slowest: nine real turns, profile in the system prompt, E2B,
book search, development, the gate in both directions, and the trail. The test post
is deleted; the conversation's audit trail is kept on purpose, for replay.

## The manual test, exactly as the client works

With the server still running:

```bash
uv run content-studio --new
```

```text
tu> Vreau conținut despre vinovăția de a spune nu
```

The correct behaviour is:

1. it asks for the format;
2. after the answer, the pillar;
3. after the answer, the source;
4. it gathers material only from the chosen source;
5. it shows 10 proposals × 5 hooks;
6. it asks which proposal and which hook to develop;
7. it shows the whole post;
8. only after confirmation does it ask, in the terminal, for permission to save.

Answer `nu` at the gate to check the refusal. The post must not appear in the
database. Repeat with `da` only if you actually want to keep it.

Type `iesire` or press `Ctrl+C` to stop.

## Seeing the trail without running the model

```bash
uv run python -m content_studio.replay --list
```

```bash
uv run python -m content_studio.replay <session-id>
```

Messages, skills opened, tools called, approval requests, refusals and saves.
`replay` reads the audit only.

## What goes out, and where

| Check | OpenAI | E2B | Neon | Writes? |
|---|---|---|---|---|
| `tests/unit/` | no | no | no | no |
| `tests/checks/bootstrap.py` | no | no | reads the profile | no |
| `tests/checks/web.py` | generic web topic | no | no | no |
| `tests/checks/write_gate.py` | no | no | temporary dummy | yes, then deletes |
| `tests/checks/tools.py` | generic topics | no | books + post titles | no |
| `tests/checks/search.py` | one embedding | no | books | no |
| `evals/run.py` | profile + messages + passages | yes | reads | refuses all writes |
| `tests/checks/full_flow.py` | profile + conversation + passages | yes | reads, one dummy | deletes the post |

## Debugging in VS Code

The configurations are already written, in `.vscode/launch.json`. Open the project,
press `F5` and pick from the list. The interpreter is the project's `.venv` and
`.env` loads itself.

For the full path, choose the compound configuration **`Server + Worker`**: it starts
both processes under the debugger, so you can stop inside the worker and inside the
MCP tool it calls. The debug toolbar has a process picker to switch between them.

### Five places that show you everything

| File and line | What you catch there |
|---|---|
| `worker.py` — `result = await run_turn(` | the entry to a turn. From there, `F11` walks the rest. |
| `worker.py` — `approved, reason = await approve(` | the gate, at the moment it stops. `arguments` holds everything it wanted to write, field by field, before the row exists. |
| `mcp_server/server.py` — first line of `search_books` | the body of a tool: the description received, the vector, the passages returned. **Only fires if the server was started from VS Code**, not from your terminal. |
| `audit.py` — `for call in calls_in(result)` | the list of calls with their arguments, as pulled from `new_items`, before it reaches `audit_log`. |
| `evals/run.py` — `def verify(` | why a case failed: compare `answers[-1]` with the patterns from `cases.json`. |

Search for the function name rather than the line number — lines move.

### What cannot be debugged

Whatever runs **inside the E2B sandbox** — that is another machine, in the cloud.
Skills are text, not code, so there is nothing to stop there: what the agent reads
from them shows up in `audit.py`, in the arguments of the shell commands.

`justMyCode` is `false` in every configuration, so `F11` steps into the SDK too —
useful when you want to see what `Runner.run` does from the inside.

## Known limits

- "Exactly 10 × 5" is an instruction to the model, not a schema. The checks count the
  result after generation.
- The no-facts rule for the internet source is reinforced in the prompt and checked
  mechanically, but qualitative case 11 stays `by_eye`: a human has to read whether a
  phrasing still sounds like an unsupported claim.
- The gate applies to the MCP registration the worker uses, and protects the agent's
  calls. The server listens on `127.0.0.1` only; a local development script can call
  the tool directly on purpose, which is exactly what `write_gate.py` does.
- The interface is a terminal. A phone-shaped one is not part of this stage yet.

## When something does not work

- `Nothing answers at …8765` → start the server in the first terminal.
- `OPENAI_API_KEY / E2B_API_KEY / DATABASE_URL is missing` → check `.env`.
- `TimeoutError` on the web search → keep `MCP_TIMEOUT=90` or raise it temporarily.
- The server starts on another port → `MCP_PORT` and the port inside `MCP_URL` have
  to match.
- `relation "posts" does not exist` on an older database → run
  `uv run python -m content_studio.db.migrate rename --apply` first.

When you are done, stop the server with `Ctrl+C`.
