"""One-off maintenance on an existing database. No model calls, ever.

    uv run python -m content_studio.db.migrate rename            (dry run)
    uv run python -m content_studio.db.migrate rename --apply

`rename` moves a database created with Romanian identifiers to the English schema
in schema.sql. Run it BEFORE db.apply — otherwise db.apply creates empty English
tables beside the Romanian ones and the data is left behind. It is idempotent, so
running it on an already-migrated database changes nothing.

There used to be a `backfill` command here, which reconstructed the cover sheet of
old conversations from the audit trail. Decision 11 removed the `conversations`
table, so it has nothing left to fill in.

The one-way change of Decision 11 itself is not a subcommand: it is
`db/reset_for_deployment.sql`, applied once, deliberately, after a Neon branch.
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

RENAME_SQL_FILE = Path(__file__).parent / "rename_to_english.sql"

# What the Romanian schema looks like, so a dry run can say what is still there.
ROMANIAN_LEFTOVERS = """
SELECT 'table  ' || c.relname AS item
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r'
   AND c.relname IN ('client', 'postari')
UNION ALL
SELECT 'column ' || table_name || '.' || column_name
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND column_name IN ('nume', 'profil_md', 'creat_la', 'actualizat_la', 'data',
                       'titlu', 'pilon', 'tip_hook', 'hashtaguri', 'sursa',
                       'corp_md', 'fisier_sursa')
UNION ALL
-- These three use EXISTS rather than LIMIT: a LIMIT inside a UNION branch needs
-- parentheses in Postgres, and one forgotten pair is a syntax error at runtime.
SELECT 'value  documents.source = biblioteca'
 WHERE EXISTS (SELECT 1 FROM public.documents WHERE source = 'biblioteca')
UNION ALL
SELECT 'keys   documents.metadata (Romanian)'
 WHERE EXISTS (SELECT 1 FROM public.documents
                WHERE metadata ?| ARRAY['autor', 'clasa', 'versiune', 'temei_drepturi'])
UNION ALL
SELECT 'keys   embeddings.metadata (Romanian)'
 WHERE EXISTS (SELECT 1 FROM public.embeddings WHERE metadata ?| ARRAY['pagina', 'capitol'])
 ORDER BY 1
"""

# There used to be a fourth check here, for the Romanian action names left in
# `audit_log` ('aprobare_ceruta' and friends). D4 replaced that table with the
# course's (run_id, event) shape, so the column those values lived in is gone and
# the check with it.
COUNTS = """
SELECT (SELECT count(*) FROM public.documents)  AS documents,
       (SELECT count(*) FROM public.embeddings) AS embeddings
"""

async def rename(engine, apply: bool) -> int:
    async with engine.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        leftovers = [r["item"] for r in await raw.fetch(ROMANIAN_LEFTOVERS)]
        before = dict(await raw.fetchrow(COUNTS))

    if not leftovers:
        print("Nothing to rename — the database already speaks English.")
        return 0

    print(f"Romanian names still in place ({len(leftovers)}):")
    for item in leftovers:
        print(f"  · {item}")

    if not apply:
        print("\nNothing was written. Add --apply to perform the rename.")
        return 0

    sql = RENAME_SQL_FILE.read_text(encoding="utf-8")
    async with engine.begin() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        await raw.execute(sql)

    async with engine.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        remaining = [r["item"] for r in await raw.fetch(ROMANIAN_LEFTOVERS)]
        after = dict(await raw.fetchrow(COUNTS))

    print("\nRow counts, before → after (they must not move):")
    for key in ("documents", "embeddings"):
        arrow = "✓" if before[key] == after[key] else "✗ CHANGED"
        print(f"  {arrow:<10} {key:<12} {before[key]:>6} → {after[key]:>6}")

    if remaining:
        print("\nStill Romanian after the migration:", file=sys.stderr)
        for item in remaining:
            print(f"  · {item}", file=sys.stderr)
        return 1

    print("\nRenamed. Next: uv run python -m content_studio.db.apply")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rename_parser = sub.add_parser("rename", help="Romanian schema → English schema")
    rename_parser.add_argument("--apply", action="store_true", help="write to Neon")

    args = parser.parse_args()

    # DDL, so the direct endpoint — never `-pooler`. See config.migration_url.
    try:
        url, connect_args = migration_url()
    except MissingConfig as e:
        print(e, file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}")
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        return await rename(engine, args.apply)
    except Exception as e:  # noqa: BLE001
        print(f"{args.command} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
