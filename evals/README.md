# The evals — the map

Start here: [`experiment.py`](#experimentpy--one-dataset-six-scores) runs every
metric below against one Phoenix dataset in one pass. The folders are what it is
made of, and each is still runnable on its own when only one question is open.

| you changed | ask | folder |
|---|---|---|
| a `SKILL.md`, a `references/` file, a frontmatter description | did it reach the method and call the right tools? | [`route/`](#route--did-it-reach-the-method) |
| the search rule, a tool's contract, the shelf | was the search any good? | [`skill/`](#skill--was-the-search-any-good) |
| the chat prompt, a trigger tool, a dictated sentence | does one request said ten ways walk one path? | [`path/`](#path--does-it-converge) |
| the profile, the writing prompts, the schemas, the model | does the writing sound like her, and like a person? | [`output/`](#output--is-the-writing-any-good) |

The two are halves of one question and they fail differently: `route/` reads the
call's NAME, `skill/` reads what came back. A tool called correctly that returned
nothing scores 1.0 in the first and 0.0 in the second, which is the whole reason
the second exists.

Three groups were removed on 2026-08-30 with their numbers already stale, and
`output/` is the first one back — rebuilt on 2026-09-01 from the question rather
than from the old code, which is what the section at the bottom is for. What the
other two measured is still kept there, under
[What used to be here](#what-used-to-be-here).

**`output/` is the only group that grades the writing.** The other three grade
the route to it, and all three were green on the day the client's wife said the
Romanian did not sound like a person.

Every eval writes `evals/reports/<name>-<stamp>.json`. That folder is gitignored on
purpose — a graded report is evidence of a moment, not source.

**Run the free ones first.** Several of the runs below cost nothing — the two
`--dry-run` label passes, `route/references.py`, `route/fidelity.py`, and the
whole deterministic layer of `output/` — and each can invalidate a paid run
before you pay for it.

---

## `experiment.py` — one dataset, eight scores

```bash
uv run python evals/experiment.py --dry-run
```

The dataset and every label on it, free. No model, no container, no upload.

```bash
uv run python evals/experiment.py
```

Ten generation runs against one Phoenix dataset, graded eight ways in one place.
Costs the ten runs plus the judge.

| score | question | it came from |
|---|---|---|
| `router` | did it open the right `SKILL.md`? | `route/` |
| `references` | exactly the `references/` its format calls for? | `route/` |
| `tools` | the search tool the source asks for, and no other? | `route/` |
| `relevance_books` | was what the shelf returned any good? | `skill/` |
| `relevance_web` | was what the web returned any good? | `skill/` |
| `convergence` | how long was the path, against the shortest correct one? | `path/`, adapted |
| `voice` | does what it WROTE sound like her? | `output/` |
| `human` | does it sound like a Romanian wrote it? | `output/` |

**Why it exists.** `route/` and `skill/` measured the same runs and could not be
read together: `run_cases.py` made spans and `relevance.py` read whatever spans
the last few minutes happened to hold. A time window is not a join. The dataset
is — the cases are uploaded once under one name, every run hangs off the example
it answers, and two experiments a week apart compare in the Phoenix UI instead of
being two report files somebody has to hold side by side.

**One door, and it is the button.** `GenerationBatchRequest`, the coordinator's
own agents, `title_prompt` / `detail_prompt` — `run_case` is imported from
`route/tool_usage.py`, not rewritten. `path/convergence.py` stays on the chat
door, because that is the only door with free text in it.

**The labels are composed, never copied.** The cases are `skill/cases.json`; the
route half of each label is computed at build time from `references.json` and
`tool-usage-grid.json`. `tests/unit/test_experiment_dataset.py` fails if
`cases.json` ever starts holding a route label of its own.

**`convergence` means something different here**, and the two numbers are not
comparable. On the chat door it asks whether ten phrasings walk one path; a
button has no phrasings. Here the same arithmetic — `optimal / turns` — asks
whether a run got there without wandering, against the shortest path any run took
that *also* passed all three route scores. Path economy, not stability under
rephrasing. The optimum is taken over correct runs for the reason written into
`path/convergence.py`: the named failure mode of this project produces a
**shorter** path, and `min(turns)` outright would let a run that did nothing set
the floor.

**The last two are the only ones that read the text.** They judge with
`EVAL_JUDGE_MODEL` like everything else — which is the family that writes the
posts, and that objection was taken seriously enough to test rather than argue.
`config.py` names DeepSeek precisely to avoid it; it was wired in and run
against both control sets on 2026-09-01, with the rubrics de-leaked first:

| | deepseek-chat | gpt-5-mini |
|---|---|---|
| `voice` | 4/4 planted, **16/16** hers | 4/4 planted, 15/16 hers |
| `human` | **2/4** planted, 15/16 hers | 4/4 planted, 14/16 hers |

DeepSeek judges her voice better and cannot do `human` at all — it passed a
caption taken verbatim from a real run, noting „practică a refuza" was odd and
then excusing it. One judge, then, and the independence is bought back by the
controls instead. `--judge deepseek` re-runs either metric through it.

They also **skip a `titluri` case**, which writes titles and angles and has no
hook to read — a scoreless skip, the same rule `relevance_*` follows for a tool
the source told it not to call. Of the ten cases, three reach them; `--dry-run`
prints which, and how many judge calls that is, before anything is spent.

**Relevance is two evaluators, and that is what makes it cheap.** Each judges
only its own tool's searches and returns a **scoreless skip** — not a zero — when
the run never called it, because `search_web` unused on a `Cărți` run is the
correct route. So every search is judged exactly once and the per-tool rate is a
column rather than something to recompute. The rubric is
`skill/relevance.py`'s `JUDGE_PROMPT`, imported.

**The witness is scored against what it expects.** `martor-negativ` expects
`irelevant`, so it passes by being refused. Nine cases that all come out
`relevant` look the same whether the metric works or the judge says yes to
anything; this is the one case that tells them apart, and it is the reason to
distrust the other nine if it ever passes as `relevant`.

Two things this file does not cover:

- **The source `Memorie`** — the rule "call nothing". `cases.json` leaves it out
  because a run that searches nothing leaves the judge nothing to read, so the
  forbidden half of `tools` is only exercised here where a source forbids the
  *other* tool. The run prints the command that covers it.
- **n = 1 per case.** Same caveat as the grid: one run is a sample, not a
  verdict. `--repetitions N` runs each case N times when a number has to hold up.

`--id` runs one case against a separate `-proba` dataset, so a smoke test cannot
shrink the one every other experiment is compared against.

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

## `skill/` — was the search any good?

The course's Skill lab, on this project's two tools. `route/` grades the routing;
this grades the searching.

### `relevance.py` — one metric, both tools

```bash
uv run python evals/skill/relevance.py --dry-run
```

What would be judged, free. No judge, no cost. Read it first: it prints the
question each run asked, and a lazy question is visible with the naked eye before
anybody pays to have it graded.

```bash
uv run python evals/skill/relevance.py
```

The judgement. One label per search — `relevant` or `irelevant` — scored 1/0 and
written back onto the span as a Phoenix annotation, so the verdict sits next to
the call it belongs to.

**ONE metric for both tools, since 2026-08-30.** Before that date `search_web`
returned a synthesis and `search_books` returned passages, so they needed two
different questions. They return the same shape now — material with its
provenance — so they get the same rubric.

**What the judge is shown** is the whole point of the design:

| piece | where it comes from | why not somewhere else |
|---|---|---|
| the brief — format, pillar, source, focus | regexed off the prompt in the same trace | the root span's name carries it only on eval runs; a metric that works on eval traffic alone measures the eval |
| the avatar — Andreea's five sections | `avatar.excerpt`, imported | the writer is shown these exact sections; a copy here would drift from what is asked for |
| the request, and the material | the tool span's input and output | |

**Both halves are graded together**, and that is deliberate. A perfect tool
answering a lazy question is not a good search; neither is a sharp question that
came back empty. Both get fixed in the same place — the search rule in the two
`SKILL.md` bodies, which `tests/unit/test_search_rule.py` keeps identical.

**It costs only the judge.** No agent runs and no container opens: it reads spans
Phoenix already holds, so every run it grades was paid for once already.

Two things to know before trusting a number:

- **The avatar is read from disk**, not from Neon. A profile she edited through
  `update_profile` lives in `clients.profile_md`, and this eval will not see it.
- **`get_spans_dataframe` takes its own `timeout`, defaulting to 5 seconds**, and
  a client-level timeout does not reach it. Any window wide enough to be
  interesting dies at five seconds with an `httpx.ReadTimeout` that names no
  call. `READ_TIMEOUT` is why that does not happen here.

---

## `path/` — does it converge?

The course's Trajectory lab, on the **chat** door — the only surface in the
studio with free text in it. A button sends the same four structured fields every
time, so repeating a generation run measures variance, not convergence.

### `convergence.py` + `phrasings.json` — one request, ten wordings

```bash
uv run python evals/path/convergence.py --dry-run
```

The ten, free. Read them first: a phrasing that drops an axis is a *different*
question, and the right answer to it is to ask her — a longer path, deservedly,
which would drag the score down for a run that behaved correctly.

```bash
uv run python evals/path/convergence.py
```

Ten chat turns. Two numbers, both free beyond the runs themselves:

- **convergence** — `optimal / turns`, the course's own score.
- **agreement** — did the turn record `start_generation` with the request every
  phrasing was written to mean? A path of equal length that lands on the wrong
  pillar is not convergence, and length alone cannot tell you.

**The anchor is the dictated sentence, and it is not in the manifest.** AGENTS.md
says a button press is dictation and that the sentence a button dictates, typed by
hand, must behave identically. That is a convergence claim written into the
contract, and this file is the first thing to measure it —
`dictated_batch_request` builds it at run time, so no second copy of a contract
string exists here.

**Two corrections made to the transplant on 2026-08-30, both worth keeping:**

- **The focus is judged as free text, not compared byte for byte.** A phrasing
  typed without diacritics recorded `limite fara vinovatie`, and an equality test
  called that a disagreement — punishing the one behaviour the tool description
  demands ("nu inventa un focus"). The three enum axes stay an exact match,
  because there a near miss *is* a miss.
- **The optimum is the shortest CORRECT path.** `Trajectory.py` takes
  `min(path_length)` and can: every path in it ends at the same SQL answer. Here
  one phrasing finished in six steps by never calling `start_generation` at all —
  it replied and stopped — which set the floor and scored every honest run 0.750
  against a run that did nothing.

A `metodă` column says whether each run opened `SKILL.md`, so a short path can be
told from a blind one.

---

## `output/` — is the writing any good?

Back on 2026-09-01, with two of the metrics it used to have and a reason nothing
in the suite could have produced: **the client's wife read a hook and a caption
in Romanian and said they did not sound like Viorela, and did not sound like a
person.** Every other group was green at the time, and correctly so — they grade
the route to the writing, never the writing.

Two metrics, one per half of what she said, because the two fail differently and
are fixed in different files:

| metric | question | where a failure gets fixed |
|---|---|---|
| `voice` | does it sound like HER? | the profile sections `voice.py` lifts, and the prompt that carries them |
| `human` | does it sound like A PERSON writing Romanian? | the writer — the model, its brief, or its temperature |

Both are graded on `hook` and `caption` separately: those are the two fields she
named, and a hook is one line that fails by being generic while a caption is a
page that fails by being assembled.

```bash
uv run python evals/output/human.py --dry-run
```

Every row that would be judged, at no cost. Read it first — a case set that has
drifted is visible with the naked eye, before anybody pays to have it graded.

```bash
uv run python evals/output/voice.py
uv run python evals/output/human.py
```

The judgement. A few cents a metric on DeepSeek.

### The controls are the point

Each metric grades three kinds of row, and the third is the reason to believe
the first two:

- **generated** — real variants out of `generation_variants`, frozen into
  `cases.json` by `seed.py`. The measurement. No expected score.
- **her own** — hooks and captions out of `content/posts/`, which she wrote and
  published. **Expected 1.0.**
- **planted** — fluent fragments written in `cases.py`, each breaking one named
  rule from her profile. **Expected 0.0.**

If a control disagrees, the run says `controls FAIL` and **the generated numbers
are not a result** — `controls_verdict` refuses the summary rather than printing
a score nobody should read. That is not hypothetical: `voice` failed its own
controls on its first judged run, calling 11 of her 16 published pieces generic,
because the rubric demanded a distinctive SUBJECT and her real hooks name
ordinary experiences. The 0/20 it printed for generated output was meaningless,
and the rubric was retuned against her own writing until it was not.

`--controls-only` runs just the controls, which is what rubric calibration
needs: the generated rows carry no expected score, so paying for them while
tuning buys nothing.

**One judged pass is a sample, not a verdict.** The same rubric and the same
judge scored the planted set 4/4 and then 3/4 on identical input — and since one
missed plant voids the whole run, that flip is the difference between a metric
that reports and one that refuses to. `--repeat N` grades every row N times and
keeps the majority, with `agreement` carried beside the score so a row the judge
is genuinely torn about is visible instead of rounded into confidence. Use it
for any number that has to hold up.

**A loanword is not a translation artefact.** On a majority of three the rubric
rejected four of her sixteen published pieces, three for the same reason: the
phrase „people pleasing". Measured against her corpus — „burnout" in 13 of 27
posts, „coach" in 18 — that is her professional vocabulary, and Romanian
coaching writing borrows it untranslated. A criterion that calls an author's own
field terminology foreign is wrong about the language; correcting it is not the
same as tuning until the controls pass, and the difference is whether you can
show the corpus.

**A negative control must be one nobody can defend.** The case that flipped was
one written here — „Ia o respirație adâncă. Nu ești singură în această
călătorie…", called a stack of calques. Two different judges read it as natural
and they had a point: that register is ordinary in Romanian self-help writing
now. It was replaced with an agreement error („3 pași care te VA ajuta"), which
is not a matter of taste.

### One question each, and no rule layer

Both metrics are a single question put to a judge. There was a deterministic
pass beside them for one afternoon and it is gone — Sorin's call, 2026-09-01 —
and the argument that produced it is worth keeping:

A word list for `voice` was built by reading the „Lucruri pe care nu le spui
niciodată" section of her profile, which says plainly that she does not use
„trebuie". Measured against her own 27 published posts before it shipped, her
own work used it **21 times**, one post titled „trebuie vs vreau". „problemă",
„peste noapte" and percentages failed the same way. Four of ten candidates were
things she does constantly. **A rule read off a profile and not measured against
the writing flags the author's best work and calls it a finding.**

**What removing it cost, stated plainly.** Real output mixes the legacy cedilla
letters `ş`/`ţ` into Romanian that otherwise uses `ș`/`ț` — measured over the 60
ready variants and her 27 posts: three generated captions mix them, one at 8
against 9 inside a single caption, and none of hers do. Six lines of `str.count`
caught every one. It was planted as a control instead and the judge passed it
twice, the second time with the character scan as the literal first line of the
rubric. That is not a wording problem: `Eşti` and `Ești` are two different
tokens, and a judge reads tokens. The control was removed rather than left
permanently failing, and **nothing catches that fault now.**

**And a rubric must not quote its own controls.** `human` originally named „mai
puțin oboseală" — the exact phrase inside a planted case — and scored 4/4. With
a different specimen of the same fault it scored 2/4 on the same judge. The
first number was recall, not measurement. `tests/unit/test_rubrics_do_not_leak.py`
holds both rubrics to that, over the whole control set.

### What it does not do

- **n = 10.** Ten frozen variants, two fields. A sample, not a verdict.
- **The judge writes in the same family as the author**, and the controls are
  the only thing standing between that and self-congratulation. Read them first,
  every time. The table above is what an independent judge scored; re-make it
  with `--judge deepseek` whenever a rubric changes shape.
- **It does not read spans.** It reads finished text, so it needs no Phoenix and
  no time window. It is not part of `experiment.py` yet.

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
