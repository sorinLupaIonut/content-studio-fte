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

One `SandboxAgent` definition with the client profile and ten output rules in its
system prompt. Two folder-shaped skills mounted into E2B. Five model-visible tools
and typed internal UI operations reached over HTTP from a purpose-built MCP server.
One Postgres database behind that server, plus two direct connections the harness
keeps only for SDK conversation memory and the approval/audit trail.

```
The client
    │  terminal or Blazor WebAssembly, Romanian
    ▼
worker.py ─── profile + 10 output rules ──► one SandboxAgent
    │                                            │
    │                                            ├─ skill: propune-postari
    │                                            └─ skill: dezvolta-postarea
    │
    └─ MCP server `content-data`
         ├─ internal resource: the live profile (not a tool the model can call)
         ├─ search_books      ─► OpenAI embedding + Neon pgvector
         ├─ search_web        ─► OpenAI web search
         ├─ list_posts        ─► Neon
         ├─ save_post         ─► Neon, only after approval
         ├─ save_posts_batch  ─► Neon, only after approval, all or none
         ├─ update_post       ─► Neon, only after approval
         └─ update_profile    ─► Neon, only after approval

FastAPI harness
    ├─ trusted identity (local loopback or Azure Easy Auth headers)
    ├─ structured profile API + approval resume
    ├─ title-first generation + SSE
    ├─ saved posts: batch save and rewrite, both through the same gate
    └─ internal `ui_*` MCP operations ─► durable generation drafts

audit.py ─── own connection ──► messages, skills, calls, approvals, results
```

**Why the profile is a resource and not a tool.** It has to be in the system prompt
before the agent can do anything, and it must never be something the model decides
to fetch. As an MCP resource it is read programmatically at startup, by the worker,
which still runs no SQL of its own.

## 3. The data model

Two halves: the domain, which is this project's own, and durable state, which is
the deployment crash course's five-table model adopted whole at D4.

**The domain.**

| Table | Holds | Note |
|---|---|---|
| `documents` | the library, one row per book | provenance lives in `metadata`, per row |
| `embeddings` | 4,778 chunks, 1536 dimensions, HNSW index | one link, to a document, enforced by NOT NULL since Decision 11 |
| `clients` | one content column, `profile_md` | it lives here rather than in embeddings because it is the only material that gets *written to*: you cannot UPDATE a vector |
| `posts` | the finished posts | at 27 rows, "have I written about this?" is a WHERE, not a vector search |
| `generation_batches` | one current unsaved batch per authenticated principal | holds the bounded source packet and survives refresh |
| `generation_ideas` | exactly ten title/angle rows | each reports its own generation and retry state |
| `generation_variants` | five complete hook variants per idea | at most one selected variant per idea |

**Durable state** (D4). Every statement names its schema — `public.runs` — because
Neon's pooled endpoint makes no promise about `search_path` surviving between
transactions.

| Table | Holds | Note |
|---|---|---|
| `runs` | one row per turn: the message in, the answer out | `session_id` points at `agent_sessions`, the SDK's own and the **only** session table |
| `traces` | one payload per run | `{"output": …}`; the real SDK traces are in the OpenAI dashboard, grouped by `group_id` |
| `artifacts` | pointers to files in object storage | empty until D5 decides on R2. A post is *not* an artifact |
| `audit_log` | the replayable trail | `(run_id, event)`; `event` is free text, so the vocabulary is a shared constant in `audit.py`, not a CHECK |

Two tables that used to be here are gone: `conversations` and
`capability_invocations` at Decision 11, both second copies of a truth another
table already held. `pending_runs` went at D4 with the rest of the old state
half. The gate itself moved onto six columns of `public.runs`: a pending run keeps
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

Production identity comes from Azure Container Apps Easy Auth headers. Authorization
starts with a deployment email allow-list and moves to stable principal IDs after
the two Google identities have signed in once. Development auth refuses non-loopback
binding and refuses to run when Azure environment markers are present.

The process may boot in a degraded state so Azure can expose diagnostics, but it
does not fall back to SQLite: a run is refused unless Neon can hold the approval
gate durably. R2 is likewise not faked locally; it remains the explicit D5
decision, and `posts` are domain rows rather than artifacts.

## 4. The flow: one method, two UI passes

The terminal conversation still uses the interview below. The Blazor generator
collects format, pillar, source and optional focus in a form, gathers the source
packet once, then runs the same agent definition in two strict structured passes:

1. one pass returns exactly ten persisted title/angle rows;
2. a second pass develops one idea per job into all five complete hook variants,
   with at most five jobs running concurrently.

Both run on `gpt-5-mini`, which since 2026-08-27 is the only model the interface
offers: the method is read from files in a sandbox, and `gpt-5-nano` could not
drive the shell that opens them — it wrote ten plausible titles without ever
reading the method. See AGENTS.md, rule 4.

SSE publishes the durable states. Refresh reads the same batch from Neon. A failed
idea retries without discarding the other nine. Ten concurrent detail calls were
rejected by the real-stack probe because the Tier-1 token window dominated; five
is therefore the explicit default rather than an arbitrary tuning value.

**Phase 1 — `propune-postari`.** Three questions, asked one at a time, none of them
assumed: the **format** (Reel, Carousel, Stories), the **pillar**, and the **source**
of the material. If she picks the books, she is offered 3–4 specific titles matched
to her topic — never the list of 17 — plus "search all of them". Material is
gathered *before* the proposals are written, not bolted on afterwards as a citation.
Then ten proposals, numbered, each with a short title, the idea in one or two
sentences, and five hooks, one of each type.

**The fourth question** is which proposal to develop, and with which hook. She can
pick several. The agent never picks for her.

**Phase 2 — `dezvolta-postarea`.** The chosen proposal becomes a full post: script
shaped by the format, caption, 3–5 hashtags, and the CTA from her profile. It is
shown whole in the chat and nothing is saved until she says yes. Then exactly one
post is saved. The other nine proposals stay in `runs.output_message`, not in
`posts` — the turn that produced them is the record of them.

### The five pillars

Positioning 🎯 · Education 📚 · Connection 🤝 · Conversion 💰 · Magnetism ✨

They belong to the method, not to the client, which is why they live in
`skills/propune-postari/references/piloni.md` and not in the database. If this
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
30,000-character profile and the ten rules into a second context, and because the
handover between phase 1 and phase 2 is exactly where a rejected proposal list would
get lost. The cost is real: a `SKILL.md` cannot *enforce* ten proposals. So the
number is counted afterwards, in `tests/checks/paid/full_flow.py`, and judged in the evals.

**Skills as folders, disclosed progressively.** The index — name, description, path —
is always in context and costs almost nothing. The body opens when the task matches
the description. The references open only when the body points at them. This means
the description is not documentation, it is the trigger: it decides whether the skill
fires at all. That is why three of the fifteen eval cases test descriptions rather
than outputs.

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

- **Vector search over the posts.** At 26 rows, a `WHERE` on title, pillar and date
  answers the question. It becomes worth it in the hundreds.
- **Public registration.** Authentication exists, but access is intentionally
  limited to two deployment-configured Google identities. Permanent content is
  shared; unsaved batches and chat sessions are principal-owned.
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
is the question. One is live: `route/` — did it reach the method and the right
tools. Three were removed on 2026-08-30 with their numbers already two
architecture changes out of date — `runs/` (what a real run did, read back out of
`public.traces`), `retrieval/` (does the shelf return the right book) and
`output/` (is what it wrote any good). The README keeps their questions, which is
what a rebuild needs; the code is in git at `0801cfe`.

The quiet failures are still the reason for all of it: a reference that never
loaded, an invented page number, a quote attributed to a book that was only a
summary, a skill that fired on a question that was only a report.
