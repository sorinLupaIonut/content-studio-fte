"""Apply a SQL file to the database. Decision 3, extended at D4.

    uv run python -m content_studio.db.apply
    uv run python -m content_studio.db.apply --file migration_d4_course_schema.sql

With no arguments it applies `schema.sql`, which is idempotent — everything is
`CREATE ... IF NOT EXISTS` — so run it as often as you like. It prints the tables
that exist afterwards, so you can see the acceptance criterion with your own eyes
instead of taking it on trust.

WHICH ENDPOINT (D4): this script runs DDL, so it takes the DIRECT one through
`migration_url()` and refuses `-pooler`. The app keeps using the pooled endpoint.
If `DATABASE_URL_DIRECT` is missing, the refusal says exactly what to add.

Why not through SQLAlchemy directly: a SQL file holds several statements, and the
asyncpg dialect sends every `text()` as a prepared statement — and a prepared
statement takes exactly one command. Dropping down to the raw asyncpg connection,
`execute()` runs the whole script as a simple query.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, describe_database, migration_url

enable_utf8_output()

HERE = Path(__file__).parent

# What has to exist at the end. `agent_sessions` and `agent_messages` are NOT
# here: SQLAlchemySession creates them on the worker's first run, not this script.
# `conversations` and `capability_invocations` left at Decision 11;
# `pending_runs` left at D4 — see the header of schema.sql for both.
EXPECTED = [
    "documents",
    "embeddings",
    "clients",
    "posts",
    "runs",
    "traces",
    "artifacts",
    "audit_log",
]

TABLE_QUERY = """
SELECT c.relname AS table_name,
       COALESCE(s.n_live_tup, 0) AS row_count
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
 WHERE n.nspname = 'public' AND c.relkind = 'r'
 ORDER BY c.relname
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        default="schema.sql",
        help="SQL file to apply, relative to db/ (default: schema.sql)",
    )
    args = parser.parse_args()

    sql_file = Path(args.file)
    if not sql_file.is_absolute():
        sql_file = HERE / sql_file
    if not sql_file.is_file():
        print(f"No such SQL file: {sql_file}", file=sys.stderr)
        return 1

    try:
        url, connect_args = migration_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}")
    print(f"Applying: {sql_file.name}")

    sql = sql_file.read_text(encoding="utf-8")
    engine = create_async_engine(url, connect_args=connect_args, echo=False)

    try:
        async with engine.begin() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(sql)

        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            rows = await raw.driver_connection.fetch(TABLE_QUERY)
    except Exception as e:  # noqa: BLE001 — the raw message is the point here
        print(f"\nApplying {sql_file.name} failed:\n  {type(e).__name__}: {e}", file=sys.stderr)
        if "vector" in str(e).lower():
            print(
                "\nIf this is about the `vector` extension: on Neon you enable it with\n"
                "  CREATE EXTENSION vector;\n"
                "from their SQL Editor, and the account needs permission to create extensions.",
                file=sys.stderr,
            )
        return 1
    finally:
        await engine.dispose()

    found = {r["table_name"]: r["row_count"] for r in rows}

    # EXPECTED describes what schema.sql builds. A migration file is applied for
    # what it removes, so checking it against that list would report failure for
    # doing its job — list the result and stop there.
    if sql_file.name != "schema.sql":
        print(f"\n{sql_file.name} applied. Tables in public:")
        for name, count in sorted(found.items()):
            print(f"  ·           {name:<24} {count:>6} rows")
        print("\nNext: uv run python -m content_studio.db.apply")
        return 0

    print("\nTables in public:")
    for name in EXPECTED:
        mark = "✓" if name in found else "✗ MISSING"
        count = f"{found.get(name, 0):>6} rows" if name in found else ""
        print(f"  {mark:<11} {name:<24} {count}")

    extra = sorted(set(found) - set(EXPECTED))
    if extra:
        print("\nAlso present (created by the SDK, or by you):")
        for name in extra:
            print(f"  ·           {name:<24} {found[name]:>6} rows")

    missing = [n for n in EXPECTED if n not in found]
    if missing:
        print(f"\nMissing: {', '.join(missing)}", file=sys.stderr)
        if "postari" in found or "client" in found:
            print(
                "The Romanian tables are still there. Run the rename first:\n"
                "  uv run python -m content_studio.db.migrate rename --apply",
                file=sys.stderr,
            )
        return 1

    print(f"\n{sql_file.name} applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
