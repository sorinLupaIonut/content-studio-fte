"""Decision 5's criterion: a search returns ranked passages, each with its page.

    uv run python tests/checks/paid/search.py
    uv run python tests/checks/paid/search.py "cum spun nu fara vinovatie"
    uv run python tests/checks/paid/search.py --client elena-rusu

The question from the plan is „vinovăția de a spune nu". What matters is not only
that passages come back, but that each one knows which book, chapter and page it
came from — otherwise it cannot be cited in the post's `source` field, which output
rule 8 requires.
"""

from __future__ import annotations

import asyncio
import os
import sys

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import CLIENT_SLUG, EMBEDDING_MODEL, database_url
from content_studio.db.import_books import as_vector

enable_utf8_output()

QUESTION = "vinovăția de a spune nu"

SQL = """
SELECT d.title,
       d.metadata->>'author'   AS author,
       e.metadata->>'page'     AS page,
       e.metadata->>'chapter'  AS chapter,
       e.chunk_text,
       1 - (e.embedding <=> $1::vector) AS score
  FROM public.embeddings e
  JOIN public.documents  d ON d.id = e.document_id
  JOIN public.clients    c ON c.id = d.client_id
 WHERE d.source = 'library'
   AND c.slug = $2
 ORDER BY e.embedding <=> $1::vector
 LIMIT 8
"""


async def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing.", file=sys.stderr)
        return 1

    # ONE SHELF AT A TIME, since `db.share_books` exists. Unscoped, this query
    # returns the same passage once per client holding a copy: four identical
    # hits, reading as four sources.
    argv = sys.argv[1:]
    client = CLIENT_SLUG
    if "--client" in argv:
        at = argv.index("--client")
        client = argv[at + 1]
        del argv[at : at + 2]
    question = argv[0] if argv else QUESTION
    response = await AsyncOpenAI().embeddings.create(model=EMBEDDING_MODEL, input=[question])
    vector = as_vector(response.data[0].embedding)

    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            rows = await conn.fetch(SQL, vector, client)
    finally:
        await engine.dispose()

    if not rows:
        print(f"Nothing on the {client!r} shelf. Fill one with:  "
              "db.import_books for your own books, db.share_books for a copy.")
        return 1

    print(f"„{question}”  ·  shelf: {client}\n")
    without_marker = 0
    for i, r in enumerate(rows, 1):
        # The page beats the chapter. Chapter titles from PDF-extracted books often
        # arrive cut across two lines („## GRANIȚELE" / „## UNUI SUFLET"), so they
        # are only trustworthy where there is no page number.
        if r["page"]:
            marker = f"page {r['page']}"
        elif r["chapter"]:
            marker = f"chapter „{r['chapter']}”"
        else:
            marker = "no marker"
        without_marker += not (r["page"] or r["chapter"])
        author = f" — {r['author']}" if r["author"] else ""
        print(f"{i}. [{r['score']:.3f}]  {r['title']}{author}")
        print(f"   {marker}")
        print(f"   {r['chunk_text'][:220].strip()}…\n")

    print(f"{len(rows)} passages, ranked by similarity. With no marker at all: {without_marker}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
