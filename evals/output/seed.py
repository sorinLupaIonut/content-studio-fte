"""Freeze real generated variants into `cases.json`.

    uv run python evals/output/seed.py            # what it would freeze, free
    uv run python evals/output/seed.py --write    # writes cases.json

WHY THE CASES ARE FROZEN AND NOT READ LIVE. The two metrics have to be
comparable across a change: run them before a fix and after it, on the same
text, or the number moved because the sample did. Reading `generation_variants`
at judge time would make every run a different measurement wearing the same
name.

WHY THEY COME OUT OF THE DATABASE ANYWAY. The alternative is writing the bad
examples by hand, which grades an imitation of the fault. These are the actual
rows her wife was reading on 2026-09-01.

Re-seed when the sample stops being representative — a new format, a new model,
a fault the current ten do not contain. A re-seed makes numbers from before it
incomparable, so the file records when and from what it was taken.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import config, enable_utf8_output

enable_utf8_output()

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "cases.json"

#: Ready variants for one client, newest first, with the brief that produced
#: them. Read-only, and through this eval's own connection: the MCP boundary is
#: for the running worker's business data (architecture rule 1), not for an
#: offline grader reading its own evidence.
SQL = """
select v.id::text as id, c.slug, b.format, b.pillar, b.source, b.focus, b.model,
       i.title, i.angle, v.hook_type, v.hook, v.caption, v.created_at
  from public.generation_variants v
  join public.generation_ideas i on i.id = v.idea_id
  join public.generation_batches b on b.id = i.batch_id
  join public.clients c on c.id = b.client_id
 where v.status = 'ready'
   and v.caption is not null
   and c.slug = :slug
 order by v.created_at desc
 limit :limit
"""


def spread(rows: list[dict], want: int) -> list[dict]:
    """A sample that covers the hook types and formats, not just the newest ten.

    Newest-first alone returns one idea's five variants and calls that a sample:
    they share an angle, a format and a search, so five rows measure one run.
    """
    picked: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["format"], row["hook_type"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(row)
        if len(picked) >= want:
            return picked
    for row in rows:  # top up from whatever is left, still newest-first
        if row not in picked:
            picked.append(row)
        if len(picked) >= want:
            break
    return picked


async def collect(slug: str, want: int, pool: int) -> list[dict]:
    url, connect_args = config.database_url()
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text(SQL), {"slug": slug, "limit": pool})
        ).mappings().all()
    await engine.dispose()
    items = [dict(row) for row in rows]
    for item in items:
        item["created_at"] = item["created_at"].isoformat()
    return spread(items, want)


def main() -> int:
    parser = argparse.ArgumentParser(description="freeze real variants as cases")
    parser.add_argument("--slug", default=config.CLIENT_SLUG, help="whose output")
    parser.add_argument("--want", type=int, default=10, help="how many to freeze")
    parser.add_argument("--pool", type=int, default=200, help="how many to read")
    parser.add_argument("--write", action="store_true", help="write cases.json")
    parser.add_argument(
        "--tag",
        default="",
        help="label this set, so a before and an after live in one file",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="keep the variants already frozen and add these beside them",
    )
    args = parser.parse_args()

    variants = asyncio.run(collect(args.slug, args.want, args.pool))
    if not variants:
        print(f"No ready variant for {args.slug!r}.")
        return 1
    for item in variants:
        item["tag"] = args.tag

    kept: list[dict] = []
    if args.append and FROZEN.exists():
        existing = json.loads(FROZEN.read_text(encoding="utf-8"))["variants"]
        fresh = {item["id"] for item in variants}
        # An id already frozen keeps its ORIGINAL row and its original tag: the
        # whole point of a before/after in one file is that the "before" half
        # cannot be quietly relabelled by a later seed.
        kept = [item for item in existing if item["id"] not in fresh]
        print(f"keeping {len(kept)} already frozen\n")

    print(f"{len(variants)} variants for {args.slug!r}\n")
    print(f"{'format':<9} {'hook type':<11} {'model':<11} {'chars':>6}  hook")
    print("-" * 96)
    for item in variants:
        print(
            f"{item['format']:<9} {item['hook_type']:<11} {item['model'] or '?':<11} "
            f"{len(item['caption']):>6}  {item['hook'][:44]}"
        )

    if not args.write:
        print("\nNothing written. Pass --write to freeze these into cases.json.")
        return 0

    FROZEN.write_text(
        json.dumps(
            {
                "seeded_at": datetime.now(UTC).strftime("%Y-%m-%d-%H%M"),
                "client": args.slug,
                "note": (
                    "Real generated output, frozen so two runs of the same metric "
                    "measure the same text. Re-seeding makes earlier numbers "
                    "incomparable."
                ),
                "variants": kept + variants,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nFrozen into {FROZEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
