"""One reader, so every grader looks at the same thing.

    uv run python evals/traces.py --hours 24
    uv run python evals/traces.py --run <run_id>
    uv run python evals/traces.py --hours 24 --json

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

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]

    @property
    def retrieved(self) -> list[Any]:
        """The passages the shelf actually returned, flattened across calls.

        Empty means this is not a retrieval run - which is a fact Ragas needs,
        not a failure. A run that searched and found nothing is also empty here,
        and `searched` is what tells the two apart.
        """
        passages: list[Any] = []
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
        return RETRIEVAL_TOOL in self.tool_names

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "status": self.status,
            "input_message": self.input_message,
            "output_message": self.output_message,
            "tools": self.tool_names,
            "retrieved": len(self.retrieved),
            "searched": self.searched,
            "response_ids": self.response_ids,
            "failed_turns": self.failed_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


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
    finally:
        await engine.dispose()
    return build_runs(list(rows), list(spans))


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
        if run.searched:
            print(f"    pasaje : {len(run.retrieved)} din {RETRIEVAL_TOOL}")
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
