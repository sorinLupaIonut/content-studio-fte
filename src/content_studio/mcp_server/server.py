"""The `content-data` MCP server — the only door to the client's data. Decision 6.

    uv run content-studio-server
    uv run python -m content_studio.mcp_server.server

Five tools, no more:

    search_books    read   — meaning search across the 17 books
    search_web      read   — current angles, with the source links
    list_posts      read   — what has already been written
    save_post       write  — one post, plus its audit row
    update_profile  write  — one profile section, plus its audit row

There is no `run_sql`, no DDL, and no tool takes free text that SQL is built
from. Architecture rule 1: the worker never touches the database directly.

The two write tools insert their audit row in the SAME transaction as the write
(rule 2). Either both land or neither does — a post without a trail cannot happen
even if the connection dies between the two statements.

The approval gate is not inside the tool body: the worker puts it on the MCP
server registration. Writes are therefore interrupted before the call and resume
only after the client answers.

Tool names and result keys are English; every description below is Romanian,
because the model reads them and the model works in Romanian.

The transport is HTTP, so the server runs separately from the worker, in its own
terminal.
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import date

from mcp.server.mcpserver import Context, MCPServer
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import (
    CLIENT_SLUG,
    MCP_HOST,
    MCP_PORT,
    WEB_SEARCH_MODEL,
    MissingConfig,
    database_url,
    describe_database,
)

# The same model at write time and at search time — rule 3. It is imported from
# the script that wrote the vectors, so the two cannot drift apart without the
# import breaking too.
from content_studio.db.import_books import EMBEDDING_MODEL, as_vector
from content_studio.mcp_server.protocol import CONVERSATION_HEADER, PROFILE_URI

enable_utf8_output()

server = MCPServer(
    "content-data",
    instructions=(
        "Datele Viorelei: biblioteca ei de 17 cărți, postările deja scrise și "
        "profilul ei de brand."
    ),
)

# Built in `main()`, before the server starts listening.
_engine = None


@asynccontextmanager
async def connection():
    """A raw asyncpg connection, inside a transaction.

    Raw rather than through SQLAlchemy: `schema.sql` and the rest of the project
    speak SQL directly, and here `$1::vector` is needed, which the dialect does
    not help with at all. The engine stays for the pool and for URL normalization.
    """
    async with _engine.begin() as conn:
        yield (await conn.get_raw_connection()).driver_connection


PROFILE_SQL = "SELECT id, name, profile_md FROM clients WHERE slug = $1"


@server.resource(
    PROFILE_URI,
    name="profil-viorela",
    title="Profilul complet al Viorelei",
    description="Bootstrap intern pentru system prompt; nu este unealtă a agentului.",
    mime_type="application/json",
)
async def client_profile() -> str:
    """The live profile, read over MCP before the agent is built."""
    async with connection() as conn:
        row = await conn.fetchrow(PROFILE_SQL, CLIENT_SLUG)
    if row is None:
        raise ValueError(f"There is no client {CLIENT_SLUG!r} in the `clients` table.")
    return json.dumps(
        {"slug": CLIENT_SLUG, "name": row["name"], "profile_md": row["profile_md"]},
        ensure_ascii=False,
    )


SEARCH_SQL = """
SELECT d.title                                                  AS title,
       d.metadata->>'author'                                    AS author,
       COALESCE(d.metadata->>'authority_class',
                'context de lucru — inspirație')                AS authority_class,
       COALESCE(d.metadata->>'version',
                'ediție neînregistrată')                        AS version,
       COALESCE(d.metadata->>'is_summary', 'false')::bool       AS is_summary,
       COALESCE(d.metadata->>'has_page_markers',
                'false')::bool                                  AS has_page_markers,
       d.metadata->>'rights_basis'                              AS rights_basis,
       d.metadata->>'owner'                                     AS owner,
       e.metadata->>'page'                                      AS page,
       e.metadata->>'chapter'                                   AS chapter,
       e.chunk_text                                             AS text,
       e.model                                                  AS embedding_model,
       1 - (e.embedding <=> $1::vector)                         AS score
  FROM embeddings e
  JOIN documents  d ON d.id = e.document_id
 WHERE d.source = 'library'
   AND ($2::text[] IS NULL OR d.title = ANY($2::text[]))
 ORDER BY e.embedding <=> $1::vector
 LIMIT $3
"""


@server.tool()
async def search_books(
    description: str,
    titles: list[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    """Caută după înțeles în cele 17 cărți din biblioteca Viorelei.

    Folosește-o DOAR când ea a ales sursa „Cărți" sau „Combinat". Descrie ce
    cauți în cuvintele ei („vinovăția de a spune nu"), nu cu cuvinte-cheie, și
    pune descrierea în `description`.

    `titles` filtrează pe cărțile alese de ea, cu titlul exact; lipsă = toate.

    Fiecare pasaj vine cu proveniența lui: titlul, autorul, pagina sau capitolul,
    și dacă e rezumat. Pune-le pe câmpul `source` al postării — niciodată în hook,
    script sau caption. Un pasaj fără pagină NU primește un număr inventat: scrii
    titlul și autorul, atât.

    `score` e cât de aproape e pasajul de ce ai cerut, între 0 și 1. Pe corpusul
    ăsta, potrivirile bune stau pe la 0,45–0,55; sub 0,35 e mai degrabă zgomot.
    Pragul e doar un minim: verifică și dacă pasajul chiar tratează subiectul.
    O potrivire vagă despre brand nu e material despre fonturi sau Canva. Dacă
    nimic nu e relevant semantic, spune asta și nu întinde un pasaj slab.
    """
    limit = max(1, min(limit, 20))
    response = await AsyncOpenAI().embeddings.create(
        model=EMBEDDING_MODEL, input=[description]
    )
    vector = as_vector(response.data[0].embedding)

    async with connection() as conn:
        rows = await conn.fetch(SEARCH_SQL, vector, titles, limit)

    return [
        {
            "text": r["text"],
            "title": r["title"],
            "author": r["author"],
            "authority_class": r["authority_class"],
            "version": r["version"],
            # The page beats the chapter: chapter titles extracted from PDFs are
            # often cut across two lines, so they are only trustworthy where no
            # page number exists.
            "page": r["page"],
            "chapter": r["chapter"] if not r["page"] else None,
            "is_summary": r["is_summary"],
            "has_page_markers": r["has_page_markers"],
            "rights_basis": r["rights_basis"],
            "owner": r["owner"],
            "embedding_model": r["embedding_model"],
            "score": round(r["score"], 3),
        }
        for r in rows
    ]


def web_sources(response, limit: int) -> list[dict]:
    """Titles and URLs cited by the Responses API, without duplicates."""
    seen: set[str] = set()
    sources: list[dict] = []
    for item in response.output:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []):
            for annotation in getattr(content, "annotations", []):
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                url = getattr(annotation, "url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                sources.append(
                    {
                        "title": getattr(annotation, "title", "") or url,
                        "url": url,
                    }
                )
                if len(sources) >= limit:
                    return sources
    return sources


@server.tool()
async def search_web(
    description: str,
    limit: int = 5,
) -> dict:
    """Caută unghiuri actuale pe internet pentru tema aleasă de Viorela.

    Folosește-o DOAR când sursa aleasă este „Internet” sau „Combinat”. Rezultatul
    este inspirație: teme de sezon și lucruri discutate acum. Nu transforma
    cifrele, studiile sau citatele găsite pe web în fapte pentru postare.

    Pune subiectul în `description`. `sources` conține titlul și linkul paginilor
    citate. Ele merg numai în câmpul `source` la salvare, nu în hook, script sau
    caption.
    """
    query = description.strip()
    if not query:
        return {
            "status": "error",
            "message": "Lipsește descrierea temei pentru căutare.",
            "angles": "",
            "sources": [],
        }
    limit = max(1, min(limit, 8))
    prompt = f"""Caută pe web idei actuale pentru conținut social în limba română
pe tema: {query!r}.

Întoarce cel mult {limit} denumiri scurte de unghiuri, ca sintagme, fără să le
explici și fără să afirmi nimic despre cauze, efecte, simptome, prevenție sau
tratament. Exemple de formă: „limite după concediu”, „presiunea de a fi mereu
disponibilă”. Nu da procente, statistici, rezultate de studii, citate ori
afirmații medicale. Nu scrie o postare și nu da reguli; oferă numai subiecte de
explorat și citează paginile consultate."""
    response = await AsyncOpenAI().responses.create(
        model=WEB_SEARCH_MODEL,
        tools=[{"type": "web_search", "search_context_size": "low"}],
        input=prompt,
    )
    return {
        "status": "ok",
        "topic": query,
        "angles": response.output_text,
        "sources": web_sources(response, limit),
        "rule": (
            "Unghiurile spun numai despre ce poți vorbi. Nu afirma cauze, efecte, "
            "simptome, prevenție, diagnostice sau reguli. Nu prelua cifre, studii "
            "ori citate. Linkurile merg doar la sursa."
        ),
    }


LIST_POSTS_SQL = """
SELECT p.posted_on, p.title, p.pillar, p.format, p.hook, p.hook_type,
       p.source, p.status
  FROM posts   p
  JOIN clients c ON c.id = p.client_id
 WHERE c.slug = $1
   AND ($2::text IS NULL OR p.pillar ILIKE '%' || $2 || '%')
   AND ($3::text IS NULL OR p.format ILIKE '%' || $3 || '%')
   AND ($4::date IS NULL OR p.posted_on >= $4)
 ORDER BY p.posted_on DESC
 LIMIT $5
"""


@server.tool()
async def list_posts(
    pillar: str | None = None,
    format: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Postările deja scrise, cele mai noi întâi.

    Pentru „am mai scris despre asta?" și pentru „ce am dat luna asta".
    `pillar` și `format` caută pe bucată de text, nu pe potrivire exactă.
    `since` e o dată, în forma 2026-07-01.
    """
    limit = max(1, min(limit, 100))
    from_date = date.fromisoformat(since) if since else None

    async with connection() as conn:
        rows = await conn.fetch(
            LIST_POSTS_SQL, CLIENT_SLUG, pillar, format, from_date, limit
        )

    return [{**dict(r), "posted_on": r["posted_on"].isoformat()} for r in rows]


CLIENT_ID_SQL = "SELECT id FROM clients WHERE slug = $1"

INSERT_POST_SQL = """
INSERT INTO posts (client_id, conversation_id, posted_on, title, pillar, format,
                   hook, hook_type, script, caption, hashtags, cta, source,
                   status, body_md)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'draft', $14)
RETURNING id
"""

AUDIT_SQL = """
INSERT INTO audit_log (conversation_id, actor, action, target, payload, result)
VALUES ($1, 'worker:content-studio', $2, $3, $4::jsonb, $5::jsonb)
"""


def as_markdown(fields: dict) -> str:
    """The whole post as Markdown, for the `body_md` column.

    Built here from the fields rather than asked of the model: `body_md` has to be
    exactly what was saved in the columns, not a second version written separately.
    """
    return "\n".join(
        [
            f"# {fields['title']}",
            "",
            f"**Pilon:** {fields['pillar']} · **Format:** {fields['format']}",
            f"**Hook ({fields['hook_type']}):** {fields['hook']}",
            "",
            "## Script",
            fields["script"],
            "",
            "## Caption",
            fields["caption"],
            "",
            f"**Hashtaguri:** {fields['hashtags']}",
            f"**CTA:** {fields['cta']}",
            f"**Sursa:** {fields['source']}",
            "",
        ]
    )


def conversation_of(ctx: Context) -> str:
    """The id the worker put on the MCP connection, not one invented by the model."""
    request = ctx.request_context.request
    headers = getattr(request, "headers", None)
    conversation_id = headers.get(CONVERSATION_HEADER) if headers else None
    if not conversation_id:
        raise ValueError(
            f"Internal header {CONVERSATION_HEADER} is missing; the write was stopped."
        )
    return conversation_id


@server.tool()
async def save_post(
    title: str,
    pillar: str,
    format: str,
    hook: str,
    hook_type: str,
    script: str,
    caption: str,
    hashtags: str,
    cta: str,
    source: str,
    ctx: Context,
) -> dict:
    """Salvează postarea confirmată de Viorela. UNA singură, cea aleasă.

    Nu o chema până nu i-ai arătat postarea întreagă în chat și nu ți-a spus „da"
    (regula 10). Celelalte nouă propuneri nu se salvează.

    `source` e obligatoriu și spune adevărul: titlul și pagina cărții, linkul, sau
    „din memorie 🧠 (profil + avatar), fără sursă externă".
    `hook_type` e unul din PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE, CONTRAST.
    `hashtags` e un singur șir, cu spații între ele: „#burnout #limite".
    """
    conversation_id = conversation_of(ctx)
    fields = {
        "title": title,
        "pillar": pillar,
        "format": format,
        "hook": hook,
        "hook_type": hook_type,
        "script": script,
        "caption": caption,
        "hashtags": hashtags,
        "cta": cta,
        "source": source,
    }

    async with connection() as conn:
        client_id = await conn.fetchval(CLIENT_ID_SQL, CLIENT_SLUG)
        if client_id is None:
            raise ValueError(f"There is no client {CLIENT_SLUG!r} in the `clients` table.")

        post_id = await conn.fetchval(
            INSERT_POST_SQL,
            client_id,
            conversation_id,
            date.today(),
            title,
            pillar,
            format,
            hook,
            hook_type,
            script,
            caption,
            hashtags,
            cta,
            source,
            as_markdown(fields),
        )
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            "post_saved",
            "posts",
            json.dumps(fields, ensure_ascii=False),
            json.dumps({"id": str(post_id)}, ensure_ascii=False),
        )

    return {"id": str(post_id), "title": title, "posted_on": date.today().isoformat()}


WRITE_PROFILE_SQL = """
UPDATE clients SET profile_md = $2, updated_at = NOW() WHERE id = $1
"""


def replace_section(profile: str, section: str, new_text: str) -> str:
    """Replace the body of a `## …` section, leaving the rest of the profile alone.

    The section heading keeps whatever the profile says, not what the model wrote —
    otherwise a difference in diacritics or an emoji would rewrite the heading.
    """
    # Horizontal whitespace only around the heading. `\s` would swallow the blank
    # lines after it and then add extra spacing on rewrite.
    headings = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", profile, re.MULTILINE))
    wanted = section.strip().lower()

    for i, heading in enumerate(headings):
        if wanted not in heading.group(1).lower():
            continue
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(profile)
        return profile[:start] + "\n\n" + new_text.strip() + "\n\n" + profile[end:]

    existing = "\n".join(f"  · {h.group(1)}" for h in headings)
    raise ValueError(
        f"Nu există o secțiune care să conțină {section!r} în profil.\n"
        f"Secțiunile de azi sunt:\n{existing}"
    )


@server.tool()
async def update_profile(section: str, new_text: str, ctx: Context) -> dict:
    """Rescrie o secțiune din profilul Viorelei. Doar la cererea ei explicită.

    `section` e o bucată din titlul secțiunii, așa cum apare în profil („Oferte",
    „CTA"). `new_text` e corpul întreg al secțiunii, fără linia de titlu — ce
    trimiți înlocuiește tot ce era acolo, deci scrie-l complet, nu doar adaosul.

    Ce era înainte rămâne în `audit_log`, deci o greșeală se poate întoarce.
    """
    conversation_id = conversation_of(ctx)
    async with connection() as conn:
        row = await conn.fetchrow(PROFILE_SQL, CLIENT_SLUG)
        if row is None:
            raise ValueError(f"There is no client {CLIENT_SLUG!r} in the `clients` table.")

        new_profile = replace_section(row["profile_md"], section, new_text)
        await conn.execute(WRITE_PROFILE_SQL, row["id"], new_profile)
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            "profile_updated",
            "clients",
            json.dumps(
                {"section": section, "previous_text": row["profile_md"]},
                ensure_ascii=False,
            ),
            json.dumps({"characters": len(new_profile)}, ensure_ascii=False),
        )

    return {
        "section": section,
        "profile_was": len(row["profile_md"]),
        "profile_is": len(new_profile),
    }


def main() -> int:
    global _engine

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing. Search does not work without it.", file=sys.stderr)
        return 1

    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    # `pool_pre_ping`: Neon suspends the compute after a few minutes without
    # traffic and closes the connections. Without the ping, the pool hands out a
    # dead connection and the first tool called after a pause fails with
    # `InterfaceError: connection is closed` — on her second question, not her
    # first. The ping costs one `SELECT 1` per checkout; this server makes a
    # network call per tool anyway.
    _engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)

    print(f"content-data · five tools · http://{MCP_HOST}:{MCP_PORT}/mcp")
    print(f"Database: {describe_database(url)}")
    print("Leave it running and open the worker in another terminal.\n")

    # stateless: every request is complete in itself, with no session kept between
    # them. The worker is a single process on the same machine — there is nothing
    # to gain from session state, and something to lose if it desynchronizes.
    server.run("streamable-http", host=MCP_HOST, port=MCP_PORT, stateless_http=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
