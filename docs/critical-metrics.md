# Critical metrics — what blocks a merge, and what only gets watched

The gate is `.github/workflows/evals.yml`. This page says which of its findings
may stop a change and which are recorded and left alone. Everything here is
about `evals/output/`, the layer that grades **what the studio writes**; the
layer that grades whether the code runs is `tests/unit` and all of it is
critical by definition.

## The four metrics

| metric | judge | threshold | blocks a merge |
|---|---|---|---|
| `CaptionLength` | none — arithmetic | in range → 1.0 | ✅ **per case, exactly** |
| `Hallucination` | DeepSeek | 0.7 | ✅ mean, tolerance 0.10 |
| `BriefCompliance` | DeepSeek | 0.7 | ✅ mean, tolerance 0.10 |
| `AvatarResonance` | DeepSeek | 0.7 | ✅ mean, tolerance 0.10 |

Plus one that is not a metric and blocks harder than any of them:

| check | blocks | why |
|---|---|---|
| the ruler fingerprint | ✅ **refuses to compare at all** | a baseline measured with a different pillar file, rubric, caption window, judge or case set is not a baseline for this run |

## What "blocks" means here, precisely

**Not** "the score is below its threshold". If that were the rule the build
would be red today — `AvatarResonance` averages 0.45 with one case in eight over
its own threshold — and a permanently red gate is one people learn to ignore.

The rule is **no worse than the recorded baseline**:

- **`CaptionLength`** is compared per case and exactly. It involves no model, so
  a case that scored 1.00 and now scores 0.00 is a regression, full stop.
- **The three judged metrics** are compared on the MEAN, with a tolerance of
  0.10. Measured 2026-08-25 across two identical runs of the same frozen text:
  a single case swung as much as 0.50, while the means moved by at most 0.03.
  A per-case gate on a judge would need a tolerance of half the scale, and a
  gate that tolerates half the scale is not a gate. See `evals/output/baseline.py`.

## Non-critical: tracked, never blocking

| what | where | why it does not block |
|---|---|---|
| the `open` list | `evals/golden.json` → `open` | 17 (case, metric) pairs are under threshold today. That is the work, deliberately recorded, and shrinking it is the evidence that a repair landed |
| absolute quality | — | nothing asserts "the writing is good". No CI can, without a person |
| `expected_behavior` | `evals/golden.json` | null on every case. Only she can write those lines, and only for the cases that fail |

## The judged layer is optional in CI, and skips rather than passes

`DEEPSEEK_API_KEY` is a repository secret. If it is absent the three judged
tests **skip**; the fingerprint check, the caption arithmetic and the structural
tests still run and can still fail the build. Measured on a bare clone with
every key unset: 4 passed, 3 skipped, 0.12 s.

A skip is not a pass. `test_the_baseline_covers_every_metric` exists precisely
to stop an expired key reading as "nothing got worse" — it fails if the recorded
baseline does not cover all four metrics.

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

then read the printed before → after, then commit `evals/golden.json`. The ruler
change becomes a line in a diff instead of a silent shift under a number nobody
re-read.

| you edited | what moves |
|---|---|
| `skills/propune-postari/references/piloni.md` | `BriefCompliance` |
| `skills/propune-postari/references/surse.md` | `BriefCompliance`, `Hallucination` |
| `SILENT_REEL_BRIEF` in `generation.py` | `CaptionLength`, `BriefCompliance` |
| `content/profile.md` (the avatar sections) | `AvatarResonance` |
| any rubric or threshold in `evals/output/metrics.py` | that metric |
| `DEEPSEEK_MODEL` | all three judged |
| the case set — a re-seed, or a promotion | all four |

## Cost

Eight cases across four briefs, three judged metrics: about 24 DeepSeek calls
per full run, cents. The free layer is 0.12 s and costs nothing, which is why it
runs on every matching push whether the secret exists or not.
