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
