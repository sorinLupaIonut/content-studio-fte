"""One-off maintenance on an existing database. No model calls, ever.

    uv run python -m content_studio.db.migrate rename            (dry run)
    uv run python -m content_studio.db.migrate rename --apply
    uv run python -m content_studio.db.migrate backfill --apply

`rename` moves a database created with Romanian identifiers to the English schema
in schema.sql. Run it BEFORE db.apply — otherwise db.apply creates empty English
tables beside the Romanian ones and the data is left behind. It is idempotent, so
running it on an already-migrated database changes nothing.

`backfill` fills in the cover sheet of old conversations from the audit trail:
summary, metadata and closing time. Conversations touched in the last hour are
skipped, so a worker that is still running does not get closed behind its back.
The closing time of historical ones is their last known activity, and it is
flagged as estimated rather than presented as fact.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url, describe_database
from content_studio.conversation import update_conversation

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
SELECT 'value  audit_log.action = ' || action
  FROM audit_log
 WHERE action IN ('propuneri_generate', 'postare_aleasa', 'postare_salvata',
                  'profil_actualizat', 'aprobare_ceruta', 'aprobare_respinsa')
 GROUP BY action
UNION ALL
-- These three use EXISTS rather than LIMIT: a LIMIT inside a UNION branch needs
-- parentheses in Postgres, and one forgotten pair is a syntax error at runtime.
SELECT 'value  documents.source = biblioteca'
 WHERE EXISTS (SELECT 1 FROM documents WHERE source = 'biblioteca')
UNION ALL
SELECT 'keys   documents.metadata (Romanian)'
 WHERE EXISTS (SELECT 1 FROM documents
                WHERE metadata ?| ARRAY['autor', 'clasa', 'versiune', 'temei_drepturi'])
UNION ALL
SELECT 'keys   embeddings.metadata (Romanian)'
 WHERE EXISTS (SELECT 1 FROM embeddings WHERE metadata ?| ARRAY['pagina', 'capitol'])
 ORDER BY 1
"""

COUNTS = """
SELECT (SELECT count(*) FROM documents)  AS documents,
       (SELECT count(*) FROM embeddings) AS embeddings,
       (SELECT count(*) FROM audit_log)  AS audit_rows
"""

BACKFILL_CANDIDATES = """
WITH activity AS (
    SELECT conversation_id, max(created_at) AS last_activity
      FROM audit_log
     WHERE conversation_id IS NOT NULL
     GROUP BY conversation_id
)
SELECT c.session_id,
       COALESCE(a.last_activity, c.started_at) AS last_activity
  FROM conversations c
  LEFT JOIN activity a ON a.conversation_id = c.session_id
 WHERE (c.summary IS NULL OR c.metadata = '{}'::jsonb OR c.ended_at IS NULL)
   AND COALESCE(a.last_activity, c.started_at)
       < NOW() - ($1::double precision * INTERVAL '1 hour')
 ORDER BY c.started_at
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
    for key in ("documents", "embeddings", "audit_rows"):
        arrow = "✓" if before[key] == after[key] else "✗ CHANGED"
        print(f"  {arrow:<10} {key:<12} {before[key]:>6} → {after[key]:>6}")

    if remaining:
        print("\nStill Romanian after the migration:", file=sys.stderr)
        for item in remaining:
            print(f"  · {item}", file=sys.stderr)
        return 1

    print("\nRenamed. Next: uv run python -m content_studio.db.apply")
    return 0


async def backfill(engine, apply: bool, idle_hours: float) -> int:
    async with engine.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        candidates = await raw.fetch(BACKFILL_CANDIDATES, idle_hours)

    print(f"Historical conversations to complete: {len(candidates)}")
    if not apply:
        for row in candidates:
            print(f"  · {row['session_id']}  last activity: {row['last_activity']}")
        print("\nNothing was written. Add --apply to complete them.")
        return 0

    for row in candidates:
        await update_conversation(
            engine,
            row["session_id"],
            model=None,
            status="closed",
            close=True,
            closure_estimated=True,
            closure_reason="backfilled_from_audit",
            closed_at=row["last_activity"],
        )
        print(f"  ✓ {row['session_id']}")

    print(f"\nCompleted: {len(candidates)}. No OpenAI call was made.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rename_parser = sub.add_parser("rename", help="Romanian schema → English schema")
    rename_parser.add_argument("--apply", action="store_true", help="write to Neon")

    backfill_parser = sub.add_parser("backfill", help="complete old conversations from the audit")
    backfill_parser.add_argument("--apply", action="store_true", help="write to Neon")
    backfill_parser.add_argument(
        "--idle-hours",
        type=float,
        default=1.0,
        help="skip conversations newer than this (default: 1 hour)",
    )
    args = parser.parse_args()

    if args.command == "backfill" and args.idle_hours < 0:
        parser.error("--idle-hours must be at least 0")

    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(e, file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}")
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        if args.command == "rename":
            return await rename(engine, args.apply)
        return await backfill(engine, args.apply, args.idle_hours)
    except Exception as e:  # noqa: BLE001
        print(f"{args.command} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
