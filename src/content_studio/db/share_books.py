"""Copy one client's library onto another's shelf. A decision, taken by hand.

    uv run python -m content_studio.db.share_books --list
    uv run python -m content_studio.db.share_books --to sorin --to elena-rusu
    uv run python -m content_studio.db.share_books --to dan-preda --rewrite

A NEW ACCOUNT STARTS WITH AN EMPTY LIBRARY ON PURPOSE. The books are licensed
material, so putting them on somebody else's shelf is a decision the owner makes
out loud, from a terminal — which is exactly why this is a named command and not
a checkbox on the admin page. `--to` is required and takes a slug: there is no
`--everyone`.

**The vectors are copied, never recomputed.** Same text, same model, same
numbers — re-embedding every chunk per tester would spend money to arrive at the
identical answer, and the copy happens inside Postgres, so no vector crosses the
wire. The corollary is architecture rule 3: if the source rows were ever written
by a different embedding model, the copy inherits it faithfully, which is what
you want — `embeddings.model` still tells you which rows are stale.

**The unit of work is the book**, as in `import_books`: a title the target
already holds with the same `sha256` is left alone, so running this twice is free
and running it after a new book arrives copies only that book. `--rewrite` drops
the target's copy and takes it again.

Provenance travels with the copy. `metadata.owner` keeps saying whose the books
are — they are on loan — and `shared_from` records which shelf this row was taken
off, so a copy is never mistaken for an original.

WHICH ENDPOINT: business data, so the pooled one, like the app and like
`db.provision`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import (
    CLIENT_SLUG,
    MissingConfig,
    database_url,
    describe_database,
)

enable_utf8_output()

SHELVES_SQL = """
SELECT c.slug                                      AS slug,
       COUNT(DISTINCT d.id)                        AS books,
       COUNT(e.id)                                 AS chunks,
       COUNT(DISTINCT d.metadata->>'shared_from')  AS lenders
  FROM public.clients c
  LEFT JOIN public.documents  d ON d.client_id = c.id AND d.source = 'library'
  LEFT JOIN public.embeddings e ON e.document_id = d.id
 GROUP BY c.slug
 ORDER BY c.slug
"""

CLIENT_SQL = "SELECT id FROM public.clients WHERE slug = $1"

SOURCE_SQL = """
SELECT d.id     AS id,
       d.title  AS title,
       d.metadata->>'sha256' AS sha,
       (SELECT COUNT(*) FROM public.embeddings e WHERE e.document_id = d.id) AS chunks
  FROM public.documents d
  JOIN public.clients  c ON c.id = d.client_id
 WHERE c.slug = $1 AND d.source = 'library'
 ORDER BY d.title
"""

# Scoped by client on both sides. An unscoped `WHERE title = $1` would reach
# across shelves — and after this command has run, there is more than one shelf.
EXISTING_SQL = """
SELECT id, metadata->>'sha256' AS sha
  FROM public.documents
 WHERE client_id = $1 AND source = 'library' AND title = $2
"""
DROP_SQL = """
DELETE FROM public.documents
 WHERE client_id = $1 AND source = 'library' AND title = $2
"""

# `embeddings.document_id` is ON DELETE CASCADE, so dropping the document takes
# its chunks with it; there is no second DELETE to forget.
COPY_DOCUMENT_SQL = """
INSERT INTO public.documents (source, title, body, metadata, client_id)
SELECT d.source, d.title, d.body,
       d.metadata || jsonb_build_object('shared_from', $2::text),
       $3::uuid
  FROM public.documents d
 WHERE d.id = $1
RETURNING id
"""
COPY_CHUNKS_SQL = """
INSERT INTO public.embeddings (document_id, chunk_text, chunk_index, embedding, model, metadata)
SELECT $2::uuid, e.chunk_text, e.chunk_index, e.embedding, e.model, e.metadata
  FROM public.embeddings e
 WHERE e.document_id = $1
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--to",
        action="append",
        default=[],
        metavar="SLUG",
        help="client slug to copy onto; repeatable",
    )
    parser.add_argument(
        "--from",
        dest="source",
        default=CLIENT_SLUG,
        metavar="SLUG",
        help=f"whose library to copy (default: {CLIENT_SLUG})",
    )
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="replace the target's copy even when the sha256 matches",
    )
    parser.add_argument(
        "--list", action="store_true", help="print what is on each shelf and exit"
    )
    return parser


async def share_one(conn, book, source_slug: str, target_id, rewrite: bool) -> tuple[str, int]:
    """Return (what happened, how many chunks travelled)."""
    existing = await conn.fetchrow(EXISTING_SQL, target_id, book["title"])
    if existing and existing["sha"] == book["sha"] and not rewrite:
        return "already there", 0

    if existing:
        await conn.execute(DROP_SQL, target_id, book["title"])

    new_id = await conn.fetchval(COPY_DOCUMENT_SQL, book["id"], source_slug, target_id)
    await conn.execute(COPY_CHUNKS_SQL, book["id"], new_id)
    return ("replaced" if existing else "copied"), book["chunks"]


async def shelves(conn) -> int:
    print("\n  shelf         books   chunks  on loan")
    for row in await conn.fetch(SHELVES_SQL):
        lent = "own" if not row["lenders"] else "borrowed"
        print(f"  {row['slug']:<12} {row['books']:>6} {row['chunks']:>8}  {lent}")
    return 0


async def run(args: argparse.Namespace) -> int:
    if not args.list and not args.to:
        print(
            "Nothing to do: name at least one shelf with --to (or use --list).",
            file=sys.stderr,
        )
        return 1

    try:
        url, connect_args = database_url()
    except MissingConfig as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}")
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)

    try:
        # One transaction for the whole run: three shelves half-filled is a worse
        # state to debug than none.
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection

            if args.list:
                return await shelves(conn)

            books = await conn.fetch(SOURCE_SQL, args.source)
            if not books:
                print(f"There is no library under {args.source!r} to copy.", file=sys.stderr)
                return 1

            total = sum(b["chunks"] for b in books)
            print(f"Source  : {args.source} · {len(books)} books · {total} chunks")
            if args.rewrite:
                print("Mode    : --rewrite, sha256 ignored")

            for slug in args.to:
                target_id = await conn.fetchval(CLIENT_SQL, slug)
                if target_id is None:
                    print(
                        f"\nThere is no client {slug!r} in `clients`. Provision the "
                        "account first with `db.provision`. Nothing was written.",
                        file=sys.stderr,
                    )
                    return 1
                if slug == args.source:
                    print(f"\n  {slug}: that is the source shelf, skipped.")
                    continue

                print(f"\n  -> {slug}")
                moved = 0
                for book in books:
                    what, count = await share_one(conn, book, args.source, target_id, args.rewrite)
                    moved += count
                    mark = "·" if count == 0 else "✓"
                    print(f"    {mark} {book['title'][:44]:<46} {what:<14} {count or '':>5}")
                print(f"    {moved} chunks copied.")
    except Exception as exc:  # noqa: BLE001
        print(
            f"\nThe copy failed, nothing was written:\n  {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        await engine.dispose()

    print("\nCheck a shelf with:  uv run python -m content_studio.db.share_books --list")
    return 0


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
