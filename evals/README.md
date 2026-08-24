# The eval set — Decision 10

`cases.json` holds the twelve ugly cases from §5 of the plan plus three trigger
evals. Each one carries the conversation and the correct behaviour side by side —
the plain-language `expected` field is the real specification, and the matcher is
only what can be automated of it.

The runner uses the real worker, the real skills in E2B and the real MCP server:

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
