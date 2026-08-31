# Testing

Four rungs, from the ones that cost nothing to the one that exercises the whole
system with real money. You do not need to re-import the database to test an
installation that already works.

## Rung 0 — unit tests, free and offline

```bash
uv run python -m unittest discover -s tests/unit
```

No network, no database, no model — 408 tests in about four seconds. URL
normalization, the conversation summary, profile section replacement, the pricing
table, and two invariants that would otherwise drift silently: that every skill's
frontmatter parses identically under this project's YAML reader *and* the SDK's own
line-based one, and that the search rule written in both `SKILL.md` bodies stays
byte-equal.

CI runs these and `ruff`, and nothing else — no key is set for that job on purpose,
because a unit test that needs a key is not a unit test. It has been **paused since
2026-08-28** and runs only from the Actions tab; the checks are the ones you run
locally before a commit.

```bash
uv run ruff check .
```

```bash
uv run python tests/checks/safe/diagram_fit.py
```

Does every label in `docs/diagrams/` fit where it was put. SVG has no text
layout — a label that is too long simply runs over whatever is beside it, the
file stays well-formed, and nothing warns. Four such faults shipped on
2026-08-31 and every one was found by looking at a rendered screenshot. This
estimates the width of each label and reports the four ways it goes wrong:
off the canvas, out of its own box, *into* a neighbouring box, or on top of
another label. It is an estimate, so it is a first pass and not a substitute for
rendering the picture and reading it.

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
content-data · 10 agent tools + 25 internal UI operations · http://127.0.0.1:8765/mcp
```

The two counts are read off `MODEL_VISIBLE_TOOLS` and `INTERNAL_UI_TOOLS`, not
typed into the banner — that line said "five agent tools" for weeks while ten
were registered, because nothing reads a banner.

Everything below uses a second terminal.

## Rung 1 — the safe check

```bash
uv run python tests/checks/safe/bootstrap.py
```

No model call, no writes. It reads the profile over MCP without printing its
content. Expect five ticks: the ten model-visible tools plus the 25 internal UI
operations, no SQL tool, the client's name, and 28,639 characters of profile.

## Rung 2 — one service at a time

```bash
uv run python tests/checks/paid/web.py
```

Sends only the generic topic written in the file. Reads nothing from Neon. Costs one
small web call.

```bash
uv run python tests/checks/safe/write_gate.py
```

No model call. Creates a test conversation, simulates a refused write, saves one
dummy post, verifies the transactional audit, and deletes every row it created in a
`finally`. The last line must be `✓ the check rows were deleted`.

```bash
uv run python tests/checks/safe/tools.py
```

The three read tools: `search_books` (an embedding call plus the passages read
out of Neon), `search_web`, and the titles of the last three posts from
`list_posts`. It must end with `PASSED`. For each passage it checks title, marker,
authority class, version, rights, owner and embedding model.

`search_books` takes a bilingual description — `description` and `description_en`
— because the shelf holds books in both languages and a Romanian query alone
cannot reach an English one.

```bash
uv run python tests/checks/paid/search.py
```

Decision 5's criterion: ranked passages, each with its page or chapter.

## Rung 3 — the automated evals

Grouped by the question each one answers; `evals/README.md` is the map. Three
groups are live — `route/` (did it reach the method and call the right tools),
`skill/` (did the search bring back usable material) and `path/` (does one request
said ten ways walk one path) — and `evals/experiment.py` runs all six of their
scores against one Phoenix dataset in one pass. The order below is also the order
to run them in — the free ones first.

The labels, without a model, a container or a key. A wrong label is a wrong
verdict on every square it touches, so this is read before anything is paid for:

```bash
uv run python evals/route/tool_usage.py --dry-run
```

The method reaches the container whole — one container, no model, no cost:

```bash
uv run python evals/route/fidelity.py
```

What a real run actually opened, off `public.traces`. Free: it reads runs that
already happened:

```bash
uv run python evals/route/references.py --traces --minutes 30
```

The dataset and every label on it, free — no model, no container, no upload:

```bash
uv run python evals/experiment.py --dry-run
```

The spine of the domain grid — 24 squares of the 240, one per distinct label,
against real runs. **This one spends money**, roughly an hour for the spine and
hours for `--all`:

```bash
uv run python evals/route/tool_usage.py
```

All six scores at once, against the Phoenix dataset, so two runs a week apart are
a comparison rather than two report files. **Costs ten generation runs plus the
judge:**

```bash
uv run python evals/experiment.py
```

Every eval writes its report to `evals/reports/<name>-<stamp>.json`, which is
gitignored: a graded report is evidence of a moment, not source. The report holds
the whole route per case — the shell commands verbatim, the references, the tools,
the turns — which is where you look when a square fails.

## Rung 4 — the full flow

```bash
uv run python tests/checks/paid/full_flow.py
```

The most expensive and slowest: nine real turns, profile in the system prompt, E2B,
book search, development, the gate in both directions, and the trail. The test post
is deleted; the conversation's audit trail is kept on purpose, for replay.

## The manual test, exactly as the client works

There is no terminal product any more — `worker.py` is the agent *definition*, and
every door builds from it. The manual test is the site. In VS Code press `F5` and
pick the compound **Site complet (MCP + harness + UI)**; it starts the MCP server,
the harness and the Blazor host, and opens `http://127.0.0.1:5178` by itself.

**Through the buttons.** Pick a format, a pillar and a source, add a focus if you
like, press *Generare*. Correct behaviour:

1. the batch reaches `titles_ready` with **ten** titles, ten different angles;
2. no detail is written yet — that is the point of the lazy phase;
3. opening one idea writes its five hook variants, one per hook type;
4. selecting a variant marks it, and still writes nothing to `posts`;
5. saving asks for confirmation, and only then does a row appear.

**Through chat, which must behave identically.** Type the sentence the button
dictates — „Vreau 10 idei de postare: format Reel, pilon Educație, sursă Memorie."
— and the same thing has to happen, because a button press *is* dictation into the
same session. The sentences are asserted whole in
`tests/unit/test_conversations.py`; if a hand-typed sentence behaves differently
from the button, that is the bug.

Refuse at the gate to check the refusal: the post must not appear in the database,
and the trail must hold `capability_blocked`.

**On a phone, and measured rather than looked at.** CSS has no overflow warning:
a bar wider than the screen is simply clipped, the page still scores as having no
horizontal scroll, and the controls past the edge are gone without a trace.
That is how the bottom bar shipped with the language switch and the way out
entirely off-screen. Narrow the viewport — 412, 375 and 320 are the three that
matter — and ask the page, rather than the screenshot:

```js
const w = document.documentElement.clientWidth;
[...document.querySelectorAll('body *')]
  .map(el => [el, el.getBoundingClientRect()])
  .filter(([, r]) => r.width && r.height && (r.right > w + 1 || r.left < -1))
  .map(([el, r]) => `${el.className} ${Math.round(r.left)}…${Math.round(r.right)}`);
```

Empty is the pass. Two more things the same session should check, because both
were wrong and neither raised: that the floating chat button clears the bar
(`fab.bottom <= rail.top`), and that `--mobile-bar` still matches the bar's real
height — it is a constant, and the bar grew a band.

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
| `tests/checks/safe/bootstrap.py` | no | no | reads the profile | no |
| `tests/checks/paid/web.py` | generic web topic | no | no | no |
| `tests/checks/safe/write_gate.py` | no | no | temporary dummy | yes, then deletes |
| `tests/checks/safe/tools.py` | generic topics | no | books + post titles | no |
| `tests/checks/paid/search.py` | one embedding | no | books | no |
| `evals/route/tool_usage.py --dry-run` | no | no | no | no |
| `evals/route/fidelity.py` | no | no | no | no |
| `evals/route/references.py --traces` | no | no | reads `public.traces` | no |
| `evals/route/tool_usage.py` | profile + brief | yes | reads | writes no batch at all |
| `evals/experiment.py --dry-run` | no | no | no | no |
| `evals/experiment.py` | ten runs + the judge | yes | reads | uploads a Phoenix dataset |
| `tests/checks/paid/run_like_production.py` | one real generation run | yes | reads | writes a batch, as the button does |
| `tests/checks/paid/full_flow.py` | profile + conversation + passages | yes | reads, one dummy | deletes the post |

## Debugging in VS Code

The configurations are written already, in `.vscode/launch.json`, rewritten on
2026-08-24. Open the project, press `F5` and pick from the list. The interpreter is
the project's `.venv` and `.env` loads itself.

Nothing else may hold the ports first. If `8000` or `8765` is already taken by a
service you started in a terminal, the launch fails on bind — stop it first.

| Pick this | To debug |
|---|---|
| **1. Prompt (build_worker)** | anything about the system prompt. No database, no MCP, no OpenAI call, no cost — it stops inside `build_worker` in under a second. The one config with `justMyCode: false`, so `F11` steps into the SDK. |
| **2. MCP server** | a tool body. The harness needs this one, so it starts first in the compound. |
| **3. Harness (FastAPI)** | a request. No `--reload`: a reloader forks, and the debugger would own the parent while the code runs in the child. |
| **4. Blazor UI** | the host process only. `node-terminal`, not `coreclr` — the app runs in the browser's WebAssembly runtime, so debug the C# from the browser's devtools. |
| **5. Unit tests** | a failing test from inside, instead of from its traceback. |
| **6. One real run (COSTS MONEY)** | the only configuration here that spends: one real generation run, the same call the *Generare* button makes. Start **2. MCP server** first and leave it running. |
| **Site complet (MCP + harness + UI)** | the product as the client uses it. One `F5`, three processes, UI at `5178`. |

**Every configuration is `launch`, and the attach ones are deliberately gone.**
They cost an afternoon: the selected one rewrote every breakpoint path to `/app/src`,
a filesystem no local process has, so every breakpoint went hollow while the
connection itself succeeded and nothing reported an error. `git show
<commit>:.vscode/launch.json` has them if a container ever needs debugging.

The compound starts three processes, so the debug toolbar grows a process picker:
you can stop inside the harness and inside the MCP tool it calls, in the same
session.

**Leave the BREAKPOINTS panel's exception filters unticked.** Importing FastAPI
and Pydantic raises ~130k caught exceptions, all normal; they are only expensive if
the debugger stops to inspect them. With "Raised Exceptions" ticked *and*
`justMyCode: false`, one import had not finished after ten minutes — it looks
exactly like a hang at `import httpx`.

No .NET extension is required. The Blazor entry is not a `coreclr` launch: with the
C# extension installed it would attach to the DevServer, a static file server, while
the application runs in the browser's WebAssembly runtime where a debugger on this
side cannot reach it. It runs as a plain command instead, and the C# that executes in
the browser is debugged from the browser's own devtools.

### The one thing worth understanding before anything else

The approval gate is one rule in two shapes, and the shapes are what the deployment
turns on. Put a breakpoint in both and the difference is visible in one sitting:

| Where | What happens |
|---|---|
| `worker.py` — `while result.interruptions:` in `run_turn` | the in-process shape. The loop **waits**: the caller answers inside the same frame. Only `tests/checks/paid/full_flow.py` still uses it — it is the shortcut past the other shape, not a different design. |
| `service.py` — `if result.interruptions:` in `_finish` | the HTTP shape, which is the product. Nothing waits. The run is serialized into `public.runs` (`status='pending'`) and the request returns `202`. |
| `service.py` — `RunState.from_string(worker, …)` in `decide` | the other half, in a **different request**, possibly a different process, possibly hours later. |

A container cannot block on a keyboard, and a replica scaled to zero cannot hold a
Python frame. That is the whole reason the second shape exists.

### Where to stop, by surface

| File and symbol | What you catch there |
|---|---|
| `service.py` — `_run_message` | a turn entering from HTTP: the message, the session, before any model call. |
| `service.py` — `decide` | the gate resolving. `matched` holds what she answered; the row still does not exist. |
| `service.py` — `health` | why `/health` says `degraded` — every backend is probed separately here. |
| `generator.py` — `_generate_one_detail` | one idea's detail run, retry included. Where a bad batch gets diagnosed. |
| `generation.py` — `detail_output_type` | which contract a format gets. Step in to watch a Reel choose the silent one. |
| `mcp_server/server.py` — `save_post` | the body of the write, after approval, before the row exists. |
| `audit.py` — `calls_in(result)` | the calls with their arguments, as pulled from `new_items`, before `audit_log`. |
| `worker.py` — `build_worker` | the four parts of the system prompt being assembled, from what is actually attached. Reachable for free through configuration **1**. |
| `evals/route/tool_usage.py` — `route_from` | what a run actually did, read out of its shell commands. Where a square's verdict is decided. |

Search for the symbol rather than the line number — lines move.

### Attaching instead of launching

For a process the editor did not start. Give it a port and it opens a listener on the
way up (`src/content_studio/debug.py`; with no `DEBUGPY_PORT` it does nothing):

```bash
DEBUGPY_PORT=5678 uv run python -X frozen_modules=off -m uvicorn content_studio.harness.main:app --port 8000
```

Then pick **Attach to a running process**. Add `DEBUGPY_WAIT=1` when the bug is in
startup itself, and the process holds until you connect.

`-X frozen_modules=off` is not decoration. CPython ships frozen copies of the import
machinery, and a breakpoint reached through them can silently fail to bind — debugpy
warns about it in a line that reads like noise.

This is also how the container gets debugged after Decision 2: publish `5678`, set
the same variable, and point `remoteRoot` in the attach configuration at the image's
`WORKDIR`. Breakpoints bind by path, so a mapping that does not match the image binds
to nothing and looks exactly like code that never runs.

### What cannot be debugged

Whatever runs **inside the E2B sandbox** — that is another machine, in the cloud.
Skills are text, not code, so there is nothing to stop there: what the agent reads
from them shows up in `audit.py`, in the arguments of the shell commands.

The Blazor half runs in the browser, not in Python. Use the browser's own debugger
for it; .NET WebAssembly debugging needs the standalone **Blazor UI** configuration
rather than the published files served by FastAPI.

`justMyCode` is `false` in every configuration, so `F11` steps into the SDK too —
useful when you want to see what `Runner.run` does from the inside.

## Known limits

- **"Exactly ten proposals" is a schema now, not an instruction.** `ANGLE_TYPES`
  gives ten archetypes for ten slots, and OpenAI enforces the enum while the model
  writes. What a `SKILL.md` still cannot enforce — tone, whether an angle is any
  good — is judged in the evals.
- **Nothing automated grades what the studio writes.** The `output/` group was
  removed on 2026-08-30 with numbers already two architecture changes stale. Hook
  quality and voice fidelity are read by eye today; that is the top item on the
  backlog and it is named rather than hidden.
- The no-facts rule for the internet source is reinforced in the prompt and in the
  skill, and the route half is checked mechanically — but whether a phrasing still
  *sounds* like an unsupported claim is read by a human.
- The gate applies to the MCP registration the agent uses, and protects the agent's
  calls. The server listens on `127.0.0.1` only; a local development script can call
  the tool directly on purpose, which is exactly what `write_gate.py` does.
- The evals assert Romanian only. The interface is bilingual; the graders are not.

## When something does not work

- `Nothing answers at …8765` → start the server in the first terminal.
- `OPENAI_API_KEY / E2B_API_KEY / DATABASE_URL is missing` → check `.env`.
- `TimeoutError` on the web search → `MCP_TIMEOUT` defaults to 180 since 2026-08-30.
  `search_web` returns read passages rather than a synthesis now, and three
  consecutive real searches took 80s, 55s and 40s. Raise it further if a check
  times out; an MCP timeout comes back as a short error string, not an exception
  the run can see.
- The server starts on another port → `MCP_PORT` and the port inside `MCP_URL` have
  to match.
- `relation "posts" does not exist` on an older database → run
  `uv run python -m content_studio.db.migrate rename --apply` first.

When you are done, stop the server with `Ctrl+C`.
