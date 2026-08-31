"""Which `references/` file was supposed to reach the model, and whether it did.

    uv run python evals/route/references.py                 the static audit, free
    uv run python evals/route/references.py --traces        what real runs actually asked for
    uv run python evals/route/references.py --traces --minutes 30
    uv run python evals/route/references.py --traces --run <run_id>

A reference fails silently. Nothing raises, nothing logs, the answer still
arrives - written from memory instead of from the method. Until 2026-08-24 that
was the state of all 126 KB of it, and the only reason anyone found out was a
batch of ten titles that read wrong.

So there are two questions, and this script keeps them apart:

  · **was it ever going to fire?** The default. Static, free, and answerable
    without a model: is the file on disk, does the manifest declare a trigger for
    it, and does a SKILL.md actually name it? A file nothing points at cannot be
    called no matter how good the run is.

  · **did it fire?** `--traces`. Reads `public.traces`, where every tool call is
    a `function` span carrying its own arguments, and counts what was asked for.

Run the first before rewriting a SKILL.md and the second after, on a real batch.
The gap between them is the work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import SKILLS_DIR, MissingConfig, database_url

# The shell tool's name lives in `sandbox.py`, with the container it belongs to:
# `audit.py`, `generator.py` and this file all ask the same question of it.
from content_studio.sandbox import SHELL_TOOL_NAME
from content_studio.worker import reference_index

MANIFEST = Path(__file__).with_name("references.json")


#: `public.traces` holds two kinds of row per run, and only one of them is ours:
#: `close_run` writes `{"output": reply}`, and `RunTraceProcessor.on_trace_end`
#: writes `{"run_id", "trace", "spans": [...]}`. So the spans are an ARRAY inside
#: the payload, not the payload - hence the unnest. Guessing this shape from the
#: outside costs one wrong query that returns zero rows and looks like an answer.
SPANS = """
  FROM public.traces t,
       jsonb_array_elements(t.payload->'spans') AS span
 WHERE t.payload ? 'spans'
"""

#: Every shell call, newest first. `span_data` carries the arguments, which is
#: the difference between knowing the shell was used and knowing WHICH file it
#: opened.
#:
#: IT USED TO BE ONE TOOL PER FILE. Until 2026-08-27 a reference was fetched by
#: `citeste-referinta("skill/file.md")`, so the span named the file in a JSON
#: field and counting was a `json.loads`. Since the method moved into a sandbox
#: the model opens files with `exec_command`, so the file name is somewhere
#: inside a shell command - `sed -n '1,200p' .agents/x/references/y.md`, or a
#: `cat`, or an `rg`. There is no field to read; the filenames are matched
#: against the command text instead. That is looser on purpose: a query that
#: only understood `sed` would report zero for a run that used `cat` and look
#: exactly like a run that never opened the method.
CALLS_SQL = f"""
SELECT t.run_id,
       span->'span_data'->>'input' AS input,
       t.created_at
{SPANS}
   AND span->'span_data'->>'type' = 'function'
   AND span->'span_data'->>'name' = $1
   AND ($2::text IS NULL OR t.run_id = $2)
   AND ($2::text IS NOT NULL OR t.created_at > now() - ($3 || ' minutes')::interval)
 ORDER BY t.created_at DESC
"""

#: How many model turns happened in the same window. Without it, "no reference
#: was read" and "nothing ran at all" look identical in the report.
RUNS_SQL = f"""
SELECT count(*)
{SPANS}
   AND span->'span_data'->>'type' = 'response'
   AND ($1::text IS NULL OR t.run_id = $1)
   AND ($1::text IS NOT NULL OR t.created_at > now() - ($2 || ' minutes')::interval)
"""

RULE = "-" * 88


def manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["references"]


def named_in_skill(reference: str) -> bool:
    """Does the skill's own body point at this file?

    Matched on the bare filename, not the full key: SKILL.md writes
    `references/piloni.md` today and will write `propune-postari/piloni.md` after
    the rewrite. Both contain the filename, so this check survives the very
    rewrite it exists to measure.
    """
    skill, _, filename = reference.partition("/")
    body = SKILLS_DIR / skill / "SKILL.md"
    return body.is_file() and filename in body.read_text(encoding="utf-8")


def shell_reads(inputs: Iterable[str | None]) -> Counter[str]:
    """Which references these shell commands opened, counted once per command.

    Once per command, not once per mention: a model that writes
    `cat a.md b.md` opened two files, but one that writes
    `sed -n '1,200p' a.md; sed -n '200,400p' a.md` opened one file twice and
    should not read as two references. The key is the manifest key, so the
    output lines up with `references.json` without a second mapping.
    """

    by_filename = {key.split("/", 1)[1]: key for key in reference_index()}
    found: Counter[str] = Counter()
    for raw in inputs:
        command = raw or ""
        for filename, key in by_filename.items():
            if filename in command:
                found[key] += 1
    return found


def audit() -> int:
    """The static half: on disk, declared in the manifest, pointed at by a skill."""

    on_disk = reference_index()
    declared = {entry["file"]: entry for entry in manifest()}
    unpointed: list[str] = []
    undeclared: list[str] = []

    print(f"{'reference':<44}{'KB':>5}  disk  manif  SKILL  trigger")
    print(RULE)
    for name in sorted(set(on_disk) | set(declared)):
        path = on_disk.get(name)
        entry = declared.get(name)
        size = f"{path.stat().st_size / 1024:.0f}" if path else "-"
        pointed = named_in_skill(name) if path else False
        if entry is None:
            trigger = "NOT DECLARED"
            undeclared.append(name)
        else:
            trigger = "proposed" if entry.get("proposed") else "decided"
        if path and not pointed:
            unpointed.append(name)
        marks = [
            "yes" if path else "NO",
            "yes" if entry else "NO",
            "yes" if pointed else "NO",
        ]
        print(f"{name:<44}{size:>5}  {marks[0]:<5} {marks[1]:<6} {marks[2]:<6} {trigger}")

    def listing(title: str, names: list[str]) -> None:
        if names:
            print(f"\n{title} ({len(names)}):")
            for name in names:
                print(f"  - {name}")

    listing("NOT NAMED BY ANY SKILL.md - these cannot fire at all", unpointed)
    listing("NOT IN THE MANIFEST - nobody said when they should fire", undeclared)
    listing("DECLARED BUT NOT ON DISK", sorted(set(declared) - set(on_disk)))
    listing(
        "TRIGGER STILL A PROPOSAL - waiting for a verdict",
        [entry["file"] for entry in manifest() if entry.get("proposed")],
    )
    print(f"\n{len(unpointed)} of {len(on_disk)} references are unreachable today.")
    return 1 if unpointed or undeclared else 0


async def traces(run: str | None, minutes: int) -> int:
    """The live half: what real runs actually asked for."""

    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            rows = await conn.fetch(CALLS_SQL, SHELL_TOOL_NAME, run, str(minutes))
            turns = await conn.fetchval(RUNS_SQL, run, str(minutes))
    finally:
        await engine.dispose()

    window = f"run {run}" if run else f"the last {minutes} minutes"
    if not turns:
        print(f"No model turns in {window}. Nothing to judge.")
        return 1

    asked = shell_reads(row["input"] for row in rows)

    declared = {entry["file"]: entry for entry in manifest()}
    print(f"{turns} model turns in {window}, {sum(asked.values())} reference reads.\n")
    print(f"{'reference':<44}{'reads':>6}  when it should fire")
    print(RULE)
    for name in sorted(set(declared) | set(asked)):
        when = declared.get(name, {}).get("when", "NOT DECLARED")
        print(f"{name:<44}{asked.get(name, 0):>6}  {when[:36]}")

    silent = sorted(set(declared) - set(asked))
    if silent:
        print(f"\nNEVER ASKED FOR ({len(silent)} of {len(declared)}):")
        for name in silent:
            print(f"  - {name}")
    return 0


def main() -> int:
    enable_utf8_output()
    parser = argparse.ArgumentParser(description="Reference activation audit.")
    parser.add_argument("--traces", action="store_true", help="read public.traces")
    parser.add_argument("--run", default=None, help="one run_id instead of a window")
    parser.add_argument("--minutes", type=int, default=15, help="window, default 15")
    options = parser.parse_args()
    if options.traces:
        return asyncio.run(traces(options.run, options.minutes))
    return audit()


if __name__ == "__main__":
    raise SystemExit(main())
