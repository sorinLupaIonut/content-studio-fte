# Handoff — 2026-08-30, evening

For the next session in this folder. `AGENTS.md` is the contract and loads itself;
this page is only what that file cannot know: where the work stopped and what the
last commits changed under it.

**Delete this file when it stops being true.** A stale handoff is read as current,
which is worse than none.

---

## State

| | |
|---|---|
| branch | `deploy`, pushed |
| unit tests | 408, green |
| ruff | clean |
| servers | none left running |

```bash
uv run ruff check .
```

```bash
uv run python -m unittest discover -s tests/unit
```

---

## What was verified end to end, 2026-08-30

Everything below was actually run, not inspected.

| Rung | Result |
|---|---|
| `tests/unit/` | 408 green |
| `tests/checks/safe/bootstrap.py` | 5/5 — 10 agent + 25 internal tools, no SQL tool, profile 28,639 chars over MCP |
| `tests/checks/safe/tools.py` | PASSED — **needs `MCP_TIMEOUT` ≥ 180, see below** |
| `tests/checks/safe/write_gate.py` | 5/5 — refused → `capability_blocked`, approved → `capability_invoked`, rows deleted |
| `tests/checks/paid/web.py` | 3 runs, all green (80s, 55s, 40s) |
| `tests/checks/paid/search.py` | 8 ranked passages, 0 without a marker |
| `evals/route/tool_usage.py --dry-run` | 24 labels, spine intact |
| `evals/route/fidelity.py` | **7/7** — the method reaches the container byte for byte |
| `tests/checks/paid/full_flow.py` | ran all 9 turns, real post with page-level source, gate both ways — **3 stale assertions, see below** |
| Blazor UI, live | generator, profile (live MCP + gated save), materials, language switch, budget % |
| One real batch from the button | `titles_ready` in 2m03s, 10/10 distinct titles, source `Cărți` |

---

## Fixed today

- **`search_web` was invisible to the budget.** It is the one model call made
  inside the MCP server with its own client, so nothing metered it. Now writes a
  `web_search` row through `record_usage`, best-effort. Verified live: 4 searches
  → 4 rows → $0.041.
- **`gpt-5` was unpriced**, and `FALLBACK` was mini's rate — so a run on gpt-5
  would have been charged a fifth of what it cost. Priced from the OpenAI page,
  verified 2026-08-30; `FALLBACK` raised to gpt-5's rate so the comment above it
  ("the most expensive row") is true again.
- **`MCP_TIMEOUT` 90 → 180.** `search_web` returns read passages now instead of a
  synthesis, and three consecutive real searches took 80s / 55s / 40s.
- **`tests/checks/paid/full_flow.py` had been dead since 2026-08-27** — a bare
  `RunConfig()` against a `SandboxAgent`. Every production caller passes a
  sandbox, so nothing the client uses was affected.
- **`tests/checks/safe/tools.py`** called `search_books` without the now-required
  `description_en`.
- Empty `evals/output`, `evals/retrieval`, `evals/runs` removed;
  `evals/experiment.py` said "five scores" in two places and has six.

---

## Open, in priority order

**1 · `full_flow.py` has three stale assertions and therefore exits 1.**
Everything it actually exercises passed. The three that fail are checks written
for a shape that no longer exists:

- `skill_activated` never fires. `Audit.turn` derives that event from tool names,
  and skills stopped being tools when the sandbox came back on 2026-08-27 — they
  are shell reads now. **This is also a real observability gap**, not only a stale
  check: the trail no longer records which skill a turn activated. Decide whether
  to re-derive it from the shell commands (`route_from` already does exactly that)
  or to drop the event.
- the five hook types are each expected ≥10 times in the proposal listing. That
  was the pre-D1b single-shot shape. The generator is title-first now: phase 1
  gives ten titles, the five hooks come per idea in phase 2.

Do not "fix" these by loosening the assertion. Decide what the check should assert
about today's flow, then re-run it once — it costs a real conversation.

**2 · Layer 3 of the eval pyramid is empty.** Nothing automated grades what the
studio *writes*. See `docs/CASE-STUDY.md` §4.

**3 · The repository is PRIVATE, and `content/profile.md` is tracked.** Making it
public to show recruiters would publish the client's full brand profile and 28 of
her posts. That is her material and her decision — see the note in the reply that
accompanied this handoff.

**4 · The paid route spine (24 squares) has not been re-run** since the two
`SKILL.md` edits of this week. Last result was 24/24 on 2026-08-28.

---

## Costs incurred today

Roughly $0.35 in total: two Phoenix experiments ($0.10), four web searches
($0.04), one full flow of nine turns, one real batch of ten titles, plus the
paid checks.
