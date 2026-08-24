"""Clear the evidence of testing, and nothing else.

    uv run python -m content_studio.db.cleanup_test_data              # counts only
    uv run python -m content_studio.db.cleanup_test_data --confirm    # deletes

WHAT IT TOUCHES, AND WHY THAT LIST. Three groups, in an order the foreign keys
allow:

    generation_variants -> generation_ideas -> generation_batches
    traces, audit_log, artifacts -> runs
    usage_events

`audit_log` and `artifacts` are in that list because `runs` cannot leave without
them - both carry a foreign key to it. That is not a technicality worth hiding:
`audit_log` is the audit trail, a named architectural feature, and this empties
it. It is the audit OF the same test runs, so keeping it while their `runs` rows
go would leave a trail that explains nothing. Use `--keep-runs` to hold all four
back together.

WHAT IT NEVER TOUCHES, and this is the whole point of the script existing rather
than a `psql` session: `posts` (her work), `documents` (her licensed books),
`clients`, `app_users` and the profile. A cleanup that can reach those is a
cleanup nobody should run twice.

TWO THINGS YOU LOSE, SAID OUT LOUD BECAUSE THE DELETE IS NOT REVERSIBLE:

* `usage_events` is what the budget gate reads. Clearing it sets every account's
  spend back to zero. That is a real change to what the studio will allow, not
  only to what it reports.
* `traces` is the raw material of the eval surface - Concept 12 grades runs by
  reading them. Cleared, the graders have nothing until new runs happen. That is
  the intended state when you want to measure on a clean slate; it is a loss
  otherwise.

Dry run is the default, and `--confirm` is the only way past it. The counts are
printed before and after either way, so "it deleted more than I thought" is a
sentence nobody has to say.

WHICH ENDPOINT: this is business data, not DDL, so it uses the pooled endpoint
like the app - the same choice `db.provision` makes and for the same reason.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url, describe_database

#: Ordered so that a child is always emptied before its parent. Grouped so the
#: report reads the way a person thinks about it, not the way the keys do.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "loturile de generare",
        ("generation_variants", "generation_ideas", "generation_batches"),
    ),
    # `traces`, `audit_log` and `artifacts` all carry a foreign key to `runs`,
    # so they go first or `runs` does not go at all. Found the hard way: the
    # first version listed only `traces` and the delete failed on `audit_log`.
    ("istoricul de rulări", ("traces", "audit_log", "artifacts", "runs")),
    ("contorul de consum", ("usage_events",)),
)

#: Named so the script can say what it is protecting, rather than only what it
#: deletes. Printed on every run.
PRESERVED: tuple[str, ...] = (
    "posts",
    "documents",
    "clients",
    "app_users",
    "profiles",
)

COUNT_SQL = "SELECT count(*) FROM public.{table}"
DELETE_SQL = "DELETE FROM public.{table}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear generation batches, run history and usage counters."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually delete; without it the script only counts",
    )
    parser.add_argument(
        "--keep-runs",
        action="store_true",
        help="leave runs, traces, audit_log and artifacts alone",
    )
    parser.add_argument(
        "--keep-usage",
        action="store_true",
        help="leave usage_events alone, so the budget gate keeps its history",
    )
    return parser


async def _count(conn, table: str) -> int:
    """Zero for a table that does not exist, rather than a crash.

    The script is run against databases at different migration levels - a fresh
    clone has no `traces` until `db.apply` has run once.
    """
    try:
        return int(await conn.fetchval(COUNT_SQL.format(table=table)) or 0)
    except Exception:  # noqa: BLE001 - a missing table is an answer, not a fault
        return -1


async def run(args: argparse.Namespace) -> int:
    try:
        url, connect_args = database_url()
    except MissingConfig as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    print(f"Baza: {describe_database(url)}")
    print(f"Neatinse: {', '.join(PRESERVED)}\n")

    skip: set[str] = set()
    if args.keep_usage:
        skip.add("contorul de consum")
    if args.keep_runs:
        skip.add("istoricul de rulări")
    groups = [(label, tables) for label, tables in GROUPS if label not in skip]

    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection

            before: dict[str, int] = {}
            for label, tables in groups:
                print(label)
                for table in tables:
                    n = await _count(conn, table)
                    before[table] = n
                    shown = "tabel absent" if n < 0 else f"{n:>7,} rânduri"
                    print(f"    {table:<22} {shown}")
            total = sum(n for n in before.values() if n > 0)
            print(f"\n  total de șters: {total:,} rânduri")

            if not args.confirm:
                print(
                    "\nNimic șters. Repetă cu --confirm dacă numerele sunt bune."
                )
                return 0

            # ONE TRANSACTION, AND IT HAS TO BE ASKED FOR EXPLICITLY.
            # `engine.begin()` does NOT cover these statements: SQLAlchemy's
            # transaction lives on its own adapter, and `driver_connection`
            # hands back the bare asyncpg connection underneath it, which runs
            # in autocommit. Measured: the first run raised on `audit_log` and
            # the four deletes before it had already committed. Half a cleanup -
            # batches gone, their runs left behind - is a database nobody can
            # reason about afterwards.
            print()
            async with conn.transaction():
                for _label, tables in groups:
                    for table in tables:
                        if before.get(table, -1) < 0:
                            continue
                        await conn.execute(DELETE_SQL.format(table=table))
                        print(f"  șters  {table}")

            print()
            for _label, tables in groups:
                for table in tables:
                    if before.get(table, -1) < 0:
                        continue
                    n = await _count(conn, table)
                    print(f"    {table:<22} {n:>7,} rânduri rămase")
    finally:
        await engine.dispose()

    print("\nGata. Bugetul fiecărui cont pornește iar de la zero." if not args.keep_usage
          else "\nGata. `usage_events` a rămas neatins.")
    return 0


def main() -> None:
    enable_utf8_output()
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))


if __name__ == "__main__":
    main()
