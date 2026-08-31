# Handoff — 2026-08-31

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

## 2026-08-31 — the documentation currency pass

Sorin read the architecture diagram and asked two questions that were both right:
why `SandboxAgent` is on it (it is correct — the sandbox came back on 2026-08-27),
and whether the ten output rules still exist (**they do not**). That opened a
sweep of every doc against the code. `tests/checks/safe/prompt.py` is the proof:
the system prompt is four parts — voice, method note, tool note, profile — and no
rules.

**Fixed in code, not only in prose:**

- `mcp_server/server.py` printed `content-data · five agent tools` on startup
  while ten were registered. It counts `MODEL_VISIBLE_TOOLS` and
  `INTERNAL_UI_TOOLS` now — a hand-written number is a second source of truth.
- `db/provision.py --list` **crashed** with `TypeError` on any client nobody has
  signed in as, which is exactly the row it exists to show (the listing is of
  clients, not sign-ins). `viorela` is such a row today.
- `language.py`'s English override told the model "Rule 7 holds with full force" —
  a reference to a rule that has not existed since 2026-08-26. It states the rule
  itself now.
- `tests/checks/safe/prompt.py` said the profile placeholder stood in for 6 KB;
  it is 28,639 characters.

**Corrected in the docs**, each verified against the code or the database:

| Was | Is |
|---|---|
| `ARCHITECTURE.md`: profile + ten output rules in the prompt | four parts, no rules |
| `ARCHITECTURE.md`: five model-visible tools | ten, plus 25 internal |
| `ARCHITECTURE.md`: `conversations` was removed at Decision 11 | a different table under the same name came back 2026-08-27 |
| `ARCHITECTURE.md`: `traces` holds one payload per run | two kinds of row, same `run_id` |
| `ARCHITECTURE.md`: the generator gathers a source packet, offers 3–4 books, five concurrent detail jobs | no packet, no picker, details are lazy — one, when she opens it |
| `ARCHITECTURE.md`: phase 1 shows 10 proposals × 5 hooks | ten titles; the hooks are phase 2 |
| `ARCHITECTURE.md` / `CASE-STUDY.md`: 18 tables | 16 — fourteen ours, two the SDK's |
| `ARCHITECTURE.md`: access limited to two Google identities | multi-tenant, two providers, scoped library |
| `CASE-STUDY.md` lever 3: one container per **batch** | one per **run** — and the real lever is that nine of ten details are never written, $0.0733 of $0.0770 |
| `README.md`: skills delivered as tools | mounted into the container |
| `README.md` / `TESTING.md`: VS Code targets `Studio complet (3 servicii)` etc. | `.vscode/launch.json` was rewritten 2026-08-24; the names are `1.`–`6.` and `Site complet` |
| `TESTING.md`: the manual test is `uv run content-studio --new` | that entry point does not exist; the manual test is the site |
| `TESTING.md`: unit tests run in CI on every push | CI has been paused since 2026-08-28 |
| `manual.html`: 29 tools; Phoenix is not here; 173 tests | 10 + 25; Phoenix since 2026-08-23; 408 |
| `AGENTS.md`: one eval group left | three, plus `experiment.py` |
| `plans/DEPLOYMENT.md` | left as the record, with a dated note naming the four things that have changed under it |

**The pattern worth keeping:** every number that was hand-written drifted, and
every number read off the code did not. Where the fix was cheap, the number is now
computed (the server banner). Where it is not, it carries the date it was measured.

---

## Costs incurred today

**2026-08-30:** roughly $0.35 in total — two Phoenix experiments ($0.10), four web
searches ($0.04), one full flow of nine turns, one real batch of ten titles, plus
the paid checks.

**2026-08-31:** nothing. The currency pass used `ruff`, the 408 unit tests,
`tests/checks/safe/prompt.py`, `evals/route/tool_usage.py --dry-run` and two
read-only database queries. No model call, no container.
