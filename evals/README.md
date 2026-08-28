# The evals — the map

Four groups, and the folder name is the question each one answers. Nothing else
here is worth memorising: open the group whose question matches what you changed.

| you changed | ask | folder |
|---|---|---|
| a `SKILL.md`, a `references/` file, a frontmatter description | did it reach the method and call the right tools? | [`route/`](#route--did-it-reach-the-method) |
| the prompt, a model setting, anything that only shows up live | what did a real run actually do? | [`runs/`](#runs--what-a-real-run-did) |
| the shelf, the embedding model, `search_books` | does the right book come back? | [`retrieval/`](#retrieval--does-the-shelf-answer) |
| the output contract, the voice, the schemas | is what it wrote any good? | [`output/`](#output--is-what-it-wrote-any-good) |

Every eval writes `evals/reports/<name>-<stamp>.json`. That folder is gitignored on
purpose — a graded report is evidence of a moment, not source.

**Run the free ones first.** Three of them cost nothing and each can invalidate a
paid run before you pay for it.

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

## `runs/` — what a real run did

`route/` makes runs happen. This group reads runs that already happened, out of
Neon, and grades them. Both files exist because **Neon is the record and Phoenix is
the sample**; this is the Neon half.

### `traces.py` — the reader

```bash
uv run python evals/runs/traces.py --hours 24
```

Free. Lists the runs in a window and, for each, what tools it called. One
`GradedRun` per `run_id`, assembled from `public.runs` (the request and the reply)
and `public.traces` (the `function` and `response` spans). Everything downstream
reads through this, so a change to the span shape is fixed once.

### `grade.py` + `trace-rubric.json` — the rubric

```bash
uv run python evals/runs/grade.py --hours 24
```

Scores those runs against `trace-rubric.json`. The deterministic criteria are code
— a caption is 863 characters or it is not, and paying a judge to count them would
be the most expensive way to learn a number. `--dry-run` scores without calling the
model, so you can see what would have been sent.

`tests/unit/test_graders.py` holds every threshold against the rubric file, so a
rule changed there and not here fails loudly.

---

## `retrieval/` — does the shelf answer?

### `retrieval.py` + `retrieval-dataset.json`

```bash
uv run python evals/retrieval/retrieval.py
```

No agent in the loop, on purpose: these failures are the tool's own — the right
book not surfaced, an off-topic query scoring like a match — and putting the agent
between the query and the verdict adds only noise and cost. The probe calls
`search_books` the way the agent does and reads titles and scores back.

- `regasire` (recall@3): the labelled book must appear in the top 3 passages. This
  is the guard on **architecture rule 3** — the same embedding model at both ends —
  and on the language gap: 8 of the 17 books are English and near-invisible to
  Romanian phrasings. One case is left red on purpose as the detector for that gap.
- `control-negativ`: queries with nothing on the shelf. What matters is the
  **separation** between the lowest passing positive and the highest negative. The
  bands overlapped when last measured, which is why score alone must never gate a
  passage — the skill says so in words; this says it in numbers, and alarms if the
  margin shrinks.

The only spend is one embedding per query.

---

## `output/` — is what it wrote any good?

A package, not a script, and deliberately **offline**: the cases are pre-recorded
into `golden.json` by `seed_golden.py`, so grading the writing never re-runs the
studio.

| file | what it is |
|---|---|
| `seed_golden.py` | freezes what the studio already wrote into a gradable set |
| `golden.json` | that set — the frozen answers, committed |
| `metrics.py` | the three metrics, all of them judgement |
| `judge.py` | the grader, and why it is a stranger to the model being graded |
| `material.py` | where the ruler's material comes from: the repo itself, never a copy |
| `ruler.py` | the ruler's fingerprint, so a comparison can refuse itself |
| `baseline.py` | what "no worse than last time" means, and why it is not per case |
| `control.py` / `negative.py` | are the metrics any good — text that must win points, text that must lose them |
| `report.py` | the same metrics read as numbers instead of pass/fail |
| `test_output.py` | the regression gate |

```bash
uv run pytest evals/output/ -v
```

```bash
uv run python -m evals.output.report
```

Needs the `evals` extra (`deepeval`); without it the package will not import, which
is by design and not a fault.

---

## What used to be here

Hand-written case files and their runners — `cases.json` / `run.py`, and later
`tool-use-dataset.json` / `tool_use.py` with `citation.py` and `convergence.py`.
They were removed as the suite moved onto real traces and the domain grid.

The last of them went on 2026-08-28 for a reason worth keeping: **its labels named
skills as tool names**, which stopped being true on 2026-08-27 when the sandbox came
back and took the skill tools with it. Its generation case expected an empty route,
on a door that must now open a file *and* call a search tool. A label that cannot be
satisfied is worse than no label — it reports a fault on every run, and you stop
reading it.
