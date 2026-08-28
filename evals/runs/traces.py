"""One reader, so every grader looks at the same thing.

    uv run python evals/runs/traces.py --hours 24
    uv run python evals/runs/traces.py --run <run_id>
    uv run python evals/runs/traces.py --hours 24 --json

CONCEPT 12'S ONE ARCHITECTURAL CLAIM is that traces are the integration point:
everything an eval grades is read from a trace, and the traces live in two
stores - Neon for the durable record, Phoenix for the live sample. This module
is the Neon half, written once so `grade.py`, `promote.py` and the CI gate all
see the same shape. Two readers with two ideas of what "the tools it called"
means is two verdicts and no way to reconcile them.

WHAT NEON HAS, VERIFIED ON 2026-08-24 rather than assumed:

  · `public.runs`      - the request and the final reply, one row per run
  · `function` spans   - EVERY tool call, with its `input` AND its `output`.
                         233 of them at the time of checking. This is what makes
                         tool-correctness and attribution gradable at all.
  · `response` spans   - `response_id` and the token usage. NOT the messages.

That last line is the limit, and it decides the shape of everything downstream:
Neon can tell you WHICH tools ran and WHAT the run finally said, but not what
the model was shown or what it reasoned. For that there are two doors, and
`GradedRun` carries the key to both - `response_ids`, which the provider will
still trade for the full response, and `run_id`, which finds the same run in
Phoenix.

`public.traces` holds two kinds of row per run and only one is ours: `close_run`
writes `{"output": reply}`, `RunTraceProcessor.on_trace_end` writes
`{"run_id", "trace", "spans": [...]}`. The spans are an ARRAY inside the
payload, hence the unnest - the same shape `references.py` documented first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url

#: The tool that reaches the shelf. Named here rather than inlined because
#: `retrieved` is what decides whether a run is a RAG run, and Ragas grades only
#: those - a typo in this string silently empties that half of the report.
RETRIEVAL_TOOL = "search_books"

#: THE PASSAGES HAVE TWO SHAPES, AND ASSUMING ONE COST THIS MODULE A REWRITE.
#: Until 2026-08-27 the generation path never called `search_books` from the
#: model: `collect_source_packet` called it server-side, BEFORE `Audit.open_run`
#: - so those batches have no retrieval span, only a `source_packet` full of
#: passages (measured 2026-08-25: source `Cărți`, two runs, both `unelte:
#: niciuna`). Since 2026-08-27 the pre-collection is gone and the agent calls
#: `search_books` itself, so new runs DO have the span and their batches store
#: an empty packet. Both doors below stay: the packet one reads the old
#: batches, the span one reads everything new. A run is tied to its batch
#: two ways, both of them strings this codebase writes itself:
#:
#:   · a title run shares the batch's `session_id`
#:   · a detail run names the batch in `input_message` - "din lotul 62dfb546"
#:
#: Neither is elegant. The alternative was a schema change to hang a batch id on
#: `runs`, which is the right fix and a bigger one; this is written down so the
#: next person can make it deliberately rather than discover it.
BATCH_IN_MESSAGE = re.compile(r"din lotul ([0-9a-f]{8})", re.IGNORECASE)

#: Same unnest `references.py` uses. Restated rather than imported: that module
#: is a command-line audit of one question, and importing a private SQL constant
#: across two scripts couples them for no gain.
SPANS_FROM = """
  FROM public.traces t,
       jsonb_array_elements(t.payload->'spans') AS span
 WHERE t.payload ? 'spans'
"""

#: One row per run in the window. LEFT JOIN on nothing - the spans come in a
#: second query, because a run with forty spans would otherwise arrive forty
#: times and the reply text with it.
RUNS_SQL = """
SELECT r.id,
       r.session_id,
       r.input_message,
       r.output_message,
       r.status,
       r.created_at
  FROM public.runs r
 WHERE ($1::text IS NULL OR r.id = $1)
   AND ($1::text IS NOT NULL
        OR r.created_at > now() - ($2 || ' hours')::interval)
 ORDER BY r.created_at DESC
"""

#: Every span that carries something a grader can read. Ordered oldest first
#: inside a run, so `tool_calls` reads in the order they happened.
SPANS_SQL = f"""
SELECT t.run_id,
       span->'span_data'->>'type'        AS span_type,
       span->'span_data'->>'name'        AS name,
       span->'span_data'->>'input'       AS input,
       span->'span_data'->>'output'      AS output,
       span->'span_data'->>'response_id' AS response_id,
       span->'span_data'->'usage'        AS usage,
       span->>'error'                    AS error,
       t.created_at
{SPANS_FROM}
   AND t.run_id = ANY($1::text[])
   AND span->'span_data'->>'type' IN ('function', 'response')
 ORDER BY t.created_at ASC
"""


@dataclass(slots=True)
class ToolCall:
    """One tool call, with both ends of it.

    `output` is the part that matters and the part a trace usually loses. Here
    it survives, which is why `attribution` can ask whether a quote in the final
    text was in a passage the search actually returned.
    """

    name: str
    input: str
    output: str

    def parsed_input(self) -> Any:
        """The arguments as data, or the raw string when it will not parse."""
        try:
            return json.loads(self.input or "")
        except (ValueError, TypeError):
            return self.input

    def parsed_output(self) -> Any:
        try:
            return json.loads(self.output or "")
        except (ValueError, TypeError):
            return self.output


#: Batches overlapping the window, with the material gathered for them. Wider
#: than the run window on purpose: she can open an idea days after the batch was
#: written, and the passages that idea was built from are still that batch's.
BATCHES_SQL = """
SELECT b.id,
       b.session_id,
       b.source,
       b.format,
       b.pillar,
       b.source_packet
  FROM public.generation_batches b
 WHERE b.created_at > now() - ($1 || ' hours')::interval
"""


@dataclass(slots=True)
class GradedRun:
    """One run, in the shape every grader reads.

    Deliberately dumb: no scoring, no judgement, no network. A reader that
    decides anything is a reader two graders will disagree about.
    """

    run_id: str
    session_id: str
    started_at: datetime
    status: str
    input_message: str
    output_message: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    response_ids: list[str] = field(default_factory=list)
    failed_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: The batch this run belongs to, when it belongs to one. Carries `source`,
    #: `format` and the gathered passages - none of which a span knows.
    batch: dict[str, Any] | None = None

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]

    @property
    def retrieved(self) -> list[Any]:
        """The passages this run was written from, wherever they came in.

        Two doors, one of them historical: the batch's `source_packet`, which
        is how generation got its material until 2026-08-27, and a
        `search_books` span, which is how chat always got it and how generation
        gets it now. Empty means this was not a retrieval run -
        a fact Ragas needs, not a failure. `searched` is what separates "never
        asked the shelf" from "asked and it was silent".
        """
        passages: list[Any] = []
        packet = (self.batch or {}).get("source_packet") or {}
        books = packet.get("books")
        if isinstance(books, list):
            passages.extend(books)
        for call in self.tool_calls:
            if call.name != RETRIEVAL_TOOL:
                continue
            value = call.parsed_output()
            if isinstance(value, list):
                passages.extend(value)
            elif value:
                passages.append(value)
        return passages

    @property
    def searched(self) -> bool:
        """Whether the shelf was consulted at all, found or not."""
        if RETRIEVAL_TOOL in self.tool_names:
            return True
        source = (self.batch or {}).get("source")
        return source in {"Cărți", "Combinat"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "status": self.status,
            "input_message": self.input_message,
            "output_message": self.output_message,
            "tools": self.tool_names,
            "batch_id": (self.batch or {}).get("id"),
            "source": (self.batch or {}).get("source"),
            "format": (self.batch or {}).get("format"),
            "retrieved": len(self.retrieved),
            "searched": self.searched,
            "response_ids": self.response_ids,
            "failed_turns": self.failed_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


def attach_batches(runs: list[GradedRun], batches: list[Any]) -> None:
    """Tie each run to the batch it belongs to. Pure, and tested.

    Two keys, in order of trust: the shared `session_id`, which the harness
    writes for a title run, and the batch id printed into a detail run's
    `input_message`. A run that matches neither keeps `batch = None` and is
    simply not a retrieval run, which is the honest answer for chat.
    """

    by_session: dict[str, dict[str, Any]] = {}
    by_prefix: dict[str, dict[str, Any]] = {}
    for row in batches:
        record = {
            "id": str(row["id"]),
            "session_id": str(row["session_id"]),
            "source": row["source"],
            "format": row["format"],
            "pillar": row["pillar"],
            "source_packet": _as_dict(row["source_packet"]),
        }
        by_session[record["session_id"]] = record
        by_prefix[record["id"][:8].lower()] = record

    for run in runs:
        found = by_session.get(run.session_id)
        if found is None:
            match = BATCH_IN_MESSAGE.search(run.input_message or "")
            if match:
                found = by_prefix.get(match.group(1).lower())
        run.batch = found


def _as_dict(value: Any) -> dict[str, Any]:
    """asyncpg gives jsonb back as a dict; a fixture may give a string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_runs(rows: list[Any], spans: list[Any]) -> list[GradedRun]:
    """Assemble runs and their spans. Pure, so the tests need no database."""

    runs: dict[str, GradedRun] = {}
    for row in rows:
        runs[str(row["id"])] = GradedRun(
            run_id=str(row["id"]),
            session_id=str(row["session_id"]),
            started_at=row["created_at"],
            status=str(row["status"]),
            input_message=str(row["input_message"] or ""),
            output_message=row["output_message"],
        )

    for span in spans:
        run = runs.get(str(span["run_id"]))
        if run is None:
            # A span whose run row is gone. Possible after a partial cleanup,
            # and not worth failing the whole read over.
            continue
        if span["span_type"] == "function":
            run.tool_calls.append(
                ToolCall(
                    name=str(span["name"] or "?"),
                    input=str(span["input"] or ""),
                    output=str(span["output"] or ""),
                )
            )
            continue
        if span["response_id"]:
            run.response_ids.append(str(span["response_id"]))
        usage = span["usage"]
        if isinstance(usage, str):
            try:
                usage = json.loads(usage)
            except ValueError:
                usage = None
        if isinstance(usage, dict):
            run.input_tokens += int(usage.get("input_tokens") or 0)
            run.output_tokens += int(usage.get("output_tokens") or 0)
        if span["error"] and span["error"] != "null":
            run.failed_turns += 1

    return list(runs.values())


async def read(hours: int = 24, run_id: str | None = None) -> list[GradedRun]:
    """Every run in the window, with its tool calls attached."""

    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            rows = await conn.fetch(RUNS_SQL, run_id, str(hours))
            if not rows:
                return []
            ids = [str(row["id"]) for row in rows]
            spans = await conn.fetch(SPANS_SQL, ids)
            # Deliberately wider than the run window: an idea opened days later
            # was still written from that batch's passages.
            batches = await conn.fetch(BATCHES_SQL, str(max(hours, 24) * 30))
    finally:
        await engine.dispose()
    runs = build_runs(list(rows), list(spans))
    attach_batches(runs, list(batches))
    return runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="What the graders will see. Reads Neon, calls no model."
    )
    parser.add_argument("--hours", type=int, default=24, help="window, default 24")
    parser.add_argument("--run", dest="run_id", help="one run instead of a window")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument(
        "--out", type=Path, help="write the JSON here as well as printing it"
    )
    return parser


def report(runs: list[GradedRun]) -> None:
    if not runs:
        print(
            "Nicio rulare în interval.\n"
            "Nu e o defecțiune: graderul notează doar ce a văzut. Generează un "
            "lot din interfață și încearcă iar."
        )
        return

    print(f"{len(runs)} rulări\n")
    for run in runs:
        reply = (run.output_message or "").replace("\n", " ")
        print(f"{run.started_at:%Y-%m-%d %H:%M}  {run.run_id[:12]}  {run.status}")
        print(f"    cerere : {run.input_message[:70]}")
        print(f"    răspuns: {reply[:70] or '(niciunul)'}")
        if run.tool_calls:
            print(f"    unelte : {', '.join(run.tool_names)}")
        else:
            print("    unelte : niciuna")
        if run.batch:
            print(
                f"    lot    : {run.batch['id'][:8]}  "
                f"{run.batch['format']} · {run.batch['source']}"
            )
        if run.searched:
            print(f"    pasaje : {len(run.retrieved)} din bibliotecă")
        if run.failed_turns:
            print(f"    ture picate: {run.failed_turns}")
        print(
            f"    tokeni : {run.input_tokens:,} in / {run.output_tokens:,} out"
            f"  ({len(run.response_ids)} apeluri de model)"
        )
        print()

    searched = sum(1 for run in runs if run.searched)
    print(f"cu retrieval: {searched} din {len(runs)} — restul nu intră la Ragas")


async def main() -> int:
    args = build_parser().parse_args()
    try:
        runs = await read(hours=args.hours, run_id=args.run_id)
    except MissingConfig as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    payload = [run.as_dict() for run in runs]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        report(runs)
    if args.out:
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nscris în {args.out}")
    return 0


if __name__ == "__main__":
    enable_utf8_output()
    raise SystemExit(asyncio.run(main()))
