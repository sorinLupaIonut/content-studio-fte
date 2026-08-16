"""Apply db/schema.sql to the database in DATABASE_URL. Decision 3.

    uv run python -m content_studio.db.apply

Idempotent — everything is `CREATE ... IF NOT EXISTS`, so run it as often as you
like. It prints the tables that exist afterwards, so you can see Decision 3's
acceptance criterion with your own eyes instead of taking it on trust.

Why not through SQLAlchemy directly: `schema.sql` holds several statements in one
file, and the asyncpg dialect sends every `text()` as a prepared statement — and a
prepared statement takes exactly one command. Dropping down to the raw asyncpg
connection, `execute()` runs the whole script as a simple query.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url, describe_database

enable_utf8_output()

SCHEMA = Path(__file__).parent / "schema.sql"

# What has to exist at the end. The first five are the Concept 7 backbone, the
# last two are the domain from §3. `agent_sessions` and `agent_messages` are NOT
# here: SQLAlchemySession creates them on the worker's first run, not this script.
EXPECTED = [
    "conversations",
    "documents",
    "embeddings",
    "audit_log",
    "capability_invocations",
    "clients",
    "posts",
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
    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}")
    print(f"Schema  : {SCHEMA}")

    sql = SCHEMA.read_text(encoding="utf-8")
    engine = create_async_engine(url, connect_args=connect_args, echo=False)

    try:
        async with engine.begin() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(sql)

        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            rows = await raw.driver_connection.fetch(TABLE_QUERY)
    except Exception as e:  # noqa: BLE001 — the raw message is the point here
        print(f"\nApplying the schema failed:\n  {type(e).__name__}: {e}", file=sys.stderr)
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

    print("\nSchema applied. Next: uv run python -m content_studio.db.seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
