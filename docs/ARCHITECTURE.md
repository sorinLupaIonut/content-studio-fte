# Architecture

Why this is built the way it is. The rules themselves are in
[AGENTS.md](../AGENTS.md); this document explains the domain they serve and the
reasoning behind each structural choice.

The original planning document, written in Romanian while the system was being
designed, is kept as [plan-ro.md](plan-ro.md). It has the day-by-day reasoning,
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

One `SandboxAgent` with the client profile and ten output rules in its system
prompt. Two folder-shaped skills mounted into an E2B sandbox. Five tools reached
over HTTP from a purpose-built MCP server. One Postgres database behind that server,
plus two direct connections the worker keeps for itself — conversation memory and
the audit trail.

```
The client
    │  terminal, Romanian
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
         └─ update_profile    ─► Neon, only after approval

audit.py ─── own connection ──► messages, skills, calls, approvals, results
```

**Why the profile is a resource and not a tool.** It has to be in the system prompt
before the agent can do anything, and it must never be something the model decides
to fetch. As an MCP resource it is read programmatically at startup, by the worker,
which still runs no SQL of its own.

## 3. The data model

Five tables from the reference design, plus two for this domain.

| Table | Holds | Note |
|---|---|---|
| `conversations` | the cover sheet: who, when, status, summary | the turn-by-turn transcript belongs to the SDK's own tables, linked by `session_id` |
| `documents` | the library, one row per book | provenance lives in `metadata`, per row |
| `embeddings` | 4,778 chunks, 1536 dimensions, HNSW index | one table for documents *and* conversations; a CHECK forces exactly one link |
| `audit_log` | the replayable trail | `action` is a **closed** vocabulary — widening it is a migration |
| `capability_invocations` | every skill or tool call, with status | `blocked` is what a refused approval looks like |
| `clients` | one content column, `profile_md` | it lives here rather than in embeddings because it is the only material that gets *written to*: you cannot UPDATE a vector |
| `posts` | the finished posts | at 26 rows, "have I written about this?" is a WHERE, not a vector search |

`posts.body_md` keeps each source file whole alongside the parsed columns. The 26
existing posts came in three different shapes; a parser that splits them into columns
loses whatever it does not recognize, and that loss would be silent.

## 4. The flow: two phases, four questions

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
post is saved. The other nine proposals stay in `audit_log`, not in `posts`.

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
number is counted afterwards, in `tests/checks/full_flow.py`, and judged in the evals.

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
- **Multi-user.** `conversations.user_id` exists and is always `'viorela'`. The
  column is the deferral, not the decision.
- **A tool for the profile.** It is a resource precisely so the model cannot choose
  to call it.
- **Anything from the project mounted into the sandbox except `skills/`.** `.env`
  holds the database password and the agent has a shell.

## 7. Where the ugly cases live

Fifteen eval cases in [../evals/cases.json](../evals/cases.json), twelve of them
chosen because they are how this class of system fails quietly. Each one carries the
correct behaviour written next to it in plain language — that, rather than the
matcher, is the actual specification. Three of them are trigger evals: does the skill
fire when it should, and stay silent when the question is only a report.
