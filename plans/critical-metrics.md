# Critical metrics — what blocks a merge, and what only gets watched

> **A plan, not the state — and since 2026-08-30, a blueprint.** It lives in
> `plans/` because the gate it describes, `.github/workflows/evals.yml`, was never
> built. On 2026-08-30 the layer it grades went too: `evals/output/` was removed
> with its numbers two architecture changes out of date, and is in git at `0801cfe`.
> So read every tense below as future. **The thresholds, the tolerance and the two
> controls are decided and worth keeping** — that is the whole reason this page
> outlived the code. `.github/workflows/ci.yml` is the only gate today — lint and
> the unit tests — and since 2026-08-28 even that runs only on the button in the
> Actions tab.

This page says which findings may stop a change and which are recorded and left
alone. Everything here is about `evals/output/`, the layer that grades **what the
studio writes**; the layer that grades whether the code runs is `tests/unit` and
all of it is critical by definition.

## The three metrics

| metric | judge | threshold | blocks a merge |
|---|---|---|---|
| `Hallucination` | DeepSeek | 0.7 | ✅ mean, tolerance 0.10 |
| `BriefCompliance` | DeepSeek | 0.7 | ✅ mean, tolerance 0.10 |
| `AvatarResonance` | DeepSeek | 0.7 | ✅ mean, tolerance 0.10 |

Plus one that is not a metric and blocks harder than any of them:

| check | blocks | why |
|---|---|---|
| the ruler fingerprint | ✅ **refuses to compare at all** | a baseline measured with a different pillar file, rubric, format brief, judge or case set is not a baseline for this run |

## What "blocks" means here, precisely

**Not** "the score is below its threshold". If that were the rule the build
would be red today — `AvatarResonance` averages 0.46 with two cases in fifteen
over their own threshold — and a permanently red gate is one people learn to ignore.

The rule is **no worse than the recorded baseline**:

- **All three** are compared on the MEAN, with a tolerance of
  0.10. Measured 2026-08-25 across two identical runs of the same frozen text:
  a single case swung as much as 0.50, while the means moved by at most 0.03.
  A per-case gate on a judge would need a tolerance of half the scale, and a
  gate that tolerates half the scale is not a gate. See `evals/output/baseline.py`.

## Non-critical: tracked, never blocking

| what | where | why it does not block |
|---|---|---|
| the `open` list | `evals/output/golden.json` → `open` | 28 (case, metric) pairs are under threshold today. That is the work, deliberately recorded, and shrinking it is the evidence that a repair landed |
| absolute quality | — | nothing asserts "the writing is good". No CI can, without a person |
| `expected_behavior` | `evals/output/golden.json` | null on every case. Only she can write those lines, and only for the cases that fail |

## The judged layer is optional in CI, and skips rather than passes

`DEEPSEEK_API_KEY` is a repository secret. If it is absent the three judged
tests **skip**; the fingerprint check and the structural tests still run and can
still fail the build. Every metric needs a judge since `CaptionLength` was
removed, so on a bare clone nothing is measured — and the suite says so instead
of going green.

A skip is not a pass. `test_the_baseline_covers_every_metric` exists precisely
to stop an expired key reading as "nothing got worse" — it fails if the recorded
baseline does not cover all three metrics.

To light up the judged layer:

```
Settings → Secrets and variables → Actions → New repository secret
Name: DEEPSEEK_API_KEY
```

Nothing in the workflow changes.

## When the gate goes red on purpose

Editing the method **is** the work, and every one of these edits will turn CI red
with the fingerprint's reason. That is correct, and the response is always the
same three steps:

```bash
uv run python -m evals.output.report --update-baseline
```

then read the printed before → after, then commit `evals/output/golden.json`. The ruler
change becomes a line in a diff instead of a silent shift under a number nobody
re-read.

**The re-record refuses to swallow a regression.** If the new measurement is
worse than the current baseline past tolerance, `--update-baseline` writes
nothing and prints what dropped. That is deliberate: without it, the command
named in the failure message would be the way to make the failure go away. When
the drop is the intended price of a better method, say so:

```bash
uv run python -m evals.output.report --update-baseline --accept-worse
```

The refusal uses the same tolerance CI blocks on — two numbers would eventually
disagree. Held by `tests/unit/test_output_baseline.py`.

## What triggers the gate, and why nothing more

The workflow's `paths` are the files `ruler.watched_files()` derives, and
`tests/unit/test_eval_trigger.py` fails if the two ever disagree — in BOTH
directions, so a path that watches nothing is as much a failure as a file that
nothing watches.

`worker.py`, `method.py` and the `SKILL.md` bodies are deliberately absent. The
answers in `golden.json` are frozen, so changing how FUTURE text is written
leaves every number identical: re-running the gate there spends judge calls to
prove nothing, and a check that always passes is one people stop reading.
`config.py` IS watched, because it holds `DEEPSEEK_MODEL` — an edit there
changes the judge, and the first hand-written path list missed it entirely.

| you edited | what moves |
|---|---|
| `skills/propune-postari/references/piloni.md` | `BriefCompliance` |
| `skills/propune-postari/references/surse.md` | `BriefCompliance`, `Hallucination` |
| `SILENT_REEL_BRIEF` in `generation.py` | `BriefCompliance` |
| `content/profile.md` (the avatar sections) | `AvatarResonance` |
| any rubric or threshold in `evals/output/metrics.py` | that metric |
| `DEEPSEEK_MODEL` | all three |
| the case set — a re-seed, or a promotion | all three |

## Cost

Fifteen cases across six briefs, three metrics: 45 DeepSeek calls per full run,
about two minutes, cents. There is no free layer left to run without the secret
— since `CaptionLength` was removed every metric needs a judge — so a run
without the key skips the measurements and still fails on the fingerprint and
the structural checks.

## Two controls, neither of them a gate

A metric can be wrong in two directions and the frozen set cannot see either,
because every case in it was written by the model being judged.

```bash
uv run python -m evals.output.control --metric Hallucination
```

scores the client's own published posts. If her writing scores low, the metric
is broken. Measured 2026-08-25: `Hallucination` gave her 0.72 — *below* the
model's 0.78 — on four false positives (a hook counting its own list, her own
biography, a CTA in quotation marks, a book she had read). After the rubric was
repaired: **1.00, ten out of ten.**

```bash
uv run python -m evals.output.negative
```

is the other half, and it exists because 1.00 is also what a metric that stopped
measuring would score. Nine fragments — five carrying a planted violation, four
written to sit as close to an exception as possible without being one. **9/9**
after the repair: it still catches the invented statistic, the invented study,
the invented Maté quote, the invented price and the invented clinical figure.

Run both after editing a rubric. Neither belongs in CI: they need a judge, and
gating a merge on the client's own writing would be a category error.
