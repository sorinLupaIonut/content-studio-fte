# The eval set — Decision 10

`cases.json` holds the twelve ugly cases from §5 of the plan plus three trigger
evals. Each one carries the conversation and the correct behaviour side by side —
the plain-language `expected` field is the real specification, and the matcher is
only what can be automated of it.

The runner uses the real worker, the real skill tools and the real MCP server:

```bash
uv run content-studio-server
```

```bash
uv run python evals/run.py
```

You can run a single case, or only the fully automatic checks:

```bash
uv run python evals/run.py --id 8
```

```bash
uv run python evals/run.py --automatic-only
```

The detailed result lands in `evals/report-latest.json` (gitignored). Cases marked
`by_eye` are run and checked mechanically where possible, but the voice and the
judgement are read out of `final_answer`. Case 11 covers the Internet source: the
tool must be called, and the figures, studies and quotes it finds must not become
facts in the post.

During evals, `save_post` and `update_profile` are always refused at the gate. The
set leaves no posts and no profile changes behind.

## The case format

```json
{
  "id": 13,
  "title": "Trigger: `propune-postari` fires",
  "why": "A skill fires from its description. So the description is code.",
  "turns": ["dă-mi conținut pe Conexiune"],
  "expected": "It opens `propune-postari` and starts with the questions.",
  "checks": { "skills": ["propune-postari"] },
  "state": "automatic"
}
```

`state` is `automatic` (checked mechanically), `by_eye` (it runs, a human gives the
verdict) or `deferred` (cannot run yet).

`checks` accepts `contains`, `must_not_contain`, `tools`, `forbidden_tools`,
`skills`, `proposal_count` and `hook_types`.

The turns and the regex patterns are Romanian, because they are what the client
types and what the model answers.

---

## References — `references.py` and `references.json`

`cases.json` asks whether the agent behaved. `references.json` asks something
narrower and easier to lose: whether each `references/` file reached the model at
all. A reference fails silently — nothing raises, nothing logs, the answer still
arrives, written from memory instead of from the method — so the expectation has
to be written down next to the file.

```bash
uv run python evals/references.py
```

The static audit. Free, no model, no database. For every reference: is it on
disk, does the manifest declare when it should fire, and does a `SKILL.md`
actually name it? A file nothing points at cannot fire however good the run is,
and that is a different fault from one that could have fired and did not.

```bash
uv run python evals/references.py --traces --minutes 30
```

What real runs asked for, counted out of `public.traces`. The spans live in
`payload->'spans'` as an array — the row `close_run` writes is a different shape
and holds only the reply. The turn count is printed next to the reads so that
"nothing was read" cannot be confused with "nothing ran".

In `references.json`, `expect` is `required`, `forbidden` or `optional` per
scenario, and `proposed: true` marks a trigger nobody has decided yet. `when` is
Romanian: it is the sentence that belongs in `SKILL.md`.

---

## The grid — `tool_usage.py` and `tool-usage-grid.json`

`references.py --traces` counts what a run that already happened asked for.
`tool_usage.py` makes the runs happen, one per square of the domain grid, and
scores each against a label written before the run: **format × pillar × source ×
focus**, in both generation phases. 240 squares.

It is not `tool_use.py`. That file runs six hand-written cases and asks one
question per case — was a required tool missing. This one asks the same question
of every combination the interface can produce, and splits the answer into the
three the course's Skill lab splits it into:

| score | question | where a failure gets fixed |
|---|---|---|
| `router` | did it open the right `SKILL.md`? | the frontmatter `description` |
| `references` | exactly the `references/` its format and source call for — all of them, none of the others? | the skill body |
| `tools` | `search_books` / `search_web` when the source says so, and not when it says not to? | the source table inside the skill |

```bash
uv run python evals/tool_usage.py --dry-run
```

The labels, free. No model, no container, no cost. Read this before paying for
anything: a wrong label is a wrong verdict on every square it touches.

```bash
uv run python evals/tool_usage.py
```

The **spine** — one case per distinct label (phase × format × source, so 24 of
the 240), with the pillar and the focus rotated through them so all five pillars
and both focus states still run. The other 216 squares carry a label identical to
one of these; the run says so rather than dropping them quietly.

```bash
uv run python evals/tool_usage.py --all
```

Every square. Real money, hours of it. Filters exist for everything in between —
`--phase`, `--format`, `--source`, `--pillar`, `--focus`, `--id`, `--concurrency`.

The input is production's, not a re-typing of it: `GenerationBatchRequest`, the
coordinator's own `_title_agent` / `_detail_agent`, and `title_prompt` /
`detail_prompt` — the same three builders `tests/checks/run_like_production.py`
uses. Each case also carries the sentence its button dictates
(`dictated_batch_request`, `dictated_develop`), so what you read in the report is
what she types and what is sent is what the button sends.

The label is composed from two manifests and neither copies the other:
`references.json` owns the **format** half (which references a Reel, a Carusel or
a Stories detail run needs, and which it must not open), `tool-usage-grid.json`
owns the **source** half (the shelf and the search tool, per source, per phase)
plus the axes. `tests/unit/test_tool_usage_grid.py` holds the composition — and
holds the axes against `FormatChoice`, `PillarChoice` and `SourceChoice`, so a
grid that drifts from the contract fails offline instead of measuring fiction.

Reports land in `evals/reports/tool-usage-<stamp>.json` with the whole route per
case: the shell commands, the references, the tools, the turns. The terminal
prints a per-axis summary, which is the reason the grid beats six cases — it says
whether it is one format, one source or one pillar that misbehaves.
