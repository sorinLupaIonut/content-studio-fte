"""The 17 books → `documents` + `embeddings`. Decision 5.

    uv run python -m content_studio.db.import_books
    uv run python -m content_studio.db.import_books --rewrite   (redo everything, ignore sha256)

**The unit of work is the book, not the library.** Every book keeps the `sha256`
of its file in `documents.metadata`. Each run compares them: unchanged → skipped;
new or modified → only that one is chunked and embedded. Add an eighteenth book,
run again, and only its chunks travel to OpenAI. The HNSW index takes new rows
without a rebuild.

The one thing that would force a full redo: changing the embedding model. Vectors
from two models are not comparable, and search would return garbage without
complaining — architecture rule 3. That is why every row carries its model in
`embeddings.model`: you can ask the database which rows are stale.

**Chunks know where they came from.** 16 of the 17 books carry `<!-- pagina N -->`
markers, added when the text was extracted from the PDF. The splitter walks the
text remembering the last page and the last heading, and every chunk leaves with
both in `embeddings.metadata`. Without that, search would return good text with no
way to say where it is from — and output rule 8 asks for exactly
`„Title" — Author, chapter N / page N` in the post's `source` field.
`cand-corpul-spune-nu.md` has no markers: there only the chapter survives, and the
document is flagged with `has_page_markers: false`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import (
    CONTENT_DIR,
    EMBEDDING_MODEL,
    MissingConfig,
    database_url,
    describe_database,
)

enable_utf8_output()

BOOKS_DIR = CONTENT_DIR / "books" / "md"

#: Characters per chunk. Below 800 you lose the sentence's context; above ~2000 a
#: good passage drowns in its neighbours and the similarity score flattens out.
CHUNK_SIZE = 1200

#: Chunks per embedding request. 100 × 1200 characters ≈ 40k tokens.
BATCH = 100

PAGE_MARKER = re.compile(r"<!--\s*pagina\s+(\d+)\s*-->")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

FIND_SQL = (
    "SELECT id, metadata->>'sha256' AS sha FROM public.documents "
    "WHERE source='library' AND title=$1"
)
DELETE_SQL = "DELETE FROM public.documents WHERE source='library' AND title=$1"
DOCUMENT_SQL = """
INSERT INTO public.documents (source, title, body, metadata)
VALUES ('library', $1, $2, $3::jsonb) RETURNING id
"""
CHUNK_SQL = """
INSERT INTO public.embeddings (document_id, chunk_text, chunk_index, embedding, model, metadata)
VALUES ($1, $2, $3, $4::vector, $5, $6::jsonb)
"""


def title_and_author(text: str) -> tuple[str, str | None]:
    """From the first `# Title — Author`. The author is optional; some books lack one."""
    found = H1.search(text)
    if not found:
        return "(fără titlu)", None
    whole = found.group(1)
    for separator in (" — ", " – ", " - "):
        if separator in whole:
            title, author = whole.split(separator, 1)
            return title.strip(), author.strip()
    return whole.strip(), None


def without_header(text: str) -> str:
    """Drop the extraction notes that sit before the book's own content.

    Every file starts with `# Title` and a `> Sursa: …` quote describing how it
    was pulled out of the PDF. That is about the file, not from the book, and has
    no business inside a chunk. Only the leading quote is cut: a `>` in the middle
    of the book is real text and stays.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (
        not lines[i].strip() or lines[i].startswith(">") or lines[i].startswith("#")
    ):
        i += 1
    return "\n".join(lines[i:])


def split(text: str) -> Iterator[tuple[str, int | None, str | None]]:
    """Chunks of ~CHUNK_SIZE characters, each with its page and chapter.

    It walks paragraphs, not characters: a chunk cut mid-sentence embeds badly and
    reads even worse when the client sees it quoted back.
    """
    page: int | None = None
    chapter: str | None = None
    chunk: list[str] = []
    length = 0
    chunk_page: int | None = None
    chunk_chapter: str | None = None

    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        pages = PAGE_MARKER.findall(paragraph)
        if pages:
            page = int(pages[-1])
            paragraph = PAGE_MARKER.sub("", paragraph).strip()
            if not paragraph:
                continue

        heading = HEADING.match(paragraph)
        if heading:
            chapter = heading.group(1).strip("* ")

        if not chunk:
            chunk_page, chunk_chapter = page, chapter

        chunk.append(paragraph)
        length += len(paragraph)

        if length >= CHUNK_SIZE:
            yield "\n\n".join(chunk), chunk_page, chunk_chapter
            chunk, length = [], 0

    if chunk:
        yield "\n\n".join(chunk), chunk_page, chunk_chapter


async def embed(client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
    response = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in response.data]


def as_vector(values: list[float]) -> str:
    """asyncpg does not know the `vector` type; its text form works with `::vector`."""
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


async def import_book(conn, client: AsyncOpenAI, path: Path, rewrite: bool) -> tuple[str, int]:
    """Return (what happened, how many chunks)."""
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    title, author = title_and_author(text)

    existing = await conn.fetchrow(FIND_SQL, title)
    if existing and existing["sha"] == sha and not rewrite:
        return "unchanged", 0

    body = without_header(text)
    chunks = list(split(body))
    if not chunks:
        return "empty, skipped", 0

    if existing:
        await conn.execute(DELETE_SQL, title)

    metadata = {
        "sha256": sha,
        "file": path.name,
        "author": author,
        "authority_class": "context de lucru — inspirație",
        "version": "ediție neînregistrată",
        "rank": 3,
        "has_page_markers": bool(PAGE_MARKER.search(text)),
        "is_summary": "rezumat" in path.stem,
        "rights_basis": "copie personală, uz privat",
        "owner": "viorela",
    }
    doc_id = await conn.fetchval(
        DOCUMENT_SQL, title, body, json.dumps(metadata, ensure_ascii=False)
    )

    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        vectors = await embed(client, [t for t, _, _ in batch])
        await conn.executemany(
            CHUNK_SQL,
            [
                (
                    doc_id,
                    chunk_text,
                    start + i,
                    as_vector(vector),
                    EMBEDDING_MODEL,
                    json.dumps({"page": page, "chapter": chapter}, ensure_ascii=False),
                )
                for i, ((chunk_text, page, chapter), vector) in enumerate(
                    zip(batch, vectors, strict=True)
                )
            ],
        )

    return ("rewritten" if existing else "imported"), len(chunks)


async def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing.", file=sys.stderr)
        return 1

    if not BOOKS_DIR.is_dir():
        print(f"No books folder at: {BOOKS_DIR}", file=sys.stderr)
        return 1

    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    rewrite = "--rewrite" in sys.argv
    files = sorted(f for f in BOOKS_DIR.glob("*.md") if f.name != "README.md")

    print(f"Database: {describe_database(url)}")
    print(f"Books   : {len(files)} files · model {EMBEDDING_MODEL}")
    if rewrite:
        print("Mode    : --rewrite, sha256 ignored\n")
    else:
        print()

    client = AsyncOpenAI()
    engine = create_async_engine(url, connect_args=connect_args)
    total = 0

    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection
            for path in files:
                what, count = await import_book(conn, client, path, rewrite)
                total += count
                mark = "·" if count == 0 else "✓"
                print(f"  {mark} {path.name:<48} {what:<12} {count or '':>5}")
    except Exception as e:  # noqa: BLE001
        print(f"\nThe import failed:\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"\n{total} new chunks in `embeddings`.")
    print("Check it with:  uv run python tests/checks/search.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
