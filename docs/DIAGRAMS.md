# Four diagrams, one studio

The Agent Factory crash courses hand you four canonical pictures: a decision tree
that picks an agentic architecture, the physical topology a deployed harness ends
up with, a nine-layer evaluation pyramid, and a cost curve across three deployment
sizes.

This page is those four diagrams redrawn against **what this repository actually
runs** — with every divergence named and, where a number decided something, the
number printed next to it.

The reasoning behind each is in [CASE-STUDY.md](CASE-STUDY.md); this page is the
picture version, meant to be readable in about four minutes.

---

## 1 · The architecture that was chosen, and the four that were not

![The five-question decision tree answered for this project: Q1 to Q3 lead to a single agent with ReAct and tools, and the two additive layers are declined with a measurement each](diagrams/01-architecture-chosen.svg)

Three answers were forced by properties of the task, not by preference:

- **Q1 — partly.** The two phases are fixed; the steps inside them are not.
- **Q2 — no.** One form produces four different runs: `Memorie` calls no tool,
  `Cărți` calls one, `Internet` calls another, `Combinat` calls either or both. A
  fixed pipeline would branch four ways and still be wrong the first time a fifth
  source appears.
- **Q3 — yes, and it is already written down.** By the domain expert, in
  `SKILL.md`, in prose she edits without a developer. Adding a planning agent
  would pay a model, every run, to re-derive a plan that already exists. **The
  plan is an input here, not an output** — which is the whole reason the pattern
  is "single agent + ReAct + tools" and not "planning + ReAct".

The interesting part is the two layers that were **declined**, because each was
declined against evidence rather than taste.

**Q4, the reflection layer.** The criteria that are genuinely checkable — exactly
ten proposals, five hook types, ten distinct angles — moved into the **output
schema** instead of a critique pass. OpenAI enforces `enum`, `pattern` and
`minLength` *while the model writes*, so a structural rule costs no second call.
Measured: with "make them different" as prose sitting 3,800 tokens above the
schema, one batch proposed *delegation* twice and *boundaries* twice — closest
title pair **0.629**. With ten named archetypes as ten schema slots, the closest
pair fell to **0.475**. A reflection pass would have cost 2–5× the latency to
catch what a schema now prevents.

**Q5, the multi-agent layer.** The two phases look like two specialists. They are
two *skills* instead, because the shared context is a **28,639-character** client
profile plus her voice rules, and splitting the work copies that into a second
context window for a **5–20×** cost multiplier — against three accounts and a
client paying her own bill.

> The rule this project wrote for itself, now rule 5 of `AGENTS.md`:
> **what a `SKILL.md` cannot enforce, a schema can — and the schema is where it
> goes.** A rule that belongs to the method still lives in the skill; only what
> has a field to sit next to moves into a contract.

---

## 2 · The stack that runs, and the three places it diverges

![The deployed topology: browser to Azure Container Apps ingress to the FastAPI harness, which opens one E2B container per run and reaches all data through a second internal-only container app running the MCP server](diagrams/02-deployed-stack.svg)

Same control-plane / execution-plane split as the reference, same Azure Container
Apps, same Neon Postgres. Three differences, each deliberate:

**1 · A second container app the reference stack has no equivalent for.** The MCP
data plane runs as its own process, on **internal ingress only** — it does not
exist on the internet. That is architecture rule 1 made physical: business data is
read and written only through `content-data`, there is no `run_sql` tool, no DDL,
and no tool takes free text that a query is built from. Ten tools are visible to
the model; 25 more are internal UI operations behind the SDK's tool filter, and a
check asserts the exact surface on every run.

**2 · E2B instead of Cloudflare Sandbox and its bridge Worker.** The reference
routes Python clients through a Worker that exposes the Sandbox API over HTTP.
E2B needs no bridge at all: one fewer network boundary and one fewer thing to
authenticate. It was also free to start, which is no longer the deciding factor —
see §4, where the two options come out within a few dollars of each other and the
choice turns on which billing model the provider actually offers.

**3 · Cloudflare R2 refused outright, not postponed.** Her posts are domain rows
in Postgres, not downloadable files. `/health` reports `artifacts` inactive **with
the reason in the body**, so the refusal is visible in the running system rather
than only in a plan.

Two properties worth pointing at in the picture:

- **The container holds no credentials and has no network.** It contains the
  method and nothing else. Everything the agent can reach, it reaches by asking
  the harness for a tool.
- **A write and its audit row commit in one transaction.** A saved post with no
  trail cannot exist, even if the connection dies between the two statements.

**The failure mode of this shape does not raise.** A model that never opens the
mounted method still answers, plausibly. On the first live run `gpt-5-nano` called
the shell twice with the bare command `bash`, read nothing, and produced ten
believable titles; `gpt-5-mini`, minutes later, ran `sed -n '1,200p'` over the
whole file. Nano left the allowlist that day — and that one incident is why the
evaluation suite below exists in the shape it does.

---

## 3 · Eight layers of the pyramid built, one honestly empty

![The nine-layer evaluation pyramid with eight layers built and layer three, output evals, marked empty in red; four defects on the right, each invisible to the layers below the one that found it](diagrams/03-eval-pyramid.svg)

| Layer | Built as | Last result |
|---|---|---|
| 1 · Unit | `tests/unit/` — free, offline, every commit | 408 green |
| 2 · Integration | `tests/checks/` — real MCP, Neon and OpenAI, no grading | 5 free + 4 paid |
| **3 · Output** | **empty** — removed when its numbers described code that no longer existed | **by eye** |
| 4 · Tool-use | `evals/route/` — a 240-square domain grid, 24-square spine | 24/24 |
| 5 · Trace | `evals/path/` + `references.py --traces` | mean 0.903 |
| 6 · RAG | `evals/skill/` — LLM judge with a negative control | 13/13 |
| 7 · Safety | gate on the MCP *registration*; `GENERATION_VISIBLE_TOOLS` | 5/5 |
| 8 · Regression | `evals/experiment.py` — one Phoenix dataset, six scores | 6 scores |
| 9 · Production | `public.traces`, one `run_id`, 100% sampled | 100% |

**Layer 3 is the honest gap.** Nothing automated grades what the studio *writes*.
Hook quality, voice fidelity and "does this sound like her" are read by eye today.
Naming that is more useful than letting a stale number stand in for it.

Three design decisions on this layer worth defending in an interview:

- **A tool that was correctly *not* called returns no score at all**, not a zero.
  A `Cărți` run must not call `search_web`; scoring that 0.0 would print a correct
  route as a failed search.
- **The convergence optimum is taken only over runs that passed the route.** The
  named failure mode of this project — a model that never opens the method —
  produces a *shorter* path, so a plain `min(turns)` would let a run that did
  nothing set the floor.
- **The negative control took two attempts.** The first asked for a topic the
  shelf simply had nothing about, so it failed for the wrong reason. The second
  asks how to choose winter tyres for an SUV: no overlap with the client's avatar
  at all, *and* the web genuinely has good material about it — so the only
  remaining reason to fail is the client herself, which is exactly what the
  control has to demonstrate.

**Not one of the four defects in the right-hand column raised an error.** That is
the entire argument for layering: a skipped layer is invisible until production,
where it shows up as a post that reads well and never followed the method.

---

## 4 · The monthly bill at ten developed ideas a day

![Monthly cost against developed ideas per month: a flat five-dollar fixed floor crossed by the variable line at about 227 ideas a month, with the planned ten-a-day workload just past the crossover](diagrams/04-monthly-cost.svg)

The reference chart's smallest column is **100 runs a day**, where the model API is
92% of the bill. The planned workload here is one batch of ten proposals plus ten
developed ideas a day: **330 model runs and about 11 container-hours a month**.

That lands just past the point where the fixed floor stops mattering. A developed
idea costs about **$0.022** all-in — roughly $0.018 of model and $0.004 of sandbox
seconds — against a **$5** floor that is billed whether or not anybody signs in.
The crossover is `$5 ÷ $0.022 ≈ 227 ideas a month`, about 7.6 a day.

| Line | Why that much | Per month |
|---|---|---:|
| **OpenAI · gpt-5-mini** | *Measured:* a batch of ten proposals is **$0.0085**, 73% of its input served from cache at a tenth the rate. A developed idea ≈ $0.018 | **$5.70** |
| **Azure Container Registry** | Basic tier — the only line billed whether or not the studio is used | **$5.00** |
| **E2B sandbox, compute** | 11 h at 2 vCPU + 1 GiB, billed per second. One container per run, closed when the run ends | **$1.29** |
| Azure Container Apps | ~86k of the 180,000 free vCPU-seconds a month; both apps scale to zero | $0 |
| Neon · App Insights · Phoenix | Free tiers. 4,778 embedded chunks are ~30 MB against a 0.5 GB allowance | $0 |
| Cloudflare R2 | Refused outright — the posts are domain rows, not files | $0 |
| **Total** | | **≈ $12** |

**One number is not settled.** The sandbox provider's one-time free credit is
spent. Its own docs say adding a payment method unblocks the account and billing
continues per second, which keeps this line at **$1.29**; at least one third-party
comparison claims the **$150/month** plan is required instead. Those cannot both
be true, and the difference is 10× the entire rest of the bill — so it is worth
reading in the provider's own dashboard rather than in anyone's blog.

If the paid plan does turn out to be required, the same job is done by **Cloudflare
Containers** for **$5/month plus about $1.14** of usage at this volume — and it is
the sandbox client the SDK ships alongside the current one, so the change is
confined to the one module that builds the client.

### How the model half got to $0.018 an idea: $0.2490 → $0.0470 a batch, same model

| Lever | What it was | Effect |
|---|---|---|
| **The cache was billed at full rate** | 826,880 of 963,852 input tokens in one batch were prompt-cache reads, which bill at a tenth | **2.8×** |
| **The ten output rules left the prompt** | 3,800 tokens above a schema that enforces the same things better, and enforces them *while the model writes* | −3,800 tok |
| **Nine of ten details are never written** | The batch used to develop all ten ideas at once. That is where nearly the whole cost sits — **$0.0733 of $0.0770** — so the details became lazy, written only for the idea she opens | −95% |
| **`reasoning: "minimal"` was a false economy** | Phase 2 must fetch two things before it writes; at the cheapest setting 15 of 16 runs did exactly one and stopped themselves under the turn limit. One step up cost 640 reasoning tokens, about $0.0013 a run, and the prompt cache survived at 98% | **3/12 → 12/12** |

The correction to the cache price is deliberately **not retroactive**: a usage row
keeps the price it was charged on the day, or last month's total silently rewrites
itself.

**And a run that fails still spent the money.** Metering used to happen only after
the run returned, so a missed structured contract or a turn limit left no row at
all. Measured against `public.traces`, which records spans either way: one batch
consumed $0.0195 and recorded $0.0061; another consumed $0.1019 against $0.0770.
The gap scales with the failure rate — exactly backwards for a gate meant to stop
runaway spending. Usage comes off a `RunHooks` now, and deliberately not off
`exception.run_data`, which the SDK detaches on the very path a structured-output
failure takes.

---

## Where to go next

| | |
|---|---|
| The reasoning in full, including what is not done | [CASE-STUDY.md](CASE-STUDY.md) |
| Why each structural choice is what it is | [ARCHITECTURE.md](ARCHITECTURE.md) |
| The rules that must not be rediscovered | [../AGENTS.md](../AGENTS.md) |
| How to verify it, rung by rung | [TESTING.md](TESTING.md) |
| The eval map, group by group | [../evals/README.md](../evals/README.md) |

The diagrams themselves are plain SVG in [`diagrams/`](diagrams/) — no build step,
no library, editable in a text editor like everything else here.
