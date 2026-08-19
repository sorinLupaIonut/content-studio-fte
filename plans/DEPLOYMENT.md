# Decision 11 — Deployment. Live status board.

**Purpose of this file.** Two coding agents (Claude Code and Codex) and one human
work this repository in parallel. This file is the shared truth about *where the
work stands*, *what is locked*, and *who owns which files right now*. Read it
before you touch anything; update it when you finish a step.

Language follows the repo rule in [AGENTS.md](../AGENTS.md): this is a developer
document, so it is English. Everything the client reads stays Romanian.

Last updated: 2026-08-19 · owner of this update: Claude Code

---

## The goal

Take the project from "runs in two terminals on Sorin's laptop" to "Viorela opens
a URL, works in Romanian, approves writes with a button, closes the browser and
loses nothing" — on infrastructure that sleeps (and costs nothing) when idle.

The hard part is not packaging. It is **rule 6**: nothing is saved without her
confirmation, implemented today as `input("Îi dai voie? (da / nu)")` in
[worker.py](../src/content_studio/worker.py). A container has no keyboard, so the
gate has to be rebuilt before anything can be deployed.

## Locked decisions

Do not reopen these without saying so here.

| # | Decision | Choice |
|---|---|---|
| 1 | Cloud provider | Azure Container Apps — `az acr build`, external ingress, scale-to-zero |
| 2 | The approval gate | `RunState.to_string()` into Postgres on interruption; `RunState.from_string()` on approval |
| 3 | Client interface | **Blazor WebAssembly (CSR)**, published as static files and served by the Python harness |
| 4 | .NET version | **10 LTS** (installed: 10.0.301). Retarget to 11 after its GA on 2026-11-10, if it pays |
| 5 | What is public | Only the harness. The MCP server gets **internal ingress** — it does not exist on the internet |
| 6 | Image strategy | One multi-stage image, two Container Apps, different `--command` |

## Roadmap

Mirrors Part 5 of the *Deploy Your Agent Harness to the Cloud* crash course,
adapted to this project. We stop after each decision for a human go/no-go.

| # | Decision | Status |
|---|---|---|
| D0 | Probe the SDK and reconcile the brief | ✅ done — SDK 0.20.0 probed and brief reconciled below |
| D1 | Harness: FastAPI + the gate on Postgres | ✅ complete — HTTP park/approve/resume contract, 21 free tests; paid live round trip proven 2026-08-18: `RunState` (48,811 bytes) persisted on interruption, approved, resumed, write completed on production data |
| D1b | Blazor WebAssembly interface | 🟡 shell, profile, hybrid generator, streaming chat, batch save and the saved-post editor all built; real 10×5 hybrid batch and real batch save both proven 2026-08-18–19 (see Changelog); a real **rewrite** through the gate (editing an already-saved post) is the one acceptance still without evidence |
| D2 | Containerize (multi-stage: .NET SDK → Python) | ✅ image builds and runs — `Dockerfile` (.NET SDK 10 `-c Release` → `python:3.13-slim`, 425 MB) and `.dockerignore` written by Codex; built and verified end to end 2026-08-19 as two containers on one Docker network: `/health` `ready`, UI served, Brotli/gzip negotiation proven byte-identical to the originals, no `.env` or `content/` in the image |
| D3 | Deploy to Azure Container Apps | ⬜ blocked: Azure subscription unconfirmed |
| D4 | Neon from the cloud + schema changes | 🟡 the course's five-table state model **adopted and verified functionally**; pooled/direct split enforced in code; the "from the cloud" half waits for D3 |
| D5 | Cloudflare R2 — wire it or skip it on purpose | ⬜ open decision |
| D6 | Sandbox execution from the cloud | ⬜ not started |
| D7 | Observability | ⬜ not started |
| D8 | Evals as a deploy gate | ⬜ not started |
| D9 | Production checklist | ⬜ not started |

## D0 findings — read these before writing harness code

Confirmed against the installed SDK, not against the course brief. Where the two
disagree, the installed SDK wins.

| Symbol | Result |
|---|---|
| `openai-agents` | **0.20.0** (the Maya brief pins 0.17.x — ignore that here) |
| `mcp` / `openai` | 2.0.0 / 2.54.0 |
| `RunState.to_string` / `from_string` | both present; `to_string()` is **synchronous** and returns `str`, while `from_string(...)` is **async** — await only `from_string(...)` |
| `from_string(initial_agent, state_string)` | the agent is stored **by reference** and resolved against `initial_agent`; rebuilding the `SandboxAgent` per request is the intended path |
| `RunState._sandbox` | a dedicated field, *"serialized sandbox resume payload for sandbox-aware runs"*, written in `to_json` and read in `from_json` — resuming a sandboxed run is designed for, not a hack |
| `E2BSandboxClient` | `create` / `delete` / `resume(state)` / `serialize_session_state` |
| already installed via `mcp` | `uvicorn` 0.52.3, `starlette` 1.6.0, `sse-starlette` 3.4.8 |
| missing, to add | `fastapi`, `itsdangerous` (`boto3` only if D5 says yes) |
| .NET SDK | 10.0.301 (LTS) |

Still unproven: a live round trip — interrupt on `save_post`, serialize,
deserialize **in a fresh process**, resume. It is a confirmation now, not a
gamble. It costs a model turn plus a sandbox, so it runs at the testing stage.

### The one thing that decides the harness: never pass `SandboxRunConfig.session`

Traced through the installed SDK, function by function:

| step | file:line | what happens |
|---|---|---|
| after the run | `run.py:1848` | `sandbox_resume_state = await sandbox_runtime.cleanup()` |
| | `run.py:1855` | → `result._sandbox_resume_state` |
| `result.to_state()` | `result.py:165-169` | → `state._sandbox` (deep-copied) |
| `state.to_string()` | `run_state.py:1197-1208` | → the `"sandbox"` key of the JSON |
| `RunState.from_string()` | `run_state.py:3640-3641` | JSON `"sandbox"` → `state._sandbox` |
| next run | `runtime_session_manager.py:329-359` | payload found → `client.deserialize_session_state(...)` → `await client.resume(...)` |

And the trap, `runtime_session_manager.py:237-238`, inside `serialize_resume_state`:

```python
if self._sandbox_config.session is not None:
    return None
```

**A live `session=` in `SandboxRunConfig` makes the SDK serialize no sandbox
payload at all** — silently. The state still saves, still restores, and then the
resumed run starts a *different* sandbox: the skills are remounted, and whatever
the agent had written to disk mid-turn is gone.

That is exactly what [worker.py](../src/content_studio/worker.py) does today, and
it is correct there: the CLI holds one process and one sandbox for the whole
conversation, so nothing has to survive serialization.

The harness must do the opposite — pass `client` and `options`, never `session`,
and let the SDK own the sandbox lifecycle. This is not a workaround; it is the
resume path the SDK is built around. Consequence for D6: the harness does not
call `client.create()` or `client.delete()` itself, so sandbox reuse across turns
is a separate question, answered there.

## Parallel work: who owns what

To keep Claude Code and Codex from colliding. Claim a zone in this table before
you start, release it when you are done.

| Zone | Files | Owner |
|---|---|---|
| Harness | `src/content_studio/harness/**` | *unclaimed* — D2 compressed static assets verified in the container |
| Blazor UI | `ui/**` | *unclaimed* — D1b.3 complete |
| Container + infra | `Dockerfile`, `.dockerignore`, `infra/**` | *unclaimed* — D2 image done; `infra/**` still untouched, waits for D3 |
| Schema + migrations | `src/content_studio/db/**` | *unclaimed* — `posts.format_details` applied |
| Content-data MCP | `src/content_studio/mcp_server/**` | *unclaimed* — D1b.3 complete |
| Existing worker/CLI | `worker.py`, `audit.py`, `conversation.py`, `replay.py` | *unclaimed* — D4 prep checkpointed; D1 only extended the gate query in `audit.py` |
| Azure access + infra provisioning | Azure portal, subscription, `az` CLI | **Codex** (D3) |
| Docs | `README.md`, `AGENTS.md`, `docs/**` | *unclaimed* — tool counts corrected at D1b.3; the `conversations` removal is still unreflected |
| This board | `plans/DEPLOYMENT.md` | shared — append, do not rewrite |

### Active handoff checkpoint — 2026-08-18 (D1b.3 closed, free half)

Claude Code took over Codex's five-step continuation order and finished all five.
Every zone is released again.

**Complete and verified:** D1b.1 shell/profile, self-hosted Manrope + Source
Serif 4, D1b.2 hybrid generation, D1b.3 target-aware streaming chat, and now the
saved-post slice: batch save, the `/saved` list and editor, and the rewrite path.

**Last green evidence:** Ruff clean; **84** Python unit/HTTP tests; **6** .NET
tests; Blazor Debug build and Release publish with zero warnings; live read-only
MCP bootstrap with **7 model-visible + 14 internal** tools; the two internal post
reads exercised against live Neon; browser passes at 800 × 450 and 390 × 844 with
no horizontal overflow and no JavaScript error. The temporary services on ports
8000/8765 were stopped. No paid model call, no business write, no commit, no push.

**What is now in place:**

- `mcp_server/posts_store.py` — the batch write, the rewrite and the two reads;
- `save_posts_batch` and `update_post`, both model-visible and both in
  `GATED_TOOLS`; the batch inserts N posts and N `post_saved` rows in **one**
  transaction;
- hidden `ui_list_saved_posts` / `ui_get_saved_post`;
- `GET /api/posts`, `GET /api/posts/{id}`, `POST /api/posts/save-runs`,
  `POST /api/posts/{id}/runs`; decisions keep going through the existing trusted
  `POST /api/runs/{run_id}/decisions`;
- the generator's multi-select save summary, the `/saved` editor, and a
  `saved_post` chat target whose patch is **returned but never persisted**;
- `posts.format_details` applied to Neon through the direct endpoint.

**Three decisions taken while implementing, each a departure worth knowing:**

1. **`save_posts_batch` takes `variant_ids`, not post content.** Codex's
   `SavePostsBatch` contract survives as the server-side validation of what the
   draft rows already hold. Making the model retype ten complete posts would cost
   tens of thousands of output tokens per save on a model that already failed
   strict output at that scale, and would put a rewrite between "she approved"
   and "it was written". `update_post` still carries full content, because a
   browser draft exists nowhere else.
2. **Identity rides a second header, `X-Content-Owner-Principal-ID`.**
   `save_posts_batch` is model-visible, so ownership cannot be a parameter the
   model fills in. The CLI never sets it, which is why that one tool refuses to
   run there and says so.
3. **A prepared run is checked for fidelity before she ever sees it.** The gate
   stops an unwanted write; it does not stop a write of the *wrong thing* — she
   would be approving `save_posts_batch` either way. `HarnessService._prepared`
   compares the prepared arguments with what the application asked for and fails
   the run instead of offering it. Six tests cover the mismatch cases.

**Still outstanding, both needing Sorin's go because they cost money:**

- one real 10 × 5 hybrid batch with observed SSE/retry behaviour (D1b.2);
- one real batch save and one real rewrite through the gate — the save panel and
  the two prepare endpoints have never run against a live batch, because creating
  one requires a paid generation.

**Found while verifying, then resolved by Sorin's decision (2026-08-18):**
`public.posts` held **5 rows of benchmark residue**, all with `conversation_id`
like `d1b-benchmark-…` and titles that were fragments of the D1b prompt header
("Reel UI Structurat D1B — Titluri", "Sursa"). They were written by the paid
nano/mini topology probe, and they were what `/saved` showed the client. The
D1b.0 entry below says "No post or generation draft was persisted"; that held for
generation drafts, not for posts. **All five were deleted** — backed up to JSON
first, then removed inside one transaction guarded on `conversation_id LIKE
'd1b-benchmark-%' AND source_file IS NULL`, committed only because the count was
exactly 5. `public.posts` is now 0 rows, which is what `reset_for_deployment.sql`
intended: the library starts empty and fills only with what the client saves.

The five `post_saved` rows in `audit_log` (#24–#28) were **kept**. The trail is
append-only by rule 2, and it recorded something that genuinely happened; editing
it to match the current table would make it a worse record, not a better one.

## D1b product interview — locked so far (2026-08-17)

Implementation has **not** started. These choices are the hand-off contract for
Codex and Claude Code; do not silently reinterpret "10 ideas" as 10 finished
posts.

The complete accepted specification, architecture mapping and checkpoint plan is
in [D1B_UI.md](D1B_UI.md). That file is awaiting Sorin's approval before code.

- The first result is exactly **10 collapsed idea titles**. Each card expands
  with an arrow, following the interaction observed in the reference recording,
  but the visual design itself will be new.
- Every idea owns **five complete variants**, one for each hook. A variant is not
  only hook text: its script, caption, CTA, hashtags and other format-specific
  fields are generated together. Total per batch: 10 ideas × 5 variants = **50
  complete variants**.
- Those five variants are **alternatives for one idea**, not five independent
  posts. Viorela chooses exactly one variant for an idea. An idea title itself
  is never saved as a post. When several **final posts** are saved together, the
  batch contains only the chosen complete variant from each selected idea.
- In an expanded idea card, the five hooks are presented as tabs. Switching a
  tab previews that variant's complete content; `Alege aceasta varianta` marks
  exactly one variant as the candidate to save.
- The generator selection is also the chat target. The composer shows the active
  idea and hook variant; an instruction such as `fa-l mai bland` rewrites that
  exact variant and the card updates immediately. If no variant is active, the
  UI must ask the user to select one rather than guessing. Rewrites replace the
  current value, with no undo or version history.
- Chat is a global bottom panel on Generator, Saved Posts, Profile and Library.
  Its visible context chip targets the active variant, saved post, profile
  section or library material; with no selection it behaves as general agent
  chat.
- Chat responses stream token-by-token. Installed `openai-agents 0.20.0` exposes
  `Runner.run_streamed(...)` and `RunResultStreaming.stream_events()`. D1b must
  therefore extend the final-response-only D1 contract with an SSE stream (not a
  WebSocket) carrying typed events for text deltas, status/progress, approval
  requests, structured UI patches, completion and errors. Persist the final
  message and run even though its presentation is incremental.
- Streaming includes `Opreste generarea`. Partial chat text remains visible and
  marked stopped, but no structured card patch is applied unless the final patch
  validates completely.
- A saved post can be reopened in the same editor and targeted by the same chat.
  Chat rewrites remain a draft until the user presses `Salveaza modificarile`;
  that explicit action replaces the stored post. There is no saved-post version
  history in the first release.
- The profile is a structured section editor, not raw Markdown. Identity, ideal
  client, voice, offer, pillars, CTAs and restrictions appear as accordions.
  Saving is explicit and section-scoped, and still passes through the existing
  confirmation gate before the destructive profile update is persisted.
- Visual direction is **Studio Viorela** with the line `Continut care suna ca
  tine`: warm editorial, calm and premium, not a copy of the reference UI and
  not generic pink wellness styling. Tokens: warm background `#F7F3EC`, primary
  text `#28242B`, plum primary `#654A5D`, sage accent `#91A296`, decorative gold
  `#C4A261`, white cards. Use Source Serif 4 for editorial headings and Manrope
  for UI/body text, self-hosted. The generator is airy card-based UI; chat is an
  expandable panel anchored at the bottom and always exposes its active target.
- Responsive priority is laptop/desktop for comparing and editing long scripts;
  the complete workflow remains usable on mobile. On narrow screens the five
  variant tabs scroll horizontally and chat opens as a bottom sheet.
- The generator has an optional weekly focus prompt in addition to the required
  source, pillar and format. When filled, it guides all ten ideas; when empty,
  the agent derives relevant angles from the profile and the selected source.
- `Carti` searches the complete indexed library by default. An optional material
  filter can restrict retrieval to one or more selected books; the same filter
  appears for `Combinat`. No extra selection is required for the fast path.
- Multi-save operates on final posts only: one chosen complete variant from each
  selected idea. The UI presents one confirmation summary and persistence is
  atomic (`all or none`), so a validation or write failure cannot leave a
  half-saved batch. This requires a batch write contract rather than independent
  `save_post` calls.
- Chat attachments are conversation-scoped by default. Each attachment offers an
  explicit `Adauga si in biblioteca` option; only that path persists the file,
  extracts/indexes its content and creates embeddings. Temporary attachments do
  not silently pollute permanent retrieval.
- Initial upload support: text PDFs, DOCX, TXT, Markdown and EPUB for documents;
  PNG/JPG as temporary chat attachments. Image-only/scanned PDFs are rejected
  with an explicit OCR-needed message; automatic OCR is deferred.
- Voice MVP is Romanian dictation, not a realtime voice agent: record, stop or
  cancel, transcribe with `gpt-4o-mini-transcribe`, place editable text in the
  composer, and send only on an explicit user action.
- Titles appear first; the 50 variants populate in the background. The sources
  are Books, Internet, Memory and Combined.
- Chat and generator share the same current state. A rewrite requested in chat
  replaces the matching card automatically. There is deliberately **no undo and
  no version history** in this first release.
- Viorela can select several generated items and approve/save them together.
  The intentionally simple lifecycle is `Generated -> Saved`.
- Scope remains core-first: one shared client workspace with exactly two
  allow-listed Google identities (Viorela plus Sorin for testing), profile,
  generator, synchronized chat, approvals and saved posts before library uploads
  and Romanian voice input. This is not public registration and does not require
  a users table in the first release. Production authorization reads a configured
  list of stable principal IDs; the initial email allow-list is used only to
  bootstrap those two identities.
- The two concrete Google addresses were supplied by Sorin in the product
  interview. Keep them out of source code and tracked documentation; provision
  them only as deployment configuration when authentication is implemented.
- Both identities operate on the **same production workspace** for now: the same
  profile, library and saved posts. There is no separate test environment. Show
  the signed-in identity in the UI and attach it to audit events so a change made
  during Sorin's testing is distinguishable from one made by Viorela.
- Clarification: permanent data is shared, but work in progress is isolated per
  identity. Each account owns its active unsaved generation batch, selected
  variant and chat session; profile, library and saved posts remain shared. A
  saved post becomes visible to both accounts.
- Persist exactly one current unsaved batch per identity so refresh, browser
  close or reconnect can restore its cards and background progress. Starting a
  new batch while one exists requires confirmation and replaces it. This is
  crash/reconnect recovery, not undo or historical batch browsing.

### Paid GPT-5 nano topology probe

Synthetic Romanian content was used, with `reasoning.effort=minimal`; no client
profile or private source material was sent. A strict schema required exactly 10
ideas and exactly five complete variants per idea.

| Topology | Wall time | Result |
|---|---:|---|
| one strict monolithic response, 10 × 5 | 61.91 s | valid: 10 ideas / 50 variants |
| titles, then 10 detail calls sequentially | 88.11 s | valid |
| titles, then 10 detail calls concurrently | **11.59 s** | valid; titles visible at 1.90 s |

Decision for the implementation plan: collect shared context once, generate the
10 titles in one fast structured call, then run one bounded concurrent detail
job per idea; each detail job returns all five complete hook variants. Persist
and retry per idea so one failure does not discard the other nine. The measured
parallel path was about 5.3× faster than the strict monolith and 7.6× faster
than sequential generation. Real production latency will be higher when the
full profile, retrieval and web tools participate; the topology comparison is
the result being locked here.

Working branch: **`deploy`**, cut from `main` after `main` was fast-forwarded to
`english`. Both agents work there. Nothing is pushed yet.

Rules for both agents:

1. **The CLI must keep working.** `uv run content-studio` is what the client uses
   today. The harness is a second front door, not a replacement.
2. **The six architecture rules in [AGENTS.md](../AGENTS.md) still hold** — in
   particular rule 1 (business data only through MCP) and rule 2 (the audit has
   its own connection and commits in the same transaction).
3. **No commits and no pushes unless the human asks.**
4. `uv run ruff check .` and `uv run python -m unittest discover -s tests/unit`
   before handing a zone back.
5. Paid checks (`tests/checks/*`, `evals/run.py`) are run deliberately, by the
   human's decision — not on every change.

## The database — migrated 2026-08-17 ✅

Neon project `dry-fog-12289707` (`content-studio-fte`), branch `main`.
Backup before the work: Neon branch **`pre-deployment-2026-08-17`**
(`br-lively-cell-avhqk36f`), verified to hold the pre-migration row counts.
Note the project's history retention is only **6 hours**, so point-in-time
restore was never a substitute for that branch.

| table | before | after |
|---|---:|---|
| `documents` | 17 | **17** — untouched |
| `embeddings` | 4,778 | **4,778** — untouched, `conversation_id` column dropped, HNSW index not rebuilt |
| `clients` | 1 | **1** — the profile, 30,748 chars |
| `posts` | 27 | 0 — all 27 still exist as files in `content/posts/`, so `db.seed` can bring them back |
| `audit_log` | 117 | 0 |
| `agent_sessions` / `agent_messages` | 2 / 56 | 0 / 0 |
| `conversations` | 7 | **dropped** |
| `capability_invocations` | 11 | **dropped** |
| `pending_runs` | — | created here, then **dropped again at D4** — see below |

The four foreign keys were dropped by their real names rather than with a blind
`CASCADE` — and the names were not the obvious ones: those on `posts` still
carried pre-rename Romanian spellings (`postari_conversation_id_fkey`).

Applied via the Neon MCP server:
[reset_for_deployment.sql](../src/content_studio/db/reset_for_deployment.sql).

### D4 verification — the schema works, not just exists

Structure, constraints and indexes were read back out of `pg_catalog` and match
[schema.sql](../src/content_studio/db/schema.sql) exactly. Beyond that, checked
by doing rather than by looking — writes on a throwaway Neon branch
(`schema-check-tmp`, `br-ancient-night-avt8x3uj`), reads on `main`:

| what | result |
|---|---|
| pgvector search over the library | ✅ probe chunk returns itself at 1.0000, then neighbours at ~0.72 across three different books, page + model metadata intact |
| the MCP server's own `SEARCH_SQL`, `LIST_POSTS_SQL`, `PROFILE_SQL` | ✅ run through the app's real path — `config.normalize_url` → asyncpg → the **pooled** endpoint — including the `$1::vector` cast and the title filter |
| `pending_runs` insert / resolve / reopen | ✅ |
| two open runs in one session | ✅ **rejected** by `idx_pending_runs_one_open_per_session` — one turn in flight per conversation is enforced by the database, not by hope |
| `approval_granted` accepted | ✅ |
| an old Romanian action (`aprobare_ceruta`) | ✅ **rejected** by the CHECK — the vocabulary is still closed |
| a post with an orphan `conversation_id` | ✅ accepted now; the old FK to `conversations` would have refused it |
| a post with a non-existent `client_id` | ✅ **rejected** — `posts_client_id_fkey` still bites |
| refused-vs-allowed derived from the trail | ✅ `save_post`→blocked, `search_web`→ok despite its own `status: error` |

**One inconsistency found and fixed.** `rename_to_english.sql` renamed the tables
and columns but not the constraints Postgres had already named after them, so
this database still said `client_pkey` and `postari_client_id_fisier_sursa_key`
while a database created fresh from `schema.sql` says `clients_pkey` and
`posts_client_id_source_file_key`. Same shape, different names — and that is
precisely how the Decision 11 migration nearly failed silently, since
`DROP CONSTRAINT IF EXISTS <guessed name>` is a no-op that reports success.
`schema.sql` now carries an idempotent rename block, so `db.apply` repairs any
database that still carries the old names. Applied to `main` through `apply.py`
rather than by hand, to prove the file does the work.

## D4, second pass — the course's state schema adopted (2026-08-17)

Sorin's call, made with the companion files in hand: replace our state half with
the crash course's, keeping only the domain. The companion lives at
`C:\Users\sorin\Downloads\AI\deploying-agents` — `schema.sql` and
`src/maya_harness/state.py`.

Backup first: Neon branch **`pre-d4-course-schema-2026-08-17`**
(`br-billowing-forest-avqqtni2`).

What the database holds now:

| table | origin | state |
|---|---|---|
| `documents`, `embeddings` | ours | untouched — 17 / 4,778 |
| `clients`, `posts` | ours | untouched — 1 / 0 |
| `runs`, `traces`, `artifacts` | **the course**, column-for-column | created, empty |
| `audit_log` | **the course** — `(run_id, event)` | replaced, empty |
| `pending_runs` | ours | **dropped** |
| `agent_sessions`, `agent_messages` | the SDK | the only session table |

Two departures from the companion, both deliberate:

1. **The course's `sessions` table is not created.** `agent_sessions` already
   exists, the SDK writes it, and `agent_messages` already keys off it — so
   `runs.session_id` references `public.agent_sessions(session_id)` instead. A
   second session table would be the same mistake `conversations` was.
2. **`artifacts` is not `posts`.** The course's artifacts are pointers to objects
   in R2; a post is a structured row of the client's work. Kept apart. `artifacts`
   stays empty until D5.

### What this costs — read before building the harness

- ~~**The approval gate has no durable home.**~~ Fixed the same day — see "The
  gate" below. It lives on `public.runs` now.
- **The trail lost its detail.** No arguments, no results, no actor, no CHECK.
  `event` is free text; the vocabulary is now a shared constant in `audit.py`
  that `replay.py` imports, and nothing in the database enforces it.
- **`update_profile` became destructive.** The previous text used to be
  recoverable from `audit_log.payload`. It is not stored anywhere now. The tool's
  own description was rewritten to say so.

### Verified by doing, not by looking

Structure read back from `pg_catalog` matches the companion's `schema.sql`
column-for-column. Then, through the app's real path (`config.normalize_url` →
asyncpg → the **pooled** endpoint) with the real `Audit` class:

| what | result |
|---|---|
| `open_run` → events → `close_run` | ✅ run, trace and six events written in order |
| the SDK session row | ✅ ensured once, not duplicated |
| `replay.py`'s own `RUNS_SQL` / `EVENTS_SQL` / `LIST_SQL` | ✅ all three read it back |
| blocked vs allowed derived from the trail | ✅ `save_post`→blocked, `search_books`→ok |
| a run on a session that does not exist | ✅ **rejected** — `runs_session_id_fkey` bites |
| a trace / artifact on a run that does not exist | ✅ **rejected** |
| an audit row with no event text | ✅ **rejected** — NOT NULL |
| an audit row with `run_id` NULL | ✅ accepted — the `db.seed` case |

### The gate — six columns on `public.runs`, not a table of its own

Sorin's call. A run waiting for an answer is still a run, so the state goes where
the run already is: `status`, `requests`, `state`, `decisions`, `resolved_at`,
`resolved_by`. Everything the companion's `state.py` writes is still written in
the columns it expects — the additions are additive, so `runs` is the course's
shape *plus* the gate.

Three things the **database** enforces, so no code has to remember them:

- `runs_status_check` — `running | pending | completed | failed | expired`.
- `runs_pending_is_resumable` — a run may not claim to be `pending` without both
  `state` and `requests`. Without it, a half-written suspend produces a row the
  harness would show her as "waiting for your answer" and then fail to continue.
- `idx_runs_one_open_per_session` — unique over `status = 'pending'`. Two browser
  tabs cannot each leave a run waiting. Deliberately **not** extended to
  `running`: a crashed turn would then lock the session out forever.

`audit.py` grew `suspend_run` / `pending_run` / `resume_run`. These are the only
methods in the file that do **not** swallow their exceptions — they raise
`GateError`. The trail can afford to lose a row; the gate cannot, because the
failure mode is telling her the agent is waiting when nothing is.

Verified through a real process boundary — parked by one `Audit`, that engine
disposed, then read and resumed by a **different** one sharing nothing but the
database. 22 checks, all passing:

| what | result |
|---|---|
| a `RunState`-shaped string with diacritics, quotes, backslashes and base64 | ✅ round-trips byte for byte |
| both interruptions of one run, arguments nested inside | ✅ survive |
| a second run waiting in the same session | ✅ **rejected** — `UniqueViolationError` |
| `pending` with no state to resume from | ✅ **rejected** — `CheckViolationError` |
| an invented status | ✅ **rejected** |
| parking an already-parked run / resuming one that is not waiting | ✅ **`GateError`**, not a silent success |
| resume → `running`, so the same run can stop at the gate again | ✅ the normal two-write case |
| `resolved_by`, `resolved_at`, both decisions | ✅ stored |
| the gate's own trail | ✅ `approval_requested` ×2, `granted` ×2, `rejected` ×1 |

**One trap found while doing it, worth knowing before writing harness code.**
Bare asyncpg returns `JSONB` as a **string**; SQLAlchemy's asyncpg dialect
registers a JSON codec on every connection it manages, so the same column comes
back **already decoded**. Code written against one and run against the other dies
on a `json.loads` that suddenly receives a list. `pending_run` now normalizes it,
so callers get the decoded value either way.

### The pooled/direct split is now enforced, not just documented

`reset_for_deployment.sql` told you to use the direct endpoint; nothing stopped
you. `apply.py` and `migrate.py` now take `config.migration_url()`, which reads
`DATABASE_URL_DIRECT` and **refuses to run DDL through a `-pooler` host**. The
app keeps `database_url()` and the pooled endpoint. Both migrations above ran
through the direct one.

Every SQL statement in the codebase is schema-qualified (`public.runs`). Measured
first: the effective `search_path` is the default and there are zero role or
database overrides, so bare names were working — this is insurance against the
day someone sets one, not a bug that was biting.

`apply.py` also grew the `--file` flag its own migration files had been
documenting for two decisions without it existing.

## Open questions blocking work

1. ~~**Branch base.**~~ Resolved: `main` fast-forwarded to `english`, branch
   `deploy` cut from it. Local only, nothing pushed.
2. ~~**Neon branch before the migration.**~~ Resolved. The Neon MCP server is
   declared in this repo's `.mcp.json`, but a project `.mcp.json` is only loaded
   from the session's own working directory — the agent was running elsewhere.
   Copying the file to that directory and restarting loaded it. **Lesson for both
   agents: run from `E:\aplicatii_noi\content-studio-fte`, or the repo's MCP
   servers are silently absent.**
3. ~~**Code that dies with `conversations`.**~~ Done — see the changelog.
4. ~~**`E2B_API_KEY` is missing from `.env`.**~~ Wrong — it is present and set,
   as are `OPENAI_API_KEY`, `MODEL` and `DATABASE_URL`. The CLI is not blocked.
5. ~~**Where does the approval gate live now?**~~ Resolved the same day, Sorin's
   call: on `public.runs`, as six more columns. `runs` is therefore the course's
   shape **plus** the gate — everything the companion writes is still written in
   the same columns. Verified across a process boundary; see below.

The remaining infrastructure blocker is unchanged — D3: Azure access, Codex's
zone, needs Sorin for MFA.

## Changelog

- **2026-08-19 (evening) · Claude Code** — **D2 finished: the image builds, runs,
  and serves the compressed UI. Picked up exactly where Codex stopped.**

  Codex had written `Dockerfile`, `.dockerignore` and the Brotli/gzip negotiation
  in `static_ui.py`, but its `docker build` was interrupted by hand at the .NET
  restore step, so nothing had ever been proven to run. Resuming it turned up a
  blocker that had nothing to do with the Dockerfile: the Docker engine answered
  `500` on every API route because the `docker-desktop` WSL distribution — the VM
  that supplies the Linux kernel — was stopped. Starting the distribution alone
  did not help; `docker desktop restart` did. Worth remembering before suspecting
  a build file again.

  **Build.** `docker build --tag content-studio-fte:d2 .` exits 0. The .NET stage
  restores and publishes with `-c Release` as required; the runtime stage installs
  from the lockfile. Final image: **425 MB**. One warning, not an error, left
  as-is deliberately: the `wasm-tools` workload is absent, so the Blazor publish
  runs "without optimizations" — it is a size/AOT optimization, unrelated to
  compression, and installing a workload inside the image is a decision for
  Sorin, not a fix to slip in.

  **Verified in the running container**, two of them on one Docker network, MCP
  started with `content-studio-server` and `MCP_HOST=0.0.0.0`, harness pointed at
  it through `MCP_URL=http://studio-mcp-test:8765/mcp`:

  | check | result |
  |---|---|
  | `/health` | first call `degraded` — Postgres hit the 3 s timeout on Neon's cold start, the exact D3 risk already flagged; second call **`ready`** in ~1 s, all backends up, MCP reporting 7 tools |
  | UI at `/` | HTTP 200, `Studio Viorela` |
  | SPA fallback `/generator` | HTTP 200, serves `index.html` |
  | unknown `/api/` route | HTTP 404 — the fallback correctly does **not** swallow API routes |
  | `Accept-Encoding: br, gzip` | `content-encoding: br`, 21,949 B, `content-type: application/wasm`, `Vary: Accept-Encoding` |
  | `Accept-Encoding: br;q=0, gzip` | falls back to `gzip`, 26,333 B — `q=0` honoured |
  | `Accept-Encoding: identity` | 62,741 B, no `Content-Encoding` |

  **Integrity, not just headers.** Serving precompressed bytes under the wrong
  headers would break the app in a browser while looking healthy in `curl`, so
  the bytes were checked: the gzip response decompresses **byte-identical** to
  the plain asset (SHA-256 `ab20a5e8…`), the Brotli response is byte-identical to
  the `.br` file .NET produced (`f540ccba…`) and decompresses to the same
  original. 53 `.br` and 53 `.gz` files ship in the image. On this asset alone the
  saving is 62,741 → 21,949 bytes.

  **Image hygiene.** No `.env` anywhere in the image, and no `content/` — the
  client's material stays local, as `.dockerignore` intends. `skills/` is present,
  as the sandbox needs it at runtime.

  **One trap worth recording.** `config.py` derives `PROJECT_ROOT` from
  `Path(__file__).resolve().parents[2]`. That only lands on `/app` because `uv
  sync` installs the project **editable**; a non-editable install would resolve it
  inside `.venv`, `UI_STATIC_DIR` would point at a directory that does not exist,
  and `mount_ui` would silently return `False` — a container that boots fine and
  serves no interface. Verified explicitly in the image: `PROJECT_ROOT=/app`,
  UI and skills both resolve.

  `uv run ruff check .` clean; 110 unit tests OK. No paid run, no model call, no
  write to Neon — `/health` only reads. Test containers and the test network were
  removed afterwards.

- **2026-08-18 · Claude Code** — **Checkpoint for Codex. Everything committed
  and pushed to `deploy` (`4f297c0`). Generation bug found and fixed. Design
  direction chosen: dashboard shell with a left rail.**

  **The bug Sorin hit.** `POST /api/generation-batches` answered 502
  `DraftDataError` and nothing said why, because the generic handler kept only
  the exception class name. Root cause, reproduced and then proven fixed without
  a single model call: an MCP tool returning an **empty list** comes back with
  zero content blocks and no structured content, and `tool_payload` read that as
  a fault. So `list_posts` on an empty library broke source collection — the
  exact first-run case, which the five benchmark rows had been masking. The fix
  is explicit rather than clever: callers that know an empty answer is legitimate
  pass `empty=[]` (`list_posts`, `search_books`); the guard stays for genuinely
  ambiguous multi-block responses. Four unit tests cover it, including two that
  prove the default does not mask a real tool error or an ambiguous payload.
  `collect_source_packet` now returns `recent_posts: []` against live Neon.

  Also added `logger.exception` behind the generic 502 handlers. The client keeps
  reading one short Romanian sentence; the operator finally gets the stack. First
  half of D7.

  **Not verified, because it costs money and that is Sorin's call:** the actual
  10-idea generation past `drafts.create`. Everything up to the model is proven.

  **Design — decided, not implemented.** Sorin chose a dashboard shell: fixed
  left rail, four tabs (Generator, Salvate, Profil, Materiale), visibly active
  tab. The mockup and the reasoning behind every choice are checked in under
  [plans/design/](design/) — `shell-mockup.html` is clickable and carries a
  laptop/phone switch so both layouts are visible in a narrow preview pane;
  `README.md` records the seven decisions and what porting costs. Statistics
  cards were proposed and then **dropped on Sorin's call**: two of four needed
  new queries and none changed what the client does next, so the space went to
  the ten generated ideas instead.

  Porting is `MainLayout.razor`, `PrimaryNav.razor` and the shell half of
  `app.css`. The four page components keep their markup and their logic, and
  `NavLink` already emits `active`, so the active-tab treatment is CSS only.

- **2026-08-18 · Claude Code** — **Benchmark residue purged from
  `public.posts`; library verified empty and the studio handed over for manual
  testing.** Backed the five rows up to JSON, deleted them inside one transaction
  whose WHERE clause matched only `d1b-benchmark-%` rows with `source_file IS
  NULL`, and committed only after the rowcount came back exactly 5. `posts` went
  5 → 0. Everything else untouched and re-counted: client Viorela, 17 library
  documents, 4 778 embeddings, 0 generation drafts, 2 completed CLI runs, 9 audit
  rows, 1 agent session with 6 messages. The `post_saved` audit rows were kept on
  purpose — rule 2 makes the trail append-only.

  Then re-published the Blazor UI clean (`rm -rf dist` first, so no stale
  fingerprinted assemblies survived) and started both services locally for Sorin:
  `content-data` on 8765 and the harness on 8000 with `AUTH_MODE=development`.
  `/health` reports all five surfaces ready and MCP at 7 tools; `/saved` renders
  the empty state; the three pre-model guards still answer 404/422/422 without
  reaching the model — `runs` stayed at 2 throughout, which is the proof.

- **2026-08-18 · Claude Code** — **D1b.3 closed on its free half.** Picked up
  Codex's five-step continuation order and finished all of it: `posts_store.py`,
  the gated `save_posts_batch` and `update_post`, the two hidden post reads, four
  FastAPI routes, the generator's save summary, the `/saved` list and editor, and
  a `saved_post` chat target whose rewrite stays a browser draft. Applied
  `posts.format_details` through Neon's direct endpoint.

  Three departures, each argued in the checkpoint above: the batch tool takes
  variant ids rather than retyped content; ownership travels as a second trusted
  header instead of a model-supplied argument; and a prepared run whose arguments
  drifted from what the application asked for is failed rather than shown for
  approval.

  Also corrected the tool counts that README, `docs/TESTING.md` and
  `docs/ARCHITECTURE.md` had been stating as five, and translated FastAPI's raw
  422 field list into one Romanian sentence — the client was being shown English
  Pydantic JSON.

  Verified: Ruff clean, 84 Python tests, 6 .NET tests, Blazor Release publish with
  zero warnings, live bootstrap at 7 + 14 tools, both internal post reads against
  live Neon, and desktop/mobile browser passes with no overflow and no JavaScript
  error. Temporary services stopped. No paid model call, no business write, no
  commit, no push. Found 5 benchmark-residue rows in `public.posts` and left them
  for Sorin to decide on.

- **2026-08-18 · Codex** — **D1b.3 streaming chat and synchronized variant
  patches implemented; saved-post approval slice remains.** Added one
  principal-owned chat session, `POST /api/chat/runs`, reconnectable typed SSE on
  `GET /api/runs/{run_id}/events`, and explicit cancellation. The UI always
  shows the active target and sends only its typed ID; the server re-resolves
  ownership and content through `content-data`.

  `gpt-5-mini` streams a strict output envelope. Only the `reply` string is
  exposed incrementally; a generation-variant patch remains hidden until the
  complete Pydantic object validates, then one internal MCP operation replaces
  the draft and writes its audit event in the same transaction. Cancelling keeps
  visible partial text but cannot apply a patch. The Blazor drawer streams text,
  has an `Oprește` action, and refreshes the generator after `ui.patch`.

  Verified: Ruff clean, 60 Python tests, 3 .NET tests, zero-warning Blazor build,
  and the live read-only bootstrap reports 5 model tools + 12 hidden UI tools,
  the exact five-tool model allowlist, no SQL tool and the 30,748-character
  profile through MCP. No paid model call, generation, profile/post write,
  commit or push.
- **2026-08-18 · Codex** — **D1b.2 implementation built; real hybrid acceptance
  run deliberately not started.** Added title-first background orchestration,
  bounded five-slot E2B detail generation, one automatic per-idea retry,
  cancellation, principal ownership checks and durable reload through internal
  `content-data` operations. Source material is gathered once. The browser sees
  only library metadata and public batch fields; source excerpts, internal
  session IDs and owner IDs are stripped from API responses.

  Added authenticated library/current/get/cancel/select endpoints and typed SSE
  with reconnectable durable snapshots. The Generator page now has the four
  sources, five pillars, three formats, optional focus, optional 17-book filter,
  replacement confirmation, ten progressive cards, five hook tabs and one
  selected variant per idea. The VS Code Blazor host on port 5178 reaches FastAPI
  correctly. SPA deep links return `index.html`; unknown `/api/*` paths remain
  404 and have a dedicated regression test. No model button was pressed, so the
  database still has no generation draft from this verification and no paid call
  was made. D1b.2 remains open only for one Sorin-approved real 10 × 5 run and
  observed SSE/retry acceptance. No commit/push.
- **2026-08-18 · Codex** — **D1b.1 complete; D1b.2 claimed and in progress.**
  Sorin accepted the hybrid generator: `gpt-5-nano` for the ten short titles,
  `gpt-5-mini` for complete variants, maximum five detail jobs concurrently.
  These are separate configuration values; the existing CLI model remains
  unchanged.

  Added the .NET 10 Blazor WebAssembly shell for Generator, Salvate, Profil and
  Materiale, plus the global chat drawer. FastAPI now exposes trusted `/api/me`
  and structured profile endpoints, reads the live profile through
  `content-data`, and routes a section update through the existing agent approval
  gate. Azure mode trusts only Easy Auth headers and fails closed; local bypass
  is restricted to loopback and is refused under Azure environment markers.
  Real addresses remain deployment configuration, never tracked source.

  The published SPA is served by FastAPI with client-route fallback. VS Code now
  has one compound, `Studio complet (3 servicii)`, for MCP + harness + Blazor.
  Verified: Ruff clean, all 42 Python unit/HTTP tests pass, Blazor Debug build and
  Release publish complete with zero warnings/errors, live profile renders from
  MCP, desktop and 390 px browser passes are clean, and browser console has zero
  warnings/errors. No paid model call and no business write were made. Temporary
  services were used only for the browser pass. No commit/push.
- **2026-08-18 · Codex** — **D1b.1 typography closed.** Added the approved
  Manrope and Source Serif 4 variable fonts from the official Google Fonts
  repository, with their OFL license files, and wired them through local
  `@font-face` declarations. The published UI has no runtime font-CDN
  dependency.
- **2026-08-18 · Codex** — **D1b.0 implemented; model/cost go-no-go pending.**
  Added strict 10-title/5-variant and typed SSE contracts, three additive draft
  tables, nine internal `content-data` operations with same-transaction audit,
  and a strict five-tool allowlist for the model. Applied `schema.sql` through
  Neon's direct endpoint: the new tables are empty and the existing 17 documents,
  4,778 embeddings and client data are intact. The live MCP reports exactly five
  agent tools plus nine internal UI operations. Updated both skills with isolated
  structured-UI branches while preserving their CLI flows.

  The real full-profile spike rejected `gpt-5-nano` for long detail generation:
  titles were valid in 25.58–35.01 s, but concurrency 10 produced 1/10 valid ideas
  in 72.45 s and an isolated concurrency-5 run produced 1/10 in 110.16 s. The
  failures were mainly the account's 200k TPM ceiling, plus invalid structured
  JSON and incomplete skill execution. Recommendation: nano for titles,
  `gpt-5-mini` for details, default concurrency 5 with backoff; mini is documented
  at 500k TPM but costs 5× per token, so it is not enabled without Sorin's go.

  The spike found that SDK 0.20.0's `E2BSandboxClient.delete()` is a no-op for a
  developer-owned session. Worker, eval and check cleanup now use
  `sandbox.aclose()`. Exactly the 20 leaked benchmark sessions were killed; the
  28 older paused sessions were deliberately left untouched. Ruff and all 31
  unit tests pass. MCP bootstrap passes and E2B reports zero running sandboxes.
  Required eval 13 was run and **failed on nano**: no skill activation, two
  rejected `update_profile` attempts, then invented content. No profile write
  executed. Eval and full-flow now use the same five-tool allowlist as production.
  No post or generation draft was persisted. No commit/push.
- **2026-08-17 · Codex** — Sorin approved [D1b.0](D1B_UI.md): strict generation
  and SSE contracts, draft persistence through `content-data`, and the real-stack
  5-vs-10 concurrency probe. Codex claimed harness, UI, schema/migrations and MCP
  for this checkpoint. Claude Code remains paused. No commit or push authorized.
- **2026-08-17 · Codex** — **D1 complete.** Added the FastAPI control plane with
  `GET /health`, `POST /runs`, durable pending lookup, and a separate decisions
  endpoint that restores `RunState` and resumes the same run. The process boots
  degraded when infrastructure is absent, but model work is refused unless
  Neon, MCP, E2B and the skill folders are available; there is deliberately no
  SQLite or R2 shadow architecture. Added header-safe session IDs, exact
  one-decision-per-call validation, and reset of old decision metadata when a
  run reaches a second approval gate. Verified with lock check, ruff, compile,
  real `/health`, and 21 free unit/HTTP contract tests. No model or sandbox call.
- **2026-08-17 · Codex** — Baseline published before D1: local `main`
  fast-forwarded to `origin/main`, checkpoint `327d297` pushed on `deploy`, and
  draft PR #3 opened. Claude Code is paused; Codex claimed `harness/**` and is
  implementing D1 against the existing SDK 0.20.0, Neon gate, MCP tools and E2B
  sandbox architecture. No SQLite/R2 or Maya-specific tools will be introduced.

- **2026-08-17 · Claude Code** — **D4, second pass: the course's state schema is
  now the one in Neon.** Sorin's decision, taken after the companion files were
  read rather than guessed at — they were sitting in the session's own working
  directory, `C:\Users\sorin\Downloads\AI\deploying-agents`.

  Backup branch `pre-d4-course-schema-2026-08-17` (`br-billowing-forest-avqqtni2`)
  first. Then `migration_d4_course_schema.sql` (drops only, both guarded against
  running on non-empty tables) and the rewritten `schema.sql`, both through the
  **direct** endpoint.

  Code moved with it, because the CLI broke the moment the tables did:
  `audit.py` rebuilt around `open_run`/`close_run`/`event` with the vocabulary as
  shared constants; `replay.py` rebuilt on `runs` + `audit_log`; `worker.py`,
  `mcp_server/server.py`, `seed.py`, `migrate.py`, `import_books.py` and both
  paid checks updated; every statement schema-qualified; `config.migration_url()`
  added and wired into `apply.py` and `migrate.py`; `apply.py --file` implemented.
  `ruff` clean, 11 unit tests pass, all modules import, and the new schema was
  exercised end-to-end against the pooled endpoint (results above).

  **One loss carried forward, accepted knowingly:** `update_profile` can no
  longer be undone from the trail. The event says the profile changed and which
  section; the previous text is not kept. `content/profile.md` on disk plus
  `db.seed` is the remaining safety net, and it does not cover changes she made
  through the agent since the last seed.
- **2026-08-17 · Claude Code** — **The gate is back, on `public.runs`.** Sorin's
  call: six columns rather than a restored `pending_runs`. Three database-level
  guarantees (status CHECK, resumable-if-pending CHECK, one-waiting-per-session
  unique index), and `suspend_run`/`pending_run`/`resume_run` in `audit.py`,
  which raise `GateError` instead of swallowing — the only writes in the file
  that do. Verified across a real process boundary, 22 checks green. Found and
  neutralized a JSONB decoding asymmetry between bare asyncpg and the SQLAlchemy
  dialect. **Blocker 5 closed; D1 is unblocked and `harness/` is the last piece.**
- **2026-08-17 · Codex** — Re-ran `uv sync` and the complete D0 import probe
  against installed `openai-agents` 0.20.0, then compared the sandbox API with
  the live official documentation. Corrected one material brief mismatch:
  `RunState.to_string()` is synchronous; `RunState.from_string(...)` is async.
  All repository SDK imports pass. No application code changed and no paid model
  or sandbox call was made. D0 remains closed with the corrected findings.
- **2026-08-17** — Board created. D0 closed by reading the SDK source: the gate
  architecture is sound. Decisions 1–6 locked. Awaiting go on branch base and on
  the destructive schema work.
- **2026-08-17 · Codex** — Started D3 Azure access/subscription discovery only.
  No code or infrastructure zone is claimed yet. Browser work is paused because
  the ChatGPT extension and native host are not installed for Chrome; Sorin must
  reconnect the Browser plugin, then complete Azure MFA personally. Azure CLI is
  also not installed or not on `PATH`, so no CLI session can be used as a fallback.
  Codex will resume at subscription and resource inventory after authentication.
- **2026-08-17 · Claude Code** — Branch base resolved: `main` fast-forwarded to
  `english` (5 commits), `deploy` cut from it, nothing pushed. Read-only inventory
  of the live database taken and recorded above. Wrote
  `db/reset_for_deployment.sql` — not applied, waiting on a Neon branch. Claimed
  the harness, schema and worker zones; D3/Azure is Codex's. Found `E2B_API_KEY`
  missing from `.env`. Next: D1, the harness and the gate, which does not need the
  database to be migrated first.
- **2026-08-17 · Claude Code** — Correction: `E2B_API_KEY` is *not* missing; all
  four variables in `.env` are set. Blocker 4 withdrawn. Blocker 2 re-diagnosed:
  the Neon MCP server is declared in this repo's `.mcp.json` but never loaded,
  because the session's working directory is elsewhere — see above for the two
  ways out. Starting D1.
- **2026-08-17 · Claude Code** — D1 design settled by tracing the SDK: the harness
  must pass `SandboxRunConfig(client=…, options=…)` and **never** `session=`,
  or the sandbox resume payload is silently dropped. Written up under D0 findings
  with the exact call chain. No harness code written yet; next session starts
  with `harness/pending.py` and the `pending_runs` table.
- **2026-08-17 · Claude Code** — **The migration ran.** Neon branch
  `pre-deployment-2026-08-17` taken and verified first; then the four foreign
  keys, the two table drops and the truncations, all through the Neon MCP server.
  Verified after: 17 documents, 4,778 embeddings still joined to a real document,
  the HNSW index intact, the profile at 30,748 chars.

  Then the code that depended on the dropped tables, since the CLI was broken the
  moment they went:
  - `schema.sql` rewritten — `conversations` and `capability_invocations` gone,
    `embeddings.document_id` NOT NULL, `pending_runs` added, and the audit
    vocabulary widened with **`approval_granted`** (in the terminal a "yes" left
    no trace of its own; over HTTP it can arrive an hour later from another
    device, so it gets its own row).
  - `worker.py` — session resume moved onto the SDK's `agent_sessions`; the
    cover-sheet writes are gone; a granted approval is now audited.
  - `audit.py` — the second call log is gone; `capability_blocked` writes only
    the trail.
  - `conversation.py` and `tests/unit/test_conversation.py` **deleted**.
  - `replay.py`, `db/apply.py`, `db/migrate.py` (the `backfill` subcommand had
    nothing left to fill in), `tests/checks/write_gate.py`,
    `tests/checks/full_flow.py` — all read the trail now.

  One trap worth knowing: deriving "was this call refused" from the trail cannot
  just look for a `status` key, because `search_web` returns a `status` of its
  own. The test is an exact match on `status = 'blocked'`, so a failed web search
  still counts as a call that was allowed — which is how the dropped table
  counted it too.

  Verified: `ruff` clean, 11 unit tests pass, `db.apply` idempotent against the
  live database, `open_session` resumes correctly on an empty `agent_sessions`,
  `replay --list` and `migrate rename` both fine. No model call, no sandbox, no
  money spent. **Next: `harness/` itself.**
- **2026-08-17 · Claude Code** — D4's schema half closed properly: the database
  was checked by exercising it, not by reading it. Full table above. Two things
  came out of it — the constraint names were still Romanian on `clients` and
  `posts` (now renamed, idempotently, from `schema.sql`), and the earlier claim
  that one post existed only in the database was wrong: all 27 are in
  `content/posts/`, so `db.seed` can restore them if the client wants that memory
  back. A throwaway branch `schema-check-tmp` (`br-ancient-night-avt8x3uj`) still
  exists and can be deleted; the backup `pre-deployment-2026-08-17` must stay.
  Still no model call and no sandbox.
- **2026-08-17 · Codex** — Azure portal access is now working in Chrome. The
  account explicitly reports that the current sign-in used multifactor
  authentication. Azure Free Trial is now active: the portal shows one active
  subscription (`Azure subscription 1`), Owner RBAC access, and USD 200 credit
  remaining. Billing scopes also confirm `Billing account owner` on the active
  Microsoft Customer Agreement account. The free-account spending limit is
  present. Its direct removal blade emits a stale/generic `Account Administrator`
  authorization message; for a Free Account the supported removal path is an
  upgrade to pay-as-you-go, so this is not evidence of missing admin rights. Do
  not upgrade and do not purchase separately billed Marketplace/support products.
  D3 is now unblocked for a 30-day deployment test using first-party Azure
  resources covered by the credit. Without a pay-as-you-go upgrade, Microsoft
  says the services do not continue after the credit is exhausted or day 30; the
  advertised 12-month free quotas require moving to pay-as-you-go. A permanent
  deployment therefore still needs a later billing/subscription decision. No
  Azure resource or infrastructure file has been created or changed yet.
- **2026-08-18 · Claude Code** — The dashboard shell is implemented and the
  generator was proved end to end, with money spent by Sorin's explicit
  decision. Two real batches, one save through the gate.

  **The shell.** `MainLayout.razor` and `PrimaryNav.razor` were rewritten around
  a 250px left rail with two labelled groups; the topbar is gone and its halves
  moved into the rail. `app.css` got the warm-dark palette and 67 light-theme
  colour values were mapped onto it. The four page components were not touched.
  Decisions and the three things the port surfaced are in
  [plans/design/README.md](design/README.md).

  **The bug behind "nu am putut genera".** Two coupled defects in
  `mcp_server/generation_store.py`. `fail_idea(retryable=False)` set the whole
  batch to `failed`, and `REFRESH_BATCH_STATUS_SQL` promoted a batch to `ready`
  only when all ten ideas were ready. Together, one idea that exhausted its
  retry made the other nine unreachable — the live batch had **eight ready ideas
  behind a failed batch status**. A batch is now finished when every idea has
  settled, `ready` if at least one succeeded, `failed` only if none did. Proved
  by running the new rule against the existing eight-ready batch: `generating` →
  `ready`, no model call. Seven new tests in `tests/unit/test_generation_status.py`.

  **D7, second half.** `generator.py` caught every batch and idea failure and
  turned it into a safe Romanian sentence without logging it, so the first failed
  batch could only say `RuntimeError`. Both boundaries now `logger.exception`
  first. That is how the `ModelBehaviorError: Invalid JSON` above was found at
  all. `service.py` got the same treatment earlier.

  **The gate, end to end, on live data.** Variant selected → `Pregătește
  salvarea` → the run interrupted on `save_posts_batch` and persisted **48,811
  bytes of `RunState`** into `public.runs` with `status='pending'`, while
  `posts` stayed at 0 and `audit_log` recorded `approval_requested`. After
  `Confirmă`: `approval_granted` → `post_saved` → `capability_invoked`, run
  `completed`, `posts` at 1. This is the D0 serialization question answered on
  production data, not a probe.

  **Language.** "1 postări" and "1 salvate" were wrong. `RomanianText.cs` now
  handles agreement including the "de" rule from twenty upwards; the chip reads
  "o postare salvată".

  **Verified:** `ruff` clean, 95 unit tests pass, all four pages driven in a real
  browser at 1280 and 375, zero WCAG AA contrast failures across 109 measured
  text nodes, no horizontal overflow.

  **Open, needs Sorin's call — quality, not correctness.** The detail model
  (`gpt-5-mini`) returned invalid JSON on 2 of 10 ideas even after the one retry
  each gets, and titles 6–10 of that batch came back as structure labels ("Hook
  principal", "CTA-uri pentru Reel") rather than ideas. Neither is a crash and
  both are now survivable, but a batch that loses a fifth of its output is worth
  a prompt or retry-budget change. More attempts cost more money per batch, so
  that is a decision, not a fix.
- **2026-08-18 · Claude Code** — Reels are silent. On Sorin's instruction, a Reel
  no longer carries a script or a production block; everything the voice-over
  would have said is written into the caption instead, and the caption grew to
  match.

  **Why this is a contract change and not a prompt tweak.** The detail phase asks
  the model to fill one exact schema. If the schema still had `script` and
  `format_details`, the model would still fill them — and the two fields would
  still reach the row and the page. So the schema is now chosen by format:
  `detail_output_type("Reel")` returns `SilentReelDetails`, whose variants have
  no such fields at all, and `ProducedIdeaDetails` keeps them required for
  Carusel and Stories. `IdeaVariant` stays the permissive shape underneath,
  because it is what reads both back.

  **The caption.** The silent reel's floor is 200 characters, against 3 for the
  produced formats, and `SILENT_REEL_BRIEF` asks the model for 900–1400: the hook
  idea entered directly, two to four short paragraphs, the engagement question at
  the end. The floor is a guard against a degenerate answer, not the target — the
  measured evidence is that the three posts saved before this change have
  captions of **145, 159 and 178 characters**. All three would fail the new floor.

  **What holds it in the database.** `generation_variants_ready_is_complete` used
  to demand a script and a production block on every ready variant. A check
  constraint cannot see the batch's format from that table, so it now enforces
  the pair instead: `(script IS NULL) = (format_details IS NULL)`. Half a
  production block is the one state that means nothing. Nothing already stored
  violates it. `SavedPostContent` makes both optional and deliberately does *not*
  couple them, because her posts imported before the production block existed
  have a script and no `format_details`, and the editor has to open those too.

  **Elsewhere.** `as_markdown` no longer prints a `## Script` or `## Producție`
  heading it cannot fill — `body_md` has to be what the columns hold. The chat
  patch keeps the permissive contract but `content-data` now refuses a rewrite
  that adds or removes a script, in the same style as the existing hook-type
  guard, and the prompt tells the model when the target is silent. `save_post`
  in the CLI takes `script` last and optional, so both fronts tell the same
  story. Generator and Saved render the two sections on presence rather than on
  format, so a post written before today still opens with everything it has.

  **Verified without spending anything:** `ruff` clean; 105 unit tests (96 + 9
  new) and 7 .NET contract tests pass; both schemas survive the SDK's strict-JSON
  conversion, with the Reel one carrying `required: [hook_type, hook, caption,
  hashtags, cta, source]` and no script; the live constraint was replaced by
  `db.apply` and 0 stored rows violate it; and a full silent reel was driven
  through the real database — batch → titles → five variants → select → save into
  `posts` — inside a transaction that was then rolled back, confirming
  `script IS NULL`, `format_details IS NULL` and a `body_md` with neither heading.

  **Not yet done:** no real generation batch has run against the new contract, so
  the caption length and quality are unproven against the model. That costs money
  and is Sorin's call.

- **2026-08-18 · Claude Code** — **Debugging made real, and the code documented in
  Romanian, both aimed at D2.** Sorin asked to test with a debugger and to have a
  tutorial before we containerize.

  **What was actually broken.** `docs/TESTING.md` still told you to pick a compound
  named `Server + Worker`, which stopped existing when the three-service compound
  replaced it, and its breakpoint table only covered the CLI era — nothing about the
  harness, the generator or the chat path. The CLI debug configuration itself had
  been lost in the same edit. Fixed both: `launch.json` now carries **CLI worker**,
  **Unit tests** and **Attach to a running process** beside the original three, plus
  a second compound `Terminal (MCP + CLI)`.

  **The attach path, which is the one that matters for the container.** New
  `src/content_studio/debug.py`: with no `DEBUGPY_PORT` in the environment it returns
  after one `os.getenv`, so it is safe in the startup path of both entry points; with
  one, it opens a debugpy listener on `0.0.0.0` — loopback would be unreachable from
  outside a container. `debugpy` added to the dev group. Two things were found by
  running it rather than by reasoning about it: the call had to move from
  `harness.main.run()` to module level, because uvicorn is handed the import string
  `…main:app` and never calls the console entry point (locally *and* in the image);
  and every message needs `flush=True`, because stdout under a pipe is buffered and
  the listener was up while its announcement was still in the buffer. Verified live:
  both services started with a port set, `content-data: debugger listening on port
  5679` and `harness: debugger listening on port 5678`, both adapters bound, and
  `/health` still `ready` on all four required backends.

  **A finding worth deciding before D3.** `/health` returned `degraded` on the first
  call after Neon had been idle, and `ready` on the second. `HarnessService.health`
  probes Postgres under `asyncio.timeout(3)` and the Neon compute takes longer than
  that to wake. Harmless locally; in Azure a liveness probe pointed at `/health`
  would flap a cold replica. Either the probe does not point there, or the timeout
  rises. Not changed unilaterally — it is a deployment decision.

  **The tutorial.** `docs/tutorial-ro.html`, ten chapters, Romanian, sharing the
  stylesheet of the English `docs/tutorial.html` so the two read as one set. It
  describes the system as it is now — three processes but two containers from one
  image, the 22 thin routes over a thick `service.py`, the generator's two stages,
  where the silent reel's contract is chosen — and it is written towards D2: a
  chapter on what enters the image and what must not, a table of every environment
  variable with which service needs it and whether it is a secret, and the traps
  (Neon's cold start, frozen modules, buffered stdout, the statement cache and
  PgBouncer). Structure validated: tags balanced, all ten table-of-contents anchors
  resolve.

  Corrected while writing it: the gate's durable home is `public.runs` with
  `status='pending'`, not the `pending_runs` table the plan named — D4 folded it in.

  **Verified without spending anything:** `ruff` clean, 105 unit tests pass, both
  services start under a debugger, `/health` `ready`. **Not done:** no model call was
  made, so nothing here proves a turn behaves under the debugger — that costs money
  and is Sorin's call. Nothing was committed.

- **2026-08-18 · Claude Code** — **The compound could not start: the Blazor entry
  needed an extension nobody had.** Pressing `F5` on `Studio complet (3 servicii)`
  raised *Configured debug type 'coreclr' is not supported*. MCP and the harness came
  up; the third configuration died on the dialog. No .NET extension is installed —
  zero of the fifteen in the editor are `ms-dotnettools.*`.

  Installing the C# extension would have removed the dialog and bought nothing.
  `coreclr` would attach to the Blazor **DevServer**, which is a static file server;
  the application itself runs in the browser's WebAssembly runtime, out of reach of a
  .NET debugger on this side. So the entry is now `node-terminal` — a type that ships
  inside VS Code, needs no extension, and does the only thing that process needs: run
  the command and stop with the rest of the compound. The C# that executes in the
  browser is debugged from the browser's devtools, which is where it always was.

  **A second compound, aimed at D2: `Studio ca in container (MCP + harness)`.** It
  runs the new `.vscode/tasks.json` task to publish the UI, then starts only the two
  Python processes; FastAPI serves `ui/StudioViorela/dist/wwwroot` at `/`. **Zero
  .NET processes — exactly the shape of the image.** Anything that breaks about the
  served build (base href, fingerprinted assets, SPA fallback) now breaks here, on
  `8000`, before it breaks in Azure.

  **The publish on disk was stale and dirty.** `dist` dated from 11:20 while the
  Razor sources had moved to 13:36 — the silent-reel UI was simply not in it — and it
  had accumulated **three** fingerprinted copies of the application assembly, because
  `dotnet publish` never cleans. Rebuilt from an empty `dist`: one assembly, 135
  files in `_framework`, 18 MB. **`.dockerignore` must exclude `ui/**/dist` too**, or
  the image copies whatever an old build left behind — one more line for D2 than the
  tutorial's chapter 07 currently lists.

  **Verified on the served path, free:** a throwaway harness on port 8010, chosen so
  it would not take `8000` from the editor — `/` returns the Blazor index, the
  fingerprinted `_framework/StudioViorela.*.wasm` returns 200, an unknown route falls
  back to the SPA, `/health` `ready` on all four backends. Stopped afterwards; the
  MCP server on 8765 belongs to Sorin's own debug session and was left alone. No
  Python changed, so no lint or unit run was warranted.

  Docs follow the code: `docs/TESTING.md` gains the compound and the reason the
  Blazor entry is not a debugger (and loses one more `pending_runs`, corrected to
  `public.runs`), `README.md` says no .NET extension is needed, and the tutorial's
  chapter 01 explains why — the same sentence that makes Blazor build-time rather
  than runtime is what makes it undebuggable from this side. Nothing committed.

- **2026-08-19 · Claude Code** — **MCP 2.0 decoding bug fixed; a second gated-write
  bug found and fixed, this time in the D1b generation path; two real generation
  batches run.** Session handoff notes are in
  [plans/PREDARE.md](PREDARE.md) — this entry covers only what changed the code
  and what money proved.

  **The decoding bug.** `mcp` 2.0.0 renamed `CallToolResult` fields to snake_case;
  `drafts.py` still read `isError`/`structuredContent` through a bare `getattr`
  with a default, so every field silently read as absent instead of raising —
  worst case, a real `content-data` error decoded as success. Fixed with
  `_result_field(result, snake, camel)`, accepting either spelling. The old test
  suite could not have caught this: it built `SimpleNamespace` fixtures under the
  same wrong names the bug expected, so bug and test confirmed each other. Tests
  now use the real field names plus a `RealResultTests` class built on an actual
  `mcp_types.CallToolResult`.

  **The gated-write bug — reproduced with real money.** A fresh 10-idea batch
  failed in 15 seconds: `RuntimeError: structured generation unexpectedly
  requested approval for: update_profile`. The title agent (`gpt-5-nano`, minimal
  effort) reached for a write tool instead of returning the structured contract.
  The approval gate itself worked exactly as designed — `update_profile` is in
  `GATED_TOOLS` with `require_approval`, and nothing wrote silently — but D1b's
  generation path has nobody on the other end to answer an approval request:
  `Runner.run` in `generator.py` has no approval loop, so any interruption fails
  the whole batch. The fix is narrower than the gate: the generation agent never
  needed `update_profile`/`save_post`/`save_posts_batch`/`update_post` visible at
  all, since saving is a separate, later, explicitly-confirmed phase. New
  `GENERATION_VISIBLE_TOOLS` (`search_books`, `search_web`, `list_posts` only) and
  a dedicated `_generation_data_mcp` connection in `service.py`, used by
  `GenerationCoordinator` instead of the chat-shared `_data_mcp`. Chat keeps the
  full set unchanged, since a person is actually there to answer.

  **Verified with real money, twice, end to end.** Before the fix: a 10-idea
  batch failed in 15s with the `update_profile` error above, zero ideas
  persisted. After the fix: a 10-idea batch (pillar Educație, format Reel, source
  Memorie) reached `status: ready` in 135 seconds — **10/10 ideas, 50/50
  variants, zero failures, zero errors in the server log**. Confirmed separately
  that `generator.py` never calls a write tool directly, so restricting model
  visibility could not have broken a legitimate path. `ruff` clean, 107 unit
  tests pass both before and after. Committed and pushed to `deploy`: `bfc941d`
  (the tool-visibility fix) and two earlier same-session commits for the decoding
  bug and the debug-configuration fixes below.

  **Also fixed this session, same money-free verification standard (ruff +
  107 tests):** the debug attach configurations carried `pathMappings` toward
  `/app/src`, correct for the container but wrong for a local process, which
  reports real Windows paths — breakpoints could bind to nothing. Split into
  `Attach: harness (local)` / `Attach: MCP server (local)` (no mapping) and
  `Attach: harness (container)` (mapping kept, for D2). Added a `tasks.json`
  sweep step, `Oprește serviciile Studio`, that kills this workspace's leftover
  Python/dotnet processes before starting new ones — stopping a debug session
  detaches the editor but leaves the terminals running, so the next `F5` was
  silently re-attaching to stale processes. The `-Xfrozen_modules=off` question
  left open in a prior session's handoff is closed: confirmed present in the
  real command line of both running processes via `Get-CimInstance
  Win32_Process`; it was never the cause of the missing debug session that
  night — the debug session had simply never been started (the extension's own
  log was empty).

  **Database reset, twice, at Sorin's request.** `TRUNCATE ... RESTART IDENTITY
  CASCADE` on `posts`, `generation_batches/ideas/variants`, `runs`, `traces`,
  `artifacts`, `audit_log`, `agent_sessions`, `agent_messages` — `clients`,
  `documents`, `embeddings` untouched both times. A Neon branch,
  `pre-curatare-2026-08-19` (`br-crimson-tree-av5gp1yn`), was created before the
  first truncate as a safety net.

  **Left for a human decision, not resolved:** the top-of-file roadmap table
  still read D1 as "paid live round trip stays at the testing stage" and D1b as
  "two paid acceptances remain" despite an earlier 2026-08-18 changelog entry
  documenting both a real 10×5 hybrid batch and a real save through the gate
  (`RunState` persisted at 48,811 bytes, `approval_granted` → `post_saved` →
  `completed`, `posts` at 1) — the summary table was simply never updated
  after that entry landed. Updated both rows below to match the evidence
  already in this changelog. One acceptance still has no clear evidence either
  way: a real **rewrite** through the gate (editing an already-saved post, not
  just saving a new one) — every gate proof found in this file is a save, not a
  rewrite.
