# The evals — the map

One group is live. The folder name is the question it answers.

| you changed | ask | folder |
|---|---|---|
| a `SKILL.md`, a `references/` file, a frontmatter description | did it reach the method and call the right tools? | [`route/`](#route--did-it-reach-the-method) |

Three more groups asked the other three questions and were removed on 2026-08-30
with their numbers already stale. What each one measured is kept at the bottom,
under [What used to be here](#what-used-to-be-here) — a rebuild should start from
the question, not from the old code.

Every eval writes `evals/reports/<name>-<stamp>.json`. That folder is gitignored on
purpose — a graded report is evidence of a moment, not source.

**Run the free ones first.** Two of the three below cost nothing and each can
invalidate a paid run before you pay for it.

---

## `route/` — did it reach the method?

The biggest group, because this is the failure that does not raise. A reference
that never loaded produces an answer written from memory, and it looks exactly
like a good one.

### `tool_usage.py` + `tool-usage-grid.json` — the domain grid

One run per square of **format × pillar × source × focus**, in both generation
phases. 240 squares. Each is scored against a label written *before* the run, and
the score is split three ways because the three fail for different reasons and get
fixed in different files:

| score | question | where a failure gets fixed |
|---|---|---|
| `router` | did it open the right `SKILL.md`? | the frontmatter `description` |
| `references` | exactly the `references/` its format calls for — all of them, none of the others? | the skill body |
| `tools` | `search_books` / `search_web` when the source says so, and not when it says not to? | the source table inside the skill |

One number would say a square is wrong without saying where to go.

```bash
uv run python evals/route/tool_usage.py --dry-run
```

The labels, free. No model, no container, no cost. **Read this before paying for
anything** — a wrong label is a wrong verdict on every square it touches.

```bash
uv run python evals/route/tool_usage.py
```

The **spine**: one case per distinct label (phase × format × source, so 24 of the
240), with the pillar and the focus rotated through them so all five pillars and
both focus states still run. The other 216 carry a label identical to one of these;
the run says so rather than dropping them quietly.

```bash
uv run python evals/route/tool_usage.py --all
```

Every square. Real money, hours of it. Filters exist for everything in between —
`--phase`, `--format`, `--source`, `--pillar`, `--focus`, `--id`, `--concurrency`.

**The input is production's, not a re-typing of it:** `GenerationBatchRequest`, the
coordinator's own `_title_agent` / `_detail_agent`, and `title_prompt` /
`detail_prompt` — the same three builders `tests/checks/paid/run_like_production.py`
uses. Each case also carries the sentence its button dictates, so what you read in
the report is what she types, and what is sent is what the button sends.

**The label is composed from two manifests and neither copies the other:**
`references.json` owns the **format** half (which references a Reel, a Carusel or a
Stories detail run needs, and which it must not open); `tool-usage-grid.json` owns
the **source** half (which search tool, per source, per phase) plus the axes.
`tests/unit/test_tool_usage_grid.py` holds the composition, and holds the axes
against `FormatChoice`, `PillarChoice` and `SourceChoice` — so a grid that drifts
from the contract fails offline instead of measuring fiction.

**Three things that will mislead you if you forget them:**

- **n = 1 per square.** One run is a sample, not a verdict. The same square has
  come out opposite ways in consecutive runs with nothing changed between them.
- **A failed tool call still counts as called.** The score reads the call's name,
  not whether it succeeded.
- **`Combinat` is `any_of`**, so it passes on one tool where the method asks for
  both. Deliberately looser than the method, for now.

### `references.py` + `references.json` — the manifest, and what runs asked for

```bash
uv run python evals/route/references.py
```

The static audit. Free — no model, no database. For every reference: is it on disk,
does the manifest declare when it should fire, and does a `SKILL.md` actually name
it? A file nothing points at cannot fire however good the run is, and that is a
different fault from one that could have fired and did not.

```bash
uv run python evals/route/references.py --traces --minutes 30
```

What real runs asked for, counted out of `public.traces`. The turn count is printed
next to the reads so that "nothing was read" cannot be confused with "nothing ran".

In `references.json`, `expect` is `required`, `forbidden` or `optional` per
scenario. `when` is Romanian: it is the sentence that belongs in `SKILL.md`.

### `fidelity.py` — the method reaches the container whole

```bash
uv run python evals/route/fidelity.py
```

Opens a real container and compares every mounted file byte for byte against the
repo. One container, no model, no cost. This is what catches a mount that arrives
truncated or re-encoded — the fault every other eval in this folder would blame on
the model.

---

## What used to be here

### Hand-written cases, and their runners

`cases.json` / `run.py`, and later `tool-use-dataset.json` / `tool_use.py` with
`citation.py` and `convergence.py`. They were removed as the suite moved onto real
traces and the domain grid.

The last of them went on 2026-08-28 for a reason worth keeping: **its labels named
skills as tool names**, which stopped being true on 2026-08-27 when the sandbox came
back and took the skill tools with it. Its generation case expected an empty route,
on a door that must now open a file *and* call a search tool. A label that cannot be
satisfied is worse than no label — it reports a fault on every run, and you stop
reading it.

### The other three groups — removed 2026-08-30

Not because they were wrong. Because only `route/` had numbers from the current
code: the sandbox came back on 2026-08-27 and the turn budget was fixed on
2026-08-28, and all three had last measured before both. **Stale numbers read
exactly like fresh ones**, which is the same fault as an unsatisfiable label,
arriving from the other direction.

They are in git at `0801cfe`, whole, tests included:

```bash
git checkout 0801cfe -- evals/runs evals/retrieval evals/output
```

What each asked, so a rebuild starts from the question:

**`runs/` — what a real run did.** `traces.py` was the reader and the integration
point: one `GradedRun` per `run_id`, assembled from `public.runs` (the request and
the reply) and `public.traces` (the `function` and `response` spans), so a change to
the span shape was fixed once. `grade.py` + `trace-rubric.json` scored those runs on
four criteria — `tool_correctness` and `contract_quality` in code, `policy` and
`attribution` by judge. The deterministic ones were code on purpose: a caption is 863
characters or it is not, and paying a judge to count them is the most expensive way
to learn a number.

**`retrieval/` — does the shelf answer?** No agent in the loop, on purpose: these
failures are the tool's own, and the agent between the query and the verdict adds
only noise and cost. Two halves. `regasire` (recall@3) was the guard on
**architecture rule 3** — the same embedding model at both ends — and on the language
gap: 8 of the 17 books are English and near-invisible to Romanian phrasings, with one
case left red as the detector. `control-negativ` measured the **separation** between
the lowest passing positive and the highest negative; the bands overlapped when last
measured, which is why score alone must never gate a passage.

**`output/` — is what it wrote any good?** The only layer that graded the writing
itself, offline against `golden.json` so that grading never re-ran the studio. Three
judged metrics — `Hallucination`, `BriefCompliance`, `AvatarResonance` — plus two
pieces that are the interesting part: `ruler.py`, the fingerprint that **refuses a
comparison** measured with a different pillar file, rubric, brief, judge or case set;
and `control.py` / `negative.py`, the two controls on the metrics themselves — her own
published posts, which must score high, and nine fragments with planted violations,
which must score low. Its decided thresholds survive in
[../plans/critical-metrics.md](../plans/critical-metrics.md), which is the blueprint
for putting it back.

Two of its files cost more than code to recreate: `golden.json` was seeded from paid
runs, and `retrieval-dataset.json` was labelled by hand. Take them out of git rather
than regenerating them.
