# Architecture

Why this is built the way it is. The rules themselves are in
[AGENTS.md](../AGENTS.md); this document explains the domain they serve and the
reasoning behind each structural choice.

The original planning document, written in Romanian while the system was being
designed, is kept as [plan-ro.md](../plans/plan-ro.md). It has the day-by-day reasoning,
including the parts that were later abandoned.

---

## 1. The problem

A life coach publishes short-form content — reels, carousels, stories — for women
trying to get out of people pleasing, burnout and self-sabotage. The content has to
sound like her, follow a method she was taught, and draw on a private library of 17
books she has read and annotated.

Doing that in a chat window has three failure modes, and all three are quiet:

- **The voice drifts.** Generic AI phrasing creeps in and the post stops being hers.
- **Facts get invented.** A figure that sounds like a study, a page number that does
  not exist, a quote attributed to a book that was only ever a summary.
- **Nothing accumulates.** Every session starts from zero. The nine proposals she
  rejected — the best available signal about her taste — are lost each time.

The design answers those three, in that order.

## 2. The shape

One `SandboxAgent` definition. Its system prompt is assembled from four parts, and
each is written from what is actually attached rather than from what was true when
the string was last edited: who the assistant is and whose voice it writes in
(`BASE_INSTRUCTIONS`), that the method is mandatory (`skill_method_note`), the
tools this particular run can see (`data_tool_note`, read off the server's own
filter), and the client's profile, 28,639 characters of it, read over MCP at
startup.

**There are no output rules in the prompt.** Ten of them used to live there. They
came out on 2026-08-24 and were deleted on 2026-08-26: they were 3,800 tokens
above a schema that enforces the same things better, because OpenAI enforces
`enum`, `pattern` and `minLength` *while the model writes*. What the model is
allowed to produce is now the skills plus the generation schemas — see
[AGENTS.md](../AGENTS.md), the "Where each truth lives" table.

Two folder-shaped skills mounted into E2B. Ten model-visible tools and 25 internal
UI operations, reached over HTTP from a purpose-built MCP server. One Postgres
database behind that server, plus two direct connections the harness keeps only
for SDK conversation memory and the approval/audit trail.

```
The client
    │  Blazor WebAssembly, Romanian — buttons and chat, ONE conversation
    ▼
FastAPI harness ─── the front door and the run lifecycle
    ├─ trusted identity (local loopback or Azure Easy Auth headers)
    ├─ structured profile API + approval resume
    ├─ title-first generation + SSE
    ├─ saved posts: batch save and rewrite, both through the same gate
    ├─ internal `ui_*` MCP operations ─► durable generation drafts
    │
    ├─ builds and runs ─► one SandboxAgent  (definition: worker.py)
    │       system prompt = voice + method note + tool note + her profile
    │       │
    │       ├─ shell ─► E2B container, one per run, `.agents/`
    │       │             ├─ skill: propune-postari
    │       │             └─ skill: dezvolta-postarea + references/
    │       │
    │       └─ MCP over HTTP ─► the tools below
    │
    └─ MCP server `content-data`
         ├─ internal resource: the live profile (not a tool the model can call)
         ├─ search_books      ─► OpenAI embedding + Neon pgvector
         ├─ search_web        ─► OpenAI web search, metered like every other call
         ├─ list_posts        ─► Neon
         ├─ start_generation  ─► records the intent; the harness runs the batch
         ├─ develop_idea      ─► records the intent; the harness runs the detail
         ├─ select_variant    ─► marks her chosen variant on the current batch
         ├─ save_post         ─► Neon, only after approval
         ├─ save_posts_batch  ─► Neon, only after approval, all or none
         ├─ update_post       ─► Neon, only after approval
         └─ update_profile    ─► Neon, only after approval

audit.py ─── own connection ──► messages, skills, calls, approvals, results
```

The three trigger tools are how the chat door reaches the same pipeline the
buttons use: the model records an intent, the harness executes it. None of them
writes her content, so none is gated — the one confirmation stays on saving a
post. See [AGENTS.md](../AGENTS.md), "One conversation, two doors".

**Why the profile is a resource and not a tool.** It has to be in the system prompt
before the agent can do anything, and it must never be something the model decides
to fetch. As an MCP resource it is read programmatically at startup, by whichever
door is starting the run, which still runs no SQL of its own.

## 3. The data model

Two halves: the domain, which is this project's own, and durable state, which is
the deployment crash course's five-table model adopted whole at D4.

**The domain.**

| Table | Holds | Note |
|---|---|---|
| `documents` | the library, one row per book | provenance lives in `metadata`, per row |
| `embeddings` | 4,778 chunks, 1536 dimensions, HNSW index | one link, to a document, enforced by NOT NULL since Decision 11 |
| `clients` | one content column, `profile_md` | it lives here rather than in embeddings because it is the only material that gets *written to*: you cannot UPDATE a vector |
| `posts` | the finished posts | in the dozens, so "have I written about this?" is a WHERE, not a vector search |
| `generation_batches` | one current unsaved batch per authenticated principal | survives refresh. `source_packet` is a dead column kept for the old rows: since 2026-08-27 nothing pre-collects material, the agent fetches its own |
| `generation_ideas` | exactly ten title/angle rows | each reports its own generation and retry state |
| `generation_variants` | five complete hook variants per idea | written lazily, only for the idea she opens; at most one selected variant per idea |
| `conversations` | which session is active per account, and which batch was born in it | **not** the table Decision 11 removed — that one duplicated the messages. This one holds what `agent_sessions` cannot express |
| `app_users` | principal → client | a *link* table: several principals may point at one client, because a principal id belongs to the identity provider, not to a person |
| `usage_events` | one row per model call, in integer micro-dollars | no floats anywhere near money; `cached_input_tokens` is the evidence for the tenth-rate cache reads |

**Durable state** (D4). Every statement names its schema — `public.runs` — because
Neon's pooled endpoint makes no promise about `search_path` surviving between
transactions.

| Table | Holds | Note |
|---|---|---|
| `runs` | one row per turn: the message in, the answer out | `session_id` points at `agent_sessions`, the SDK's own and the **only** session table |
| `traces` | **two kinds of row per run** | what was answered, written by `close_run`; and how it was reached — the agent's own spans, collected by `RunTraceProcessor` since 2026-08-23. Same `run_id`, which is what makes them one story rather than two tables |
| `artifacts` | pointers to files in object storage | empty until D5 decides on R2. A post is *not* an artifact |
| `audit_log` | the replayable trail | `(run_id, event)`; `event` is free text, so the vocabulary is a shared constant in `audit.py`, not a CHECK |

Sixteen tables in all: the fourteen above plus `agent_sessions` and
`agent_messages`, which belong to the SDK and are the **only** session tables —
`runs.session_id` points at the SDK's, rather than a second one of ours.

`capability_invocations` went at Decision 11, a second copy of a truth another
table already held; `pending_runs` went at D4 with the rest of the old state
half. A `conversations` table went at Decision 11 too and a different one came
back on 2026-08-27 under the same name — that near-duplicate held the messages,
this one holds the active pointer. The gate moved onto six columns of
`public.runs`: a pending run keeps
its serialized `RunState`, every approval request, and later every decision. A
database constraint forbids `pending` without resumable state, while a partial
unique index allows at most one pending run per session.

What the trail no longer keeps: the arguments a tool was called with and what it
returned. A row says `capability_invoked: save_post`; the post itself is in
`posts`, and the message and answer are columns on `runs`.

`posts.body_md` keeps each source file whole alongside the parsed columns. The
existing posts came in three different shapes; a parser that splits them into columns
loses whatever it does not recognize, and that loss would be silent.

### The HTTP control plane (deployment D1)

The FastAPI harness is the cloud-facing front door and owns the run lifecycle;
E2B is only where the method is read from. **Every run gets its own container,
opened as a live session** — `content_studio.sandbox.sandbox_run_config` — and
closed when the run ends. Measured 2026-08-27: a container comes up in
0.35–1.17s, which is small next to the model call it serves.

A live session means `RunState` carries no sandbox payload (the SDK returns
`None` for the resume state when it did not create the session), and that is
correct here rather than a limitation: the container holds read-only method
files that no run mutates, so an approval resumed minutes later is given a fresh
one and reads exactly the same method. Verified end to end on 2026-08-27 —
`save_posts_batch` gated to `pending`, approved, resumed from `RunState`, post
written.

| Endpoint | Contract |
|---|---|
| `GET /health` | reports OpenAI, Postgres, MCP, E2B and artifact backends without a model or sandbox call |
| `POST /runs` | starts or continues a session; returns `200 completed` or `202 pending` |
| `GET /sessions/{session_id}/pending` | restores the approval screen after refresh or scale-to-zero |
| `POST /runs/{run_id}/decisions` | requires one decision per interrupted call and resumes that exact run |

Authenticated Blazor routes use `/api/*`. `GET /api/me` exposes only the trusted
identity, profile reads return structured blocks rather than raw Markdown, and
profile writes still become a normal interrupted `update_profile` call. Generation
uses `/api/generation-batches`, per-batch reads/cancel, one variant-selection
operation and an SSE event resource. Chat starts through `/api/chat/runs`, streams
through `/api/runs/{run_id}/events`, and can be stopped explicitly. The browser
supplies only a typed target ID; the server verifies its ownership through
`content-data`. Text deltas are exposed immediately, while a structured draft
patch is persisted only after the complete object validates. The browser never
supplies the audit actor.

Production identity comes from Azure Container Apps Easy Auth headers, and since
2026-08-21 the studio is multi-tenant in fact rather than only in the schema.
**One account is one `clients` row** — it owns the profile, the lifetime budget in
integer micro-dollars, the usage and the shelf — and `app_users` links principals
to it. Google principals are authorized off the deployment allow-list; principals
from the Entra external tenant carry their own (see §6). An authenticated
principal with no `app_users` row is told its account is not set up yet; only the
address in `CLIENT_OWNER_EMAIL` may fall through to the original client, and that
fall-through now *writes* her row, so the admin page can act on her account like
anybody else's. `provisioned()` has three answers, not two — True, False, and None
when the data plane could not be asked — because refusing on None would turn one
bad minute into everybody locked out of their own studio. Development auth refuses
non-loopback binding and refuses to run when Azure environment markers are present.

The process may boot in a degraded state so Azure can expose diagnostics, but it
does not fall back to SQLite: a run is refused unless Neon can hold the approval
gate durably. R2 is likewise not faked locally; it remains the explicit D5
decision, and `posts` are domain rows rather than artifacts.

## 4. The flow: one method, two passes, and the second one is lazy

Four answers start a batch — **format**, **pillar**, **source**, and an optional
**focus**. The buttons collect them in a form; chat asks for whatever is missing
and then dictates the same sentence. Nothing else is collected: since 2026-08-27
there is no source packet and no book picker, because the agent brings its own
material with its own tools, following the skill. `drafts.create(...)` passes an
empty packet on purpose.

1. **Titles.** One run returns exactly ten persisted title/angle rows.
2. **Detail, on demand.** A second run develops **one** idea into all five hook
   variants — and only when she opens that idea.

**Why the detail phase is lazy.** The batch used to write all ten as soon as the
titles landed. That is where nearly the whole cost of a run sits — $0.0733 of a
$0.0770 batch, measured 2026-08-24 — and she develops one. The other nine were
paid for, stored, and never opened. Everything a detail run needs is read back off
the batch rather than held in memory, so it can be asked for days later, from a
different replica, and produce what the batch would have produced then.

Both phases run on `gpt-5-mini`, which since 2026-08-27 is the only model the
interface offers: the method is read from files in a sandbox, and `gpt-5-nano`
could not drive the shell that opens them — it wrote ten plausible titles without
ever reading the method. See AGENTS.md, rule 4.

**The two phases have different reasoning budgets, and that is a setting rather
than a sentence in the skill.** Phase 1 stays at `"minimal"`: it opens no files,
so there is nothing for extra reasoning tokens to buy. Phase 2 is at `"low"`,
because it has two errands before it writes — the format's reference file and the
source's tool — and at `minimal` 15 of 16 measured runs did exactly one of them
and stopped themselves well under the turn limit. `parallel_tool_calls=True` is
explicit for the same reason: the default is `None`, and `None` omits the field,
so the model was never invited to batch its two errands into one turn.

SSE publishes the durable states. Refresh reads the same batch from Neon. A failed
idea retries without discarding the other nine.

**Phase 1 — `propune-postari`.** Ten proposals, each a short title plus the angle
in a sentence or two. Ten and only ten, and different from each other by
construction: `ANGLE_TYPES` gives ten archetypes for ten slots, so "make them
different" stops being a request and becomes arithmetic. The hooks are *not* here
— they belong to phase 2, one set of five per idea.

**Then she chooses** which proposal to develop. The agent never picks for her.

**Phase 2 — `dezvolta-postarea`.** The chosen proposal becomes a full post: hook,
caption, 3–5 hashtags, the CTA from her profile, and at Carousel and Stories the
script as well — five complete variants, one per hook type, from which she selects
one. Nothing is saved until she says yes.

### The five pillars

Positioning 🎯 · Education 📚 · Connection 🤝 · Conversion 💰 · Magnetism ✨

They belong to the method, not to the client, which is why they live in
`skills/propune-postari/SKILL.md` and not in the database. They used to be a
`references/` file; they were folded into the body on 2026-08-27, under the rule
that always-required method is body and only *conditional* method travels as a
reference. `propune-postari` has no `references/` directory at all now. If this
system reaches a second coach tomorrow, the pillars travel unchanged.

### The five hook types

Every proposal carries exactly five, one of each, none repeated: **PROVOCARE**
(direct challenge), **CIFRĂ** (a concrete number and its consequence), **SECRET**
(what nobody says out loud), **ÎNTREBARE** (an uncomfortable question), **CONTRAST**
(before versus after).

### The four sources, and what each may give

| Choice | From | May give | May **not** give |
|---|---|---|---|
| 📚 Books | `documents` + `embeddings`, via `search_books` | idea, frame, quote — with title, author, page | to be presented as "this is how it is done"; to be credited with something it does not say |
| 🌐 Internet | `search_web`, via the Responses API | an angle, a seasonal theme, what is being discussed now | figures, studies, quotes — nothing from the web enters as fact |
| 🧠 Memory | the profile plus what the model knows | structure, phrasing, ordinary-life examples | any figure, study, name or claim presented as verified |
| 🔀 Combined | several of the above | whatever each gives | the restrictions add up, they do not cancel out |

**When two sources disagree**, the higher rung wins — but only when both are
actually answering the same question:

1. the client's profile, including "things you never say"
2. the method (format, structure, filming)
3. the 17 books — a source of angle, never of rule
4. the internet — angle and currency, never fact
5. the model's memory — structure and phrasing, never assertion

**The source is always recorded** on the saved post, in the `source` field and
nowhere else — never in the hook, the script or the caption. It is social media, not
a paper with a bibliography.

## 5. The choices worth defending

**One agent instead of a crew.** The two phases were an obvious place to split into
two agents. They are skills instead, because splitting means copying the
28,639-character profile and her voice rules into a second context, and because the
handover between phase 1 and phase 2 is exactly where a rejected proposal list would
get lost. The cost is real: a `SKILL.md` cannot *enforce* ten proposals. What is
genuinely checkable therefore moved into the **output schema**, where OpenAI
enforces it while the model writes; the rest is judged in the evals.

**Skills as folders, disclosed progressively.** The index — name, description, path —
is always in context and costs almost nothing. The body opens when the task matches
the description. The references open only when the body points at them. This means
the description is not documentation, it is the trigger: it decides whether the skill
fires at all. `evals/route/` grades exactly that, square by square across the
domain, and `evals/experiment.py` carries it as the `router` score.

**Data only through MCP.** The worker could open a connection and query the profile
directly in three lines. It does not, for two reasons. The agent has a shell inside
the sandbox, so anything the worker can reach is one prompt injection away from being
reachable by the model; and a tool boundary is the only place a gate can sit
honestly. The absence of a `run_sql` tool is the rule that makes the other rules
enforceable.

**The audit commits with the write.** Two statements, one transaction. An audit
written afterwards misses exactly the events worth explaining — the ones where
something failed halfway. For the same reason the trail row for an incoming message
is written *before* the model runs, so a turn that dies still leaves evidence that it
existed.

**The gate on the registration, not in the tool.** `require_approval` is configured
on the MCP server registration in the worker. If it were a check inside the tool
body, it would be one prompt away from being talked around, and it would not cover a
tool added later. On the registration, it stops the call before it happens, for every
write tool, regardless of what the model was told.

**One embedding model, recorded per row.** Storing with one model and searching with
another returns plausible nonsense — ranked, confident and wrong. There is no error
to catch, so the defence is structural: the search code imports the model name from
the script that wrote the vectors, and every row carries the model it was made with,
so the database can be asked which rows are stale.

## 6. What was deliberately not built

- **Vector search over the posts.** In the dozens, a `WHERE` on title, pillar and
  date answers the question. It becomes worth it in the hundreds.
- **Public registration.** Two identity providers are supported and neither of them
  lets a stranger in. Google principals must be on the deployment allow-list.
  Principals from the Entra external tenant named in
  `AUTH_SELF_PROVISION_PROVIDERS` skip that list — membership of a directory only
  Sorin can add people to *is* the list — and get a `clients` row on first request,
  always role `user`, always the default allowance. That rests entirely on
  self-enrolment being off in the tenant; adding Google to the same setting would
  hand a studio to anyone with an email address. **Addresses are never matched
  across providers**: the same string from Google and from the tenant is two people
  with two studios. See [../plans/ACCOUNTS-OIDC.md](../plans/ACCOUNTS-OIDC.md).
- **Anything shared between accounts.** Since 2026-08-21 the library is scoped too:
  `documents.client_id` is NOT NULL and both readers join through `clients` on the
  slug from the connection. A new account starts with an empty shelf on purpose —
  the books are licensed material, and copying them onto a tester's shelf should
  take a decision rather than a checkbox.
- **Uploads and dictation.** The Library route and streaming chat exist, but
  original-file storage, extraction, embeddings for new files, chat attachments
  and Romanian audio transcription stay behind the later media checkpoint.
- **A tool for the profile.** It is a resource precisely so the model cannot choose
  to call it.
- **Anything from the project mounted into the sandbox except `skills/`.** `.env`
  holds the database password and the agent has a shell.

## 7. Where the ugly cases live

Not in a file of hand-written cases any more. Fifteen of those existed until the
suite moved onto real traces; what replaced them measures the same failures against
every combination the interface can produce, and against runs that actually
happened. [../evals/README.md](../evals/README.md) is the map, and the group name
is the question.

| Group | The question | Pyramid layer |
|---|---|---|
| `route/` | did it open the right `SKILL.md`, the right references, and call the right tool? | 4 — tool use |
| `skill/` | did the search bring back material this brief can use? | 6 — RAG |
| `path/` | does one request said ten ways walk one path? | 5 — trace |
| `experiment.py` | all six scores against one Phoenix dataset, comparable over time | 8 — regression |

`experiment.py` is the door: it imports the other three rather than restating
them, so a label exists in exactly one place. Three further groups were removed on
2026-08-30 with their numbers already two architecture changes out of date —
`runs/` (what a real run did, read back out of `public.traces`), `retrieval/`
(does the shelf return the right book) and `output/` (is what it wrote any good).
The README keeps their questions, which is what a rebuild needs; the code is in
git at `0801cfe`. **`output/` is the one that matters**: nothing automated grades
what the studio writes today.

The quiet failures are still the reason for all of it: a reference that never
loaded, an invented page number, a quote attributed to a book that was only a
summary, a skill that fired on a question that was only a report.
