# D1b — Studio Viorela UI specification and implementation plan

Status: **approved; D1b.0–D1b.2 implemented, D1b.2 paid acceptance pending;
D1b.3 in progress**.

This document is the hand-off contract for Codex, Claude Code and Sorin. Product
decisions came from the interview completed on 2026-08-17. Repository rules in
`AGENTS.md` still win: one `SandboxAgent`, business data through `content-data`,
folder-shaped skills, and approval before every durable content write.

## 1. Outcome

Build a .NET 10 Blazor WebAssembly application, served as static files by the
FastAPI harness, where Viorela can:

1. update her profile by section;
2. generate ten idea titles quickly;
3. receive five complete alternatives for every idea in the background;
4. choose one alternative per idea;
5. use a streaming, context-aware chat to rewrite the active content;
6. save one or several final posts after explicit approval;
7. reopen and edit saved posts;
8. later upload reference material and dictate Romanian messages.

Sorin has a second allow-listed account for testing. Permanent content is shared;
each account's unsaved batch and active chat are separate.

## 2. Locked product language

These terms must not be blurred in code, API names or UI copy.

- **Idea**: one of ten short titles/angles. An idea is not a saved post.
- **Variant**: one complete treatment of an idea for a hook type. It includes the
  hook, format-specific script/body, caption, 3–5 hashtags, CTA and provenance.
- **Final post**: the one variant selected from an idea. It becomes a saved post
  only after explicit approval and a successful write.
- **Batch**: ten ideas, each with five variants: 50 generated variants in total.

The five hook tabs are always, in this order: `PROVOCARE`, `CIFRA`, `SECRET`,
`INTREBARE`, `CONTRAST`. The UI uses Romanian diacritics in their labels.

## 3. Locked user experience

### Navigation and visual system

Primary routes:

- `/generator`
- `/saved`
- `/profile`
- `/library`

The default route after sign-in is `/generator`. The global chat is an expandable
bottom panel on every route.

Product name: **Studio Viorela**. Line: **Conținut care sună ca tine**.

| Token | Value |
|---|---|
| warm background | `#F7F3EC` |
| primary text | `#28242B` |
| plum primary | `#654A5D` |
| sage accent | `#91A296` |
| decorative gold | `#C4A261` |
| cards | `#FFFFFF` |
| editorial headings | Source Serif 4, self-hosted |
| UI/body | Manrope, self-hosted |

Laptop/desktop is the primary editing experience. Mobile keeps the complete
workflow; hook tabs scroll horizontally and chat becomes a bottom sheet.

### Generator

Required selectors:

- format: Reel, Carusel, Stories;
- pillar: Poziționare, Educație, Conexiune, Conversie, Magnetism;
- source: Cărți, Internet, Memorie, Combinat.

The weekly focus text is optional. With no focus, the agent derives angles from
the profile and selected source. `Cărți` searches the complete library by default;
an optional multi-select restricts it to chosen books. `Combinat` offers the same
filter.

The first model result is exactly ten collapsed idea cards. Details populate in
the background. Each card reports its own `waiting`, `generating`, `ready`,
`retrying`, `failed` or `cancelled` state. Expanding a ready card exposes the five
hook tabs. `Alege această variantă` marks exactly one tab for that idea.

### Chat and UI synchronization

The chat composer always exposes its target chip:

- active generated variant;
- active saved post;
- active profile section;
- active library document;
- general chat when nothing is selected.

If a rewrite is ambiguous and no target is active, the UI asks for a selection;
the agent must not guess. Chat text streams progressively. A structured UI patch
is applied only after the complete patch validates, never token by token. A
cancelled response leaves its partial text visible and marked as stopped, but it
does not mutate the target card.

Rewrites replace current content. There is no undo or version-history UI.

### Saving

Several final posts may be selected and submitted together. The approval view
shows a summary and creates one gated batch write. Persistence is atomic: all
selected posts are saved or none are. The user-facing lifecycle is only
`Generată -> Salvată`; the existing internal `posts.status` vocabulary is not
exposed as a second workflow.

A saved post can be reopened in the same editor and chat. Changes remain a draft
until `Salvează modificările`; approval then replaces the stored post. No saved
post history is added in D1b.

### Profile

Never show raw Markdown. Parse the live profile resource into accordions for
identity, ideal client, voice, offer, pillars, CTAs and restrictions. Saving is
section-scoped, explicit and protected by the existing `update_profile` approval
gate.

## 4. Authentication and ownership

Production uses Azure Container Apps built-in authentication with Google and
`Require authentication`.

- No public registration.
- The two supplied Google addresses are deployment configuration, never source
  code or tracked documentation.
- Bootstrap with an email allow-list only until both stable
  `X-MS-CLIENT-PRINCIPAL-ID` values are captured.
- Production authorization then uses `AUTH_ALLOWED_PRINCIPAL_IDS` and fails
  closed with `403` for every other identity.
- `resolved_by` and audit actor values come from trusted request identity, never
  from a JSON body supplied by the browser.
- The signed-in identity is visible in the app shell.

Local development uses an explicit development-auth mode that refuses to start
on a non-loopback binding. It must not be possible to enable that bypass in the
Azure environment accidentally.

Permanent profile, library and saved posts are shared. Each principal owns one
current unsaved batch and one chat session. Starting another batch asks for
confirmation and replaces that account's current batch only.

## 5. Architecture guardrails

### Keep one agent

Do not create an ideation agent plus a writing agent. Use the same
`SandboxAgent` definition and the same profile/rules for:

1. one structured title run;
2. ten bounded-concurrent structured detail runs;
3. ordinary streaming chat and rewrites.

`output_type` may vary by operation, but the agent identity, instructions, skills
and tool boundary do not. Update the two existing skills to describe the new UI
flow; do not duplicate their method inside Python prompts.

### Keep business data behind `content-data`

The harness does not issue raw SQL for profiles, books, drafts or posts. Extend
the purpose-built `content-data` server with typed operations for generator draft
state and UI reads. Filter internal UI operations from the model-visible MCP tool
list using the installed SDK's `tool_filter` support.

Model-visible writes remain deliberately small:

- existing `update_profile`;
- new atomic `save_posts_batch`;
- new `update_post`.

All three stay in `GATED_TOOLS`. The agent sees them and the SDK can interrupt
before execution. Internal draft upserts are not final content writes and are not
model-visible, but still record their audit event in the same transaction.

### Gather source context once

For a batch, read the profile resource and gather permitted source material once
through MCP before generating titles. Store the bounded source packet with the
batch and pass the same packet to all ten detail runs. Do not run ten duplicate
book or web searches.

`Combinat` keeps the restrictions of every source; it does not weaken them.

## 6. Generation topology and latency

The synthetic paid probe used `gpt-5-nano` with minimal reasoning and strict
structured output:

| Topology | Wall time | Validation |
|---|---:|---|
| one strict 10 × 5 response | 61.91 s | 10 ideas / 50 variants |
| titles + ten sequential detail calls | 88.11 s | valid |
| titles + ten concurrent detail calls | **11.59 s** | valid; titles at 1.90 s |

Therefore the planned topology is:

1. gather context once;
2. generate and persist ten titles;
3. publish a `titles.ready` SSE event;
4. launch one detail job per idea with configurable bounded concurrency;
5. every detail job returns exactly five complete variants;
6. validate and persist per idea;
7. retry only a failed idea with idempotency keys.

The synthetic result is a topology decision, not a production latency promise.
Before fixing the default concurrency, run a paid real-stack spike with the same
`SandboxAgent`, E2B skills, full profile and selected MCP source. Compare 5 and 10
concurrent detail jobs. Record first-title time, full-batch time, E2B concurrency,
token cost and retry behaviour. `GENERATION_CONCURRENCY` remains configurable.

### Real-stack result — 2026-08-18

The spike used the live 30,748-character profile, `content-data`, the real E2B
skill mount, strict Pydantic output and the configured `gpt-5-nano` model.

| Probe | Result | Finding |
|---|---:|---|
| title run | 10/10 in 25.58–35.01 s | valid and suitable for nano |
| ten concurrent details | 1/10 in 72.45 s | rejected; the 200k TPM ceiling dominated |
| five concurrent details, isolated rerun | 1/10 in 110.16 s | rejected on nano; TPM, invalid JSON and incomplete skill execution |

The required regression eval for the ordinary CLI skill trigger also failed on
nano: case 13 did not activate `propune-postari`, attempted two gated profile
writes (both rejected), and improvised five posts. The UI branch did not change
the skill description that controls activation. This is further evidence that
nano is not reliable for the sandbox-skill agent role, not a passed regression.
The eval and full-flow MCP registrations were subsequently aligned with the
production five-tool allowlist; the failed result remains recorded rather than
being hidden by an unapproved rerun on a stronger model.

The spike also exposed an SDK lifecycle trap: a developer-owned E2B session must
end through `sandbox.aclose()`. `E2BSandboxClient.delete(session)` is intentionally
a no-op in SDK 0.20.0. The worker, eval and check cleanup paths now use `aclose()`;
the 20 sessions leaked by the first failed benchmark were identified by exact ID
and killed, and no new session remained after the corrected runs.

**Accepted by Sorin on 2026-08-18:** keep `gpt-5-nano` for the short
title run, but use `gpt-5-mini` for the five complete variants per idea, with a
default maximum concurrency of 5 and rate-limit backoff. The configuration is
now `GENERATION_TITLE_MODEL`, `GENERATION_DETAIL_MODEL` and
`GENERATION_CONCURRENCY`; the existing CLI `MODEL` is unchanged. Ten concurrent
details are rejected for the current account tier. The official model pages describe
nano as best suited to summarization/classification and mini as suited to precise,
well-defined work; both support structured output. At Tier 1 their documented TPM
limits are 200k and 500k respectively. Mini's input and output token prices are
five times nano's; Sorin explicitly accepted that tradeoff:

- https://developers.openai.com/api/docs/models/gpt-5-nano
- https://developers.openai.com/api/docs/models/gpt-5-mini

Generation endpoints explicitly request minimal reasoning. Chat remains separately
configurable so a speed setting for bulk output does not silently degrade complex
conversation work.

## 7. Durable draft model

Add three domain tables through the normal direct-endpoint migration path. All
runtime access goes through `content-data`:

### `generation_batches`

Holds `id`, `client_id`, opaque `owner_principal_id`, `session_id`, source,
pillar, format, optional focus, optional selected material IDs, a bounded source
packet, status, `is_current`, timestamps and cancellation state. A partial unique
index permits one `is_current` batch per principal.

### `generation_ideas`

Holds `id`, `batch_id`, ordinal 1–10, title, short angle, generation status,
retry count and last safe error. Unique `(batch_id, ordinal)`.

### `generation_variants`

Holds `id`, `idea_id`, hook type, hook, script/body, caption, hashtags as JSON,
CTA, provenance, format-specific JSON, readiness status and `is_selected`.
Unique `(idea_id, hook_type)` plus a partial unique index allowing at most one
selected variant per idea.

The tables hold only current draft state. Replacing a batch makes it non-current;
the product exposes no history. A retention cleanup may remove replaced drafts
after a documented interval, but must never touch `posts`.

## 8. HTTP contract

Preserve the four D1 endpoints for compatibility. Add authenticated `/api/*`
contracts for the Blazor app.

### Identity and reads

- `GET /api/me`
- `GET /api/profile/sections`
- `GET /api/library`
- `GET /api/posts`
- `GET /api/posts/{post_id}`

### Generation

- `POST /api/generation-batches`
- `GET /api/generation-batches/current`
- `GET /api/generation-batches/{batch_id}`
- `GET /api/generation-batches/{batch_id}/events` — SSE
- `POST /api/generation-batches/{batch_id}/cancel`
- `PUT /api/generation-variants/{variant_id}/selection`

### Agent chat and approvals

- `POST /api/chat/runs` starts a run and returns its durable ID.
- `GET /api/runs/{run_id}/events` streams typed SSE events.
- The existing decision operation is reused internally, but production identity
  supplies `resolved_by`. A resumed run can be streamed through the same event
  resource.

SSE event types: `text.delta`, `status`, `titles.ready`, `idea.ready`,
`idea.failed`, `ui.patch`, `approval.required`, `completed`, `cancelled`, `error`
and heartbeat. Every mutating request accepts an idempotency key.

Do not use WebSockets in D1b. Communication is request/response plus one-way event
delivery, which maps directly to SSE and simplifies reconnect through Container
Apps.

## 9. Blazor solution shape

Create `ui/StudioViorela` and `ui/StudioViorela.Tests`.

Suggested component boundaries:

- `AppShell`, `PrimaryNav`, `UserMenu`;
- `GeneratorPage`, `GenerationForm`, `IdeaList`, `IdeaCard`, `VariantTabs`;
- `SavedPostsPage`, `PostEditor`;
- `ProfilePage`, `ProfileSectionEditor`;
- `LibraryPage`, later `UploadQueue`;
- `ChatDrawer`, `ContextChip`, `ApprovalCard`, `StreamingMessage`;
- typed API client, SSE client, auth state, generator state and chat state.

Use semantic HTML, visible focus states, keyboard-operable tabs/accordions, reduced
motion support and WCAG AA contrast. Do not add a large component framework just
to reproduce the reference site's look.

FastAPI registers API routes first, then serves the built Blazor assets and an
SPA fallback to `index.html`. Local VS Code launches harness and Blazor together;
D2 later publishes the Blazor output in the multi-stage container.

## 10. Deferred media slice (after core acceptance)

The core UI is profile + generator + synchronized streaming chat + approvals +
saved posts. After that vertical slice is accepted:

### Library and attachments

- permanent: text PDF, DOCX, TXT, Markdown and EPUB;
- temporary chat-only: the same types plus PNG/JPG;
- temporary by default, with explicit `Adaugă și în bibliotecă`;
- permanent uploads extract text, create `text-embedding-3-small` embeddings and
  report queued/processing/ready/failed states;
- image-only PDFs return a clear OCR-required message; OCR is deferred.

Storage must be resolved with D5 before permanent original files are deployed.
Extracted text and embeddings already belong in Neon; original file retention
must not be invented as a second shadow architecture.

### Romanian dictation

Record, stop/cancel, upload audio, transcribe with
`gpt-4o-mini-transcribe`, place editable text in the composer, and send only on
explicit action. This is dictation, not a realtime voice agent.

## 11. Implementation checkpoints

Each checkpoint ends with a demo and a go/no-go. Agents must claim their zone in
`plans/DEPLOYMENT.md` before editing.

### D1b.0 — contracts and real-stack spike

Implementation complete; Sorin accepted the hybrid model checkpoint.

- reconcile this plan with SDK 0.20.0 signatures;
- paid 5-vs-10 concurrency probe on the real agent stack;
- Pydantic contracts for exactly 10 titles and exactly 5 variants;
- migration and MCP operations for draft state;
- SSE event contract and free contract tests.

### D1b.1 — secure shell and profile

Implementation complete on 2026-08-18.

- Blazor project, design tokens, responsive shell and global empty chat drawer;
- development identity adapter and trusted Azure header adapter;
- `/api/me`, authorization tests and fail-closed production behaviour;
- structured profile accordions with no raw Markdown and gated section save;
- production publish served by FastAPI plus one VS Code compound for MCP,
  harness and Blazor;
- desktop and 390 px browser passes with zero console warnings/errors.

### D1b.2 — fast generator

Implementation complete; one paid real 10 × 5 acceptance run remains pending.

- selectors, optional focus and optional book filter;
- title-first orchestration and bounded parallel details;
- progressive card states, retries, cancellation and reconnect;
- selection of exactly one variant per idea.

### D1b.3 — streaming chat, saved posts and approvals

- global SSE chat and stop button — implemented;
- typed target context and validated UI patches — implemented for generated
  variants; the complete patch is persisted only after validation;
- atomic `save_posts_batch`, `update_post`, approval UI and authenticated actor;
- saved list/editor and shared visibility.

### D1b acceptance gate

- both allow-listed development identities tested;
- refresh during generation restores the same batch;
- exact 10 × 5 contract survives a real model run;
- one failed detail job retries without discarding nine successes;
- cancelled chat cannot partially patch a card;
- profile, batch save and saved-post update cannot write before approval;
- `uv run ruff check .`;
- `uv run python -m unittest discover -s tests/unit`;
- `dotnet test ui/StudioViorela.Tests`;
- browser pass at laptop and mobile widths.

Only after this gate does D2 package the accepted core UI. Library uploads,
attachments and dictation follow as the next product slice unless Sorin changes
the order explicitly.

## 12. Documentation changes required during implementation

When code changes, update rather than contradict:

- `docs/ARCHITECTURE.md` phase flow, HTTP contract and authentication section;
- `skills/propune-postari/SKILL.md` for title-first UI generation;
- `skills/dezvolta-postarea/SKILL.md` for five complete alternatives per idea;
- `src/content_studio/db/schema.sql` as the database truth;
- `plans/DEPLOYMENT.md` ownership and checkpoint status;
- `.env.example` with names only, never the supplied addresses or secrets.

Do not commit or push until Sorin asks.
