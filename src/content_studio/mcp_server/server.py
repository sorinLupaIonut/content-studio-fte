"""The `content-data` MCP server — the only door to the client's data. Decision 6.

    uv run content-studio-server
    uv run python -m content_studio.mcp_server.server

Ten model-visible tools:

    search_books      read     — meaning search across the 17 books
    search_web        read     — meaning search across the live web
    list_posts        read     — what has already been written
    save_post         write    — one post, plus its audit row
    save_posts_batch  write    — the chosen variants of one UI batch, all or none
    update_post       write    — one studio-written post, replaced whole
    update_profile    write    — one profile section, plus its audit row
    start_generation  trigger  — record a validated batch request; the harness runs it
    develop_idea      trigger  — record which idea to develop; the harness runs it
    select_variant    choice   — mark her chosen variant on the current batch

The trigger tools (2026-08-27) close the chat↔UI loop: the conversation agent
never writes her content itself — it records what she asked for, and the
harness executes the same pipeline the interface buttons use. Ungated, because
they create drafts; the one confirmation stays on saving a post (rule 6).

Internal D1b draft operations share this server but are hidden from the agent by
the SDK tool filter. There is no `run_sql`, no DDL, and no tool takes free text
that SQL is built from. Architecture rule 1: the worker never touches the
database directly.

Every write tool inserts its audit row in the SAME transaction as the write
(rule 2). Either both land or neither does — a post without a trail cannot happen
even if the connection dies between the two statements. `save_posts_batch` widens
that promise to a whole batch: ten posts and ten trail rows commit together.

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
from uuid import UUID

from mcp.server.mcpserver import Context, MCPServer
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output

# The event vocabulary is shared rather than spelled out here: since D4 the
# `event` column is free text, so a typo on this side would simply produce a row
# `replay.py` cannot group. One import keeps both ends honest.
from content_studio.audit import (
    ACCOUNT_PROVISIONED,
    CONVERSATION_STARTED,
    GENERATION_BATCH_CREATED,
    GENERATION_BATCH_FAILED,
    GENERATION_CANCELLED,
    GENERATION_IDEA_FAILED,
    GENERATION_IDEA_READY,
    GENERATION_IDEA_STARTED,
    GENERATION_REQUESTED,
    GENERATION_TITLES_READY,
    GENERATION_VARIANT_PATCHED,
    GENERATION_VARIANT_SELECTED,
    IDEA_DEVELOPMENT_REQUESTED,
    POST_SAVED,
    POST_UPDATED,
    PROFILE_UPDATED,
    event_name,
)
from content_studio.config import (
    CLIENT_SLUG,
    MCP_HOST,
    MCP_PORT,
    WEB_SEARCH_MODEL,
    MissingConfig,
    database_url,
    describe_database,
)
from content_studio.db.import_books import EMBEDDING_MODEL, as_vector

# The same model at write time and at search time — rule 3. It is imported from
# the script that wrote the vectors, so the two cannot drift apart without the
# import breaking too.
from content_studio.debug import attach_if_requested
from content_studio.harness.generation import (
    HOOK_TYPES,
    FormatChoice,
    GenerationBatchRequest,
    IdeaDetails,
    IdeaTitles,
    IdeaVariant,
    PillarChoice,
    SourceChoice,
)
from content_studio.harness.posts import SavedPostContent, SavePostsRequest
from content_studio.mcp_server.accounts import (
    list_accounts,
    provision_self,
    resolve_account,
    set_disabled,
)
from content_studio.mcp_server.conversation_store import (
    bind_conversation_batch,
    current_conversation,
    new_conversation,
)
from content_studio.mcp_server.generation_store import (
    cancel_batch,
    complete_idea,
    create_batch,
    fail_batch,
    fail_idea,
    list_library,
    load_batch,
    load_current_batch,
    patch_variant,
    put_titles,
    start_idea,
)
from content_studio.mcp_server.generation_store import (
    # Aliased because `select_variant` is now also the model-visible tool's
    # name; the store primitive keeps its own.
    select_variant as select_variant_store,
)
from content_studio.mcp_server.posts_store import (
    as_markdown,
    list_saved_posts,
    load_saved_post,
    save_selected_variants,
    update_saved_post,
)
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    INTERNAL_UI_TOOLS,
    MODEL_VISIBLE_TOOLS,
    OWNER_HEADER,
    profile_uri,
)
from content_studio.mcp_server.usage_store import (
    all_usage,
    load_budget,
    record_usage,
    set_budget,
)
from content_studio.pricing import cost_micros as price_of

enable_utf8_output()

server = MCPServer(
    "content-data",
    instructions=(
        "Viorela's data: her library of 17 books, the posts already written, "
        "and her brand profile."
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


# Every statement names its schema. The app talks to Neon's pooled endpoint,
# which is PgBouncer in transaction mode and makes no promise about `search_path`
# holding from one transaction to the next (D4).
PROFILE_SQL = "SELECT id, name, profile_md FROM public.clients WHERE slug = $1"


# A template, not one fixed URI: the slug is part of the address. Reading the
# old concrete URI still matches it and still yields Viorela, so the CLI and the
# existing tests are unaffected.
@server.resource(
    profile_uri("{slug}"),
    name="profil-client",
    title="Profilul complet al clientei",
    description="Internal bootstrap for the system prompt; not an agent tool.",
    mime_type="application/json",
)
async def client_profile(slug: str) -> str:
    """The live profile, read over MCP before the agent is built."""
    async with connection() as conn:
        row = await conn.fetchrow(PROFILE_SQL, slug)
    if row is None:
        raise ValueError(f"There is no client {slug!r} in the `clients` table.")
    return json.dumps(
        {"slug": slug, "name": row["name"], "profile_md": row["profile_md"]},
        ensure_ascii=False,
    )


SEARCH_SQL = """
SELECT e.id                                                     AS chunk_id,
       d.title                                                  AS title,
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
  FROM public.embeddings e
  JOIN public.documents  d ON d.id = e.document_id
  JOIN public.clients    c ON c.id = d.client_id
 WHERE d.source = 'library'
   AND c.slug = $4
   AND ($2::text[] IS NULL OR d.title = ANY($2::text[]))
 ORDER BY e.embedding <=> $1::vector
 LIMIT $3
"""


@server.tool()
async def search_books(
    ctx: Context,
    description: str,
    description_en: str,
    titles: list[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    """Search the client's library by meaning.

    `description` is what you are looking for, as a sentence in Romanian.
    `description_en` is the same search phrased by you in English: the shelf is
    bilingual, and an English book stays nearly invisible to a Romanian phrasing
    without it. The search runs with both and keeps, for each passage, the better
    match of the two.

    `titles` narrows the search to particular books, by exact title; absent means
    the whole shelf. `limit` is how many passages you want, between 1 and 20.

    Every passage arrives with its text and with its provenance: the title, the
    author, the page or the chapter. `score` says how close the passage is to what
    you asked for, between 0 and 1.
    """
    limit = max(1, min(limit, 20))
    # The client rides the connection, like every other tool here. The books are
    # licensed material belonging to whoever imported them, and an unscoped
    # search would let one account's agent quote from another's shelf.
    client_slug = await client_of(ctx)
    # Both phrasings in one embeddings round-trip. The shelf is bilingual and
    # the embedding model is not: measured on 2026-08-26, a Romanian phrasing
    # left all three English burnout books unreached while its English twin
    # found them at 0.60. Two ANN queries, merged on the fragment, best score
    # wins — the schema makes the second phrasing mandatory, so the guarantee
    # does not depend on the model remembering a rule.
    response = await AsyncOpenAI().embeddings.create(
        model=EMBEDDING_MODEL, input=[description, description_en]
    )
    vectors = [as_vector(d.embedding) for d in response.data]

    async with connection() as conn:
        merged: dict[object, object] = {}
        for vector in vectors:
            for r in await conn.fetch(SEARCH_SQL, vector, titles, limit, client_slug):
                key = r["chunk_id"]
                if key not in merged or r["score"] > merged[key]["score"]:
                    merged[key] = r
    rows = sorted(merged.values(), key=lambda r: r["score"], reverse=True)[:limit]

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


class WebFinding(BaseModel):
    """One page read by the search, in the same shape a book passage arrives in."""

    text: str
    title: str
    url: str
    site: str
    published: str


class WebFindings(BaseModel):
    items: list[WebFinding]


async def meter_web_search(ctx: Context, response) -> None:
    """Put this call on the client's meter. Best effort, never fatal.

    THE ONE MODEL CALL THE BUDGET COULD NOT SEE. Every other call in the studio
    is made by the harness, which reads the usage off a `RunHooks` and records it
    through `ui_record_usage`. This one is made here, inside the MCP server, with
    its own `AsyncOpenAI` — so nothing was watching, and a source of `Internet`
    or `Combinat` spent money the gate never counted. `schema.sql` has listed
    `web_search` among the kinds since the table was written; this is the row it
    was waiting for.

    What is metered is the TOKENS. The `web_search` tool has a per-call charge of
    its own that the Responses API does not report in `usage`, so the row is an
    undercount by that fixed amount - smaller than the gap it closes, and honest
    about which part it knows.
    """

    usage = getattr(response, "usage", None)
    if usage is None:
        return
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    if not input_tokens and not output_tokens:
        return
    # Same defensive read as `accounts.py`: a provider that reports no detail
    # leaves this zero, which charges the full rate rather than inventing a
    # discount.
    details = getattr(usage, "input_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0)
    try:
        client_slug = await client_of(ctx)
        async with connection() as conn:
            await record_usage(
                conn,
                client_slug=client_slug,
                principal_id=_header(ctx, OWNER_HEADER) or "unknown",
                kind="web_search",
                model=WEB_SEARCH_MODEL,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached,
                cost_micros=price_of(
                    WEB_SEARCH_MODEL, input_tokens, output_tokens, cached
                ),
            )
    except Exception:  # noqa: BLE001
        # The search already succeeded and its material is on its way to the
        # model. Losing the meter row is bad; turning a delivered answer into a
        # tool error because of the meter is worse.
        return


@server.tool()
async def search_web(
    ctx: Context,
    description: str,
    limit: int = 5,
) -> list[dict]:
    """Search the internet for current material, by meaning.

    `description` is what you are looking for, as a sentence in Romanian. `limit`
    is how many fragments you want, between 1 and 8.

    Every fragment arrives with its text, taken from the page as it was read, and
    with its provenance: the page title, its link, the publication and the date,
    when the page shows one.
    """
    query = description.strip()
    if not query:
        return []
    limit = max(1, min(limit, 8))
    prompt = f"""Search the web for material on: {query!r}.

Return at most {limit} fragments, each from a page you actually read. `text` is
a short passage from the page, in the page's own words, not a summary of yours.
`title` is the page's title, `url` its link, `site` the publication, and
`published` the publication date if the page shows one, otherwise an empty
string."""
    response = await AsyncOpenAI().responses.parse(
        model=WEB_SEARCH_MODEL,
        tools=[{"type": "web_search", "search_context_size": "low"}],
        input=prompt,
        text_format=WebFindings,
    )
    await meter_web_search(ctx, response)
    findings = response.output_parsed
    if findings is None:
        return []
    return [f.model_dump() for f in findings.items[:limit]]


LIST_POSTS_SQL = """
SELECT p.posted_on, p.title, p.pillar, p.format, p.hook, p.hook_type,
       p.source, p.status
  FROM public.posts   p
  JOIN public.clients c ON c.id = p.client_id
 WHERE c.slug = $1
   AND ($2::text IS NULL OR p.pillar ILIKE '%' || $2 || '%')
   AND ($3::text IS NULL OR p.format ILIKE '%' || $3 || '%')
   AND ($4::date IS NULL OR p.posted_on >= $4)
 ORDER BY p.posted_on DESC
 LIMIT $5
"""


@server.tool()
async def list_posts(
    ctx: Context,
    pillar: str | None = None,
    format: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """The posts already written, newest first.

    For „am mai scris despre asta?" and for „ce am dat luna asta".
    `pillar` and `format` match on a piece of text, not on an exact match.
    `since` is a date, in the form 2026-07-01.
    """
    limit = max(1, min(limit, 100))
    from_date = date.fromisoformat(since) if since else None

    client_slug = await client_of(ctx)
    async with connection() as conn:
        rows = await conn.fetch(
            LIST_POSTS_SQL, client_slug, pillar, format, from_date, limit
        )

    return [{**dict(r), "posted_on": r["posted_on"].isoformat()} for r in rows]


CLIENT_ID_SQL = "SELECT id FROM public.clients WHERE slug = $1"

INSERT_POST_SQL = """
INSERT INTO public.posts (client_id, conversation_id, posted_on, title, pillar,
                          format, hook, hook_type, script, caption, hashtags,
                          cta, source, status, body_md)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'draft', $14)
RETURNING id
"""

# Rule 2, second half: the trail is written in the SAME transaction as the write
# it describes, so a saved post without its audit row cannot exist.
#
# Since D4 the trail hangs off a run rather than a conversation, and this server
# only ever learns the session_id — it comes in on the connection header, set by
# the worker. So the run is looked up here, in the same statement: the newest run
# of that session. The worker opens exactly one run per turn and waits for it, so
# "newest" is "the one that called this tool". If no run exists yet, `run_id`
# lands NULL, which the column allows: a trail row with no run beats none at all.
AUDIT_SQL = """
INSERT INTO public.audit_log (run_id, event)
VALUES (
    (SELECT id FROM public.runs
      WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1),
    $2
)
"""


def _header(ctx: Context, name: str) -> str | None:
    request = ctx.request_context.request
    headers = getattr(request, "headers", None)
    return headers.get(name) if headers else None


def conversation_of(ctx: Context) -> str:
    """The id the worker put on the MCP connection, not one invented by the model."""
    conversation_id = _header(ctx, CONVERSATION_HEADER)
    if not conversation_id:
        raise ValueError(
            f"Internal header {CONVERSATION_HEADER} is missing; the write was stopped."
        )
    return conversation_id


def owner_of(ctx: Context) -> str:
    """The signed-in identity, taken from the connection rather than the model.

    Only the studio UI sets it. The CLI has no generation batches to save from,
    so a missing header is not a failure of configuration — it is the honest
    answer that this tool does not apply there.
    """
    owner = _header(ctx, OWNER_HEADER)
    if not owner:
        raise ValueError(
            "The tool is available only from the Studio interface, where the "
            "identity is verified. From a terminal, use `save_post`."
        )
    return owner


async def client_of(ctx: Context) -> str:
    """Whose data this connection may see. Three sources, most trusted first.

    1. `CLIENT_HEADER`, when the caller already knows. The harness resolves the
       account once per request and puts the answer here, so the common path
       costs no query at all.
    2. The principal on the connection, looked up in `app_users`. This is the
       path for a connection that carries an identity but was not told the
       client.
    3. `CLIENT_SLUG`. The CLI sets neither header, and an unprovisioned
       principal has no account - both land on the configured default, which is
       exactly the behaviour that existed before this function did.

    Never a tool argument, in any of the three. `save_post` is model-visible, and
    a client the model can name is a client the model can get wrong.
    """
    slug = _header(ctx, CLIENT_HEADER)
    if slug:
        return slug

    principal_id = _header(ctx, OWNER_HEADER)
    if principal_id:
        # Its own short transaction, before the caller opens the one that does
        # the work. Only reached when the header above is absent.
        async with connection() as conn:
            account = await resolve_account(conn, principal_id)
        if account is not None:
            return account.client_slug

    return CLIENT_SLUG


@server.tool()
async def save_post(
    title: str,
    pillar: str,
    format: str,
    hook: str,
    hook_type: str,
    caption: str,
    hashtags: str,
    cta: str,
    source: str,
    ctx: Context,
    # Last, and optional, because a Reel does not have one: she films mute, and
    # the caption carries what she would have said. `ctx` stays ahead of it
    # only because a parameter with a default cannot precede one without.
    script: str | None = None,
) -> dict:
    """Save the post Viorela confirmed. ONE only, the one she chose.

    Do not call it until you have shown her the whole post in the chat and she has
    said „da" (rule 10). The other nine proposals are not saved.

    `source` is required and tells the truth: the book's title and page, the link,
    or „din memorie 🧠 (profil + avatar), fără sursă externă".
    `hook_type` is one of PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE, CONTRAST.
    `hashtags` is a single string, with spaces between them: „#burnout #limite".
    `script` is filled in for Carusel and Stories only. Her Reels are silent:
    there you leave `script` empty, and everything that would have been said sits
    in `caption`.
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

    client_slug = await client_of(ctx)
    async with connection() as conn:
        client_id = await conn.fetchval(CLIENT_ID_SQL, client_slug)
        if client_id is None:
            raise ValueError(f"There is no client {client_slug!r} in the `clients` table.")

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
        await conn.execute(AUDIT_SQL, conversation_id, event_name(POST_SAVED, title))

    return {"id": str(post_id), "title": title, "posted_on": date.today().isoformat()}


@server.tool()
async def save_posts_batch(variant_ids: list[str], ctx: Context) -> dict:
    """Save for good the posts Viorela chose in the interface.

    You call it once, with exactly the list of `variant_ids` the application gave
    you, in the same order. Do not invent ids, do not add or remove any, and do
    not rewrite the content: the text saved is exactly the variant she read and
    chose.

    All of them save, or none does. A variant that is not marked as chosen, is not
    ready, or is not from her account's batch stops the whole batch.
    """
    conversation_id = conversation_of(ctx)
    owner_principal_id = owner_of(ctx)
    request = SavePostsRequest.model_validate({"variant_ids": variant_ids})

    client_slug = await client_of(ctx)
    async with connection() as conn:
        saved = await save_selected_variants(
            conn,
            client_slug=client_slug,
            session_id=conversation_id,
            owner_principal_id=owner_principal_id,
            variant_ids=request.variant_ids,
        )
        # One trail row per post, in the same transaction as all the inserts:
        # the batch is atomic in both halves of rule 2, not just in the write.
        for post in saved:
            await conn.execute(
                AUDIT_SQL, conversation_id, event_name(POST_SAVED, post["title"])
            )

    return {
        "count": len(saved),
        "saved": [{"id": post["id"], "title": post["title"]} for post in saved],
    }


@server.tool()
async def update_post(
    post_id: str,
    title: str,
    pillar: str,
    format: str,
    hook: str,
    hook_type: str,
    # NULLABLE, AND STILL REQUIRED. A silent Reel has no script and no
    # production block, so the JSON the application hands the model carries
    # `"script": null` — and the model is told, in as many words, to copy that
    # content literally. Until 2026-08-31 these two were plain `str` and `dict`,
    # so `null` violated the schema: the call was rejected before the tool ran,
    # the model corrected itself to `""`, and the corrected call hit the
    # approval gate AGAIN. From the page that looked like confirming a save and
    # being told the change was cancelled — every time, for any saved Reel.
    # No default, so the model must still send both: what is being replaced is
    # the WHOLE post, and a field it may omit is a field it may drop.
    script: str | None,
    caption: str,
    hashtags: list[str],
    cta: str,
    source: str,
    format_details: dict | None,
    ctx: Context,
) -> dict:
    """Replace a saved post with the version rewritten in the interface.

    You send the COMPLETE content, exactly as the application gave it to you,
    including the unchanged fields. Do not rephrase anything: what you send
    replaces everything that was there.

    CAREFUL: the old version is NOT kept anywhere. It applies only after Viorela
    confirms at the gate.

    `hook_type` is one of PROVOCARE, CIFRA, SECRET, INTREBARE, CONTRAST.
    `hashtags` is a list of 3–5 tags, each starting with #.
    """
    conversation_id = conversation_of(ctx)
    content = SavedPostContent.model_validate(
        {
            "title": title,
            "pillar": pillar,
            "format": format,
            "hook": hook,
            "hook_type": hook_type,
            # EMPTY IS ABSENT, for the two fields a silent Reel does not have.
            # The parameters above are required so the model always sends the
            # complete post; `SavedPostContent` says `str | None` with a
            # `min_length` of 3. So `""` — which is what the editor sends for a
            # Reel's script — was neither absent nor long enough, and the tool
            # raised "String should have at least 3 characters" on every attempt.
            # The model read the error and called the tool again, hit the
            # approval gate again, and the page reported the change cancelled.
            # A saved Reel could not be edited at all. Found 2026-08-31.
            "script": script or None,
            "caption": caption,
            "hashtags": hashtags,
            "cta": cta,
            "source": source,
            "format_details": format_details or None,
        }
    )

    client_slug = await client_of(ctx)
    async with connection() as conn:
        post = await update_saved_post(
            conn,
            client_slug=client_slug,
            post_id=UUID(post_id),
            content=content,
        )
        await conn.execute(
            AUDIT_SQL, conversation_id, event_name(POST_UPDATED, post["title"])
        )

    return {"id": post["id"], "title": post["title"]}


WRITE_PROFILE_SQL = """
UPDATE public.clients SET profile_md = $2, updated_at = NOW() WHERE id = $1
"""


#: Both heading levels the profile uses. `##` are the six numbered parts, `###`
#: are the sections inside them.
#:
#: IT WAS `^##` UNTIL 2026-08-31, AND THAT MADE THIS TOOL UNABLE TO EDIT ANYTHING
#: THE INTERFACE OFFERS. `harness/profile.py` reads `#{2,3}` and shows the `###`
#: sections as the editable cards - every card on the page. This matched only the
#: `##` parents, so every save raised "there is no section named …", in both
#: languages, for as long as the page has existed. The run still finished
#: `completed`, because the agent handled the tool error and wrote a sentence
#: about it, and the page said "the change was saved". Found on 2026-08-31 by
#: editing a name in the browser and then reading `clients.updated_at`, which had
#: not moved.
#:
#: Horizontal whitespace only after the hashes. `\s` would swallow the blank
#: lines after the heading and then add extra spacing on rewrite.
PROFILE_HEADING = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*$", re.MULTILINE)

#: The wrapper the harness puts around the exact text it wants written back, so
#: the model can see where the section starts and ends. It is scaffolding, and
#: the model copied it into the document the first time a save ever reached this
#: function (2026-08-31 — every earlier save had failed on the heading level
#: above, so nobody had seen it). A prompt asks; this makes sure. The client's
#: profile is a document she reads, and it does not carry our tags.
SCAFFOLD = re.compile(r"</?profile-section>", re.IGNORECASE)


def without_scaffolding(new_text: str) -> str:
    return SCAFFOLD.sub("", new_text).strip()


def replace_section(profile: str, section: str, new_text: str) -> str:
    """Replace the body of a `##` or `###` section, leaving the rest alone.

    The section heading keeps whatever the profile says, not what the model wrote —
    otherwise a difference in diacritics or an emoji would rewrite the heading.

    A section's body ends at the NEXT heading of either level, so replacing a
    `##` part rewrites its own introduction and never swallows the `###` sections
    underneath it.
    """
    new_text = without_scaffolding(new_text)
    headings = list(PROFILE_HEADING.finditer(profile))
    wanted = section.strip().lower()

    # Exact title first, substring second. "Your niche" names a `###` section and
    # is also inside the `## 2. Your niche — in detail` part; the one the caller
    # typed in full is the one they meant.
    exact = [i for i, h in enumerate(headings) if h.group(2).strip().lower() == wanted]
    loose = [i for i, h in enumerate(headings) if wanted in h.group(2).lower()]

    for i in exact or loose:
        start = headings[i].end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(profile)
        return profile[:start] + "\n\n" + new_text.strip() + "\n\n" + profile[end:]

    existing = "\n".join(f"  · {h.group(2)}" for h in headings)
    raise ValueError(
        f"There is no section containing {section!r} in the profile.\n"
        f"Today's sections are:\n{existing}"
    )


@server.tool()
async def update_profile(section: str, new_text: str, ctx: Context) -> dict:
    """Rewrite one section of Viorela's profile. Only when she asks explicitly.

    `section` is a piece of the section's title, as it appears in the profile
    („Oferte", „CTA"). `new_text` is the section's whole body, without the title
    line — what you send replaces everything that was there, so write it in full,
    not just the addition.

    CAREFUL: what was there before is NOT kept anywhere. Ask her to confirm the
    whole text before you call the tool.
    """
    # Until D4 the previous text was kept in `audit_log.payload`, and a mistaken
    # rewrite could be undone from the trail. The course's trail has no payload
    # column, so that safety net is gone: this tool is now destructive. The
    # profile is still on disk at content/profile.md, which is what `db.seed`
    # restores from — but anything she changed through the agent since the last
    # seed is not there either. Worth a column of its own if this bites.
    conversation_id = conversation_of(ctx)
    client_slug = await client_of(ctx)
    async with connection() as conn:
        row = await conn.fetchrow(PROFILE_SQL, client_slug)
        if row is None:
            raise ValueError(f"There is no client {client_slug!r} in the `clients` table.")

        new_profile = replace_section(row["profile_md"], section, new_text)
        await conn.execute(WRITE_PROFILE_SQL, row["id"], new_profile)
        await conn.execute(
            AUDIT_SQL, conversation_id, event_name(PROFILE_UPDATED, section)
        )

    return {
        "section": section,
        "profile_was": len(row["profile_md"]),
        "profile_is": len(new_profile),
    }


# ---- the chat trigger tools (2026-08-27) -------------------------------------
#
# The conversation agent never writes content: these tools record what she asked
# for, validated, and the harness runs the same generation pipeline the buttons
# use. The tool answers immediately — the model tells her the app is working —
# and the result reaches both windows through the tables, written once.


@server.tool()
async def start_generation(
    format: FormatChoice,
    pillar: PillarChoice,
    source: SourceChoice,
    ctx: Context,
    focus: str | None = None,
) -> dict:
    """Start Viorela's batch of 10 ideas, with the application's whole method.

    You call it ONLY after she has chosen the format, the pillar and the source —
    if one is missing, you ask her first, with the skill's closed vocabulary.
    `focus` is her theme, if she gave one; do not invent a focus. The books are not
    chosen here: the engine picks the fitting titles off the shelf itself.

    You do NOT write the ten ideas: the application generates them and brings them
    into the conversation and into the interface. After you call the tool, you only
    tell her the batch is starting and appears in a few tens of seconds. A new
    batch closes the old one.
    """
    # The identity is enforced, not used: the harness executes under the same
    # principal it authenticated, never one the model could influence.
    owner_of(ctx)
    conversation_id = conversation_of(ctx)
    request = GenerationBatchRequest.model_validate(
        {"format": format, "pillar": pillar, "source": source, "focus": focus}
    )
    async with connection() as conn:
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(
                GENERATION_REQUESTED,
                f"{request.format}/{request.pillar}/{request.source}",
            ),
        )
    # The harness watches the run for this call and launches the pipeline.
    return {
        "status": "accepted",
        "format": request.format,
        "pillar": request.pillar,
        "source": request.source,
        "focus": request.focus,
        "note": (
            "The batch is starting now; the ten ideas appear in the conversation "
            "and in the interface within a few tens of seconds. Do not write them "
            "yourself."
        ),
    }


@server.tool()
async def develop_idea(idea: int, ctx: Context) -> dict:
    """Develop one idea from the current batch: the application writes the five variants.

    `idea` is the proposal's number in the list, 1–10 — „a treia” means 3. You call
    it when Viorela chooses which proposal we develop. You do NOT write the
    variants: the application generates them with the format's method and brings
    them into the conversation and into the interface. If there is no batch in the
    conversation, the tool tells you — then you offer her the ten ideas first, you
    do not guess a list.
    """
    owner = owner_of(ctx)
    conversation_id = conversation_of(ctx)
    if not 1 <= idea <= 10:
        raise ValueError("The idea is chosen with a number between 1 and 10.")
    async with connection() as conn:
        batch = await load_current_batch(conn, owner)
    if batch is None:
        raise ValueError(
            "There is no batch of ideas in this conversation. Offer her the ten "
            "first, with start_generation."
        )
    found = next(
        (item for item in batch.get("ideas", []) if int(item["ordinal"]) == idea),
        None,
    )
    if found is None:
        raise ValueError(f"the current batch has no idea {idea}.")
    async with connection() as conn:
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(IDEA_DEVELOPMENT_REQUESTED, f"{batch['id']}/{idea}"),
        )
    return {
        "status": "accepted",
        "idea": idea,
        "title": found["title"],
        "already_ready": found.get("status") == "ready",
        "note": (
            "The five variants appear in the conversation and in the interface "
            "within a few tens of seconds. Do not write them yourself."
        ),
    }


@server.tool()
async def select_variant(idea: int, hook_type: str, ctx: Context) -> dict:
    """Mark the variant Viorela chose from a developed idea.

    `idea` is the idea's number, 1–10. `hook_type` is the variant's hook name,
    exactly one of: PROVOCARE, CIFRA, SECRET, INTREBARE, CONTRAST — „a doua” from
    the list she was shown means the second hook in the displayed order. The choice
    shows in the interface immediately; saving for good stays her step, with a
    confirmation.
    """
    owner = owner_of(ctx)
    conversation_id = conversation_of(ctx)
    hook = hook_type.strip().upper()
    if hook not in HOOK_TYPES:
        raise ValueError(
            "hook_type must be one of: " + ", ".join(HOOK_TYPES)
        )
    async with connection() as conn:
        batch = await load_current_batch(conn, owner)
    if batch is None:
        raise ValueError("There is no current batch to choose from.")
    found = next(
        (item for item in batch.get("ideas", []) if int(item["ordinal"]) == idea),
        None,
    )
    if found is None:
        raise ValueError(f"the current batch has no idea {idea}.")
    variant = next(
        (
            item
            for item in found.get("variants", [])
            if str(item.get("hook_type")) == hook
        ),
        None,
    )
    if variant is None or variant.get("status") != "ready":
        raise ValueError(
            f"Idea {idea} has no {hook} variant ready. "
            "Develop it first with develop_idea."
        )
    async with connection() as conn:
        result = await select_variant_store(conn, UUID(str(variant["id"])), owner)
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_VARIANT_SELECTED, str(variant["id"])),
        )
    return {
        "status": "selected",
        "idea": result["idea_ordinal"],
        "title": result["idea_title"],
        "hook_type": result["hook_type"],
        "hook": variant.get("hook"),
    }


# ---- D1b internal UI operations ---------------------------------------------
#
# These functions are MCP tools so the harness still crosses the same typed data
# boundary as the agent. `MODEL_VISIBLE_TOOLS` filters them out of the agent's
# view entirely; only the harness calls them programmatically.


@server.tool()
async def ui_create_generation_batch(
    owner_principal_id: str,
    format: str,
    pillar: str,
    source: str,
    ctx: Context,
    focus: str | None = None,
    source_packet: dict | None = None,
    model: str | None = None,
) -> dict:
    """Create the interface's current batch, internally; not an agent tool."""
    conversation_id = conversation_of(ctx)
    request = GenerationBatchRequest.model_validate(
        {
            "format": format,
            "pillar": pillar,
            "source": source,
            "focus": focus,
            "model": model,
        }
    )
    client_slug = await client_of(ctx)
    async with connection() as conn:
        result = await create_batch(
            conn,
            client_slug=client_slug,
            owner_principal_id=owner_principal_id,
            session_id=conversation_id,
            request=request,
            source_packet=source_packet or {},
        )
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_BATCH_CREATED, result["id"]),
        )
    return result


@server.tool()
async def ui_put_generation_titles(
    batch_id: str, ideas: list[dict], ctx: Context
) -> dict:
    """Persist exactly the ten validated titles, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    value = IdeaTitles.model_validate({"ideas": ideas})
    async with connection() as conn:
        result = await put_titles(conn, UUID(batch_id), value)
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_TITLES_READY, batch_id),
        )
    return result


@server.tool()
async def ui_start_generation_idea(
    batch_id: str, ordinal: int, ctx: Context
) -> dict:
    """Mark an idea as in progress, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    async with connection() as conn:
        result = await start_idea(conn, UUID(batch_id), ordinal)
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_IDEA_STARTED, f"{batch_id}/{ordinal}"),
        )
    return result


@server.tool()
async def ui_complete_generation_idea(
    batch_id: str, idea: dict, ctx: Context
) -> dict:
    """Persist the five complete variants, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    value = IdeaDetails.model_validate(idea)
    async with connection() as conn:
        result = await complete_idea(conn, UUID(batch_id), value)
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_IDEA_READY, f"{batch_id}/{value.idea_ordinal}"),
        )
    return result


@server.tool()
async def ui_fail_generation_idea(
    batch_id: str,
    ordinal: int,
    error: str,
    retryable: bool,
    ctx: Context,
) -> dict:
    """Record one idea's settled failure, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    async with connection() as conn:
        result = await fail_idea(
            conn, UUID(batch_id), ordinal, error, retryable=retryable
        )
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_IDEA_FAILED, f"{batch_id}/{ordinal}"),
        )
    return result


@server.tool()
async def ui_fail_generation_batch(batch_id: str, error: str, ctx: Context) -> dict:
    """Record the batch's failure before any title, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    safe_error = " ".join(error.split())[:180] or "generation failed"
    async with connection() as conn:
        result = await fail_batch(conn, UUID(batch_id))
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_BATCH_FAILED, f"{batch_id}/{safe_error}"),
        )
    return result


@server.tool()
async def ui_select_generation_variant(
    variant_id: str, owner_principal_id: str, ctx: Context
) -> dict:
    """Choose one ready variant, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    async with connection() as conn:
        result = await select_variant_store(
            conn, UUID(variant_id), owner_principal_id
        )
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_VARIANT_SELECTED, variant_id),
        )
    return result


@server.tool()
async def ui_patch_generation_variant(
    variant_id: str,
    owner_principal_id: str,
    content: dict,
    ctx: Context,
) -> dict:
    """Replace a fully validated draft, internally; not an agent tool."""
    conversation_id = conversation_of(ctx)
    value = IdeaVariant.model_validate(content)
    async with connection() as conn:
        result = await patch_variant(
            conn, UUID(variant_id), owner_principal_id, value
        )
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_VARIANT_PATCHED, variant_id),
        )
    return result


@server.tool()
async def ui_cancel_generation_batch(
    batch_id: str, owner_principal_id: str, ctx: Context
) -> dict:
    """Stop the identity's current batch, internally; not for the agent."""
    conversation_id = conversation_of(ctx)
    async with connection() as conn:
        result = await cancel_batch(conn, UUID(batch_id), owner_principal_id)
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(GENERATION_CANCELLED, batch_id),
        )
    return result


@server.tool()
async def ui_get_generation_batch(batch_id: str) -> dict:
    """Read one batch and its variants, internally; not for the agent."""
    async with connection() as conn:
        return await load_batch(conn, UUID(batch_id))


@server.tool()
async def ui_get_current_generation_batch(owner_principal_id: str) -> dict:
    """Read the identity's current batch, internally; not for the agent."""
    async with connection() as conn:
        return {"batch": await load_current_batch(conn, owner_principal_id)}


@server.tool()
async def ui_current_conversation(owner_principal_id: str, ctx: Context) -> dict:
    """The account's active conversation, created on first request. Not for the agent."""
    conversation_id = conversation_of(ctx)
    client_slug = await client_of(ctx)
    async with connection() as conn:
        row, created = await current_conversation(
            conn, client_slug=client_slug, owner_principal_id=owner_principal_id
        )
        if created:
            await conn.execute(
                AUDIT_SQL,
                conversation_id,
                event_name(CONVERSATION_STARTED, row["session_id"]),
            )
    return {"conversation": row}


@server.tool()
async def ui_new_conversation(owner_principal_id: str, ctx: Context) -> dict:
    """Archive the active conversation and start a new one; the old batch leaves
    the interface in the same transaction. Not for the agent."""
    conversation_id = conversation_of(ctx)
    client_slug = await client_of(ctx)
    async with connection() as conn:
        row = await new_conversation(
            conn, client_slug=client_slug, owner_principal_id=owner_principal_id
        )
        await conn.execute(
            AUDIT_SQL,
            conversation_id,
            event_name(CONVERSATION_STARTED, row["session_id"]),
        )
    return {"conversation": row}


@server.tool()
async def ui_bind_conversation_batch(
    owner_principal_id: str, batch_id: str, ctx: Context
) -> dict:
    """Bind the batch to the account's active conversation; not for the agent."""
    async with connection() as conn:
        row = await bind_conversation_batch(
            conn, owner_principal_id=owner_principal_id, batch_id=UUID(batch_id)
        )
    return {"conversation": row}


@server.tool()
async def ui_list_library(ctx: Context) -> dict:
    """List the selectable books, internally; does not expose document bodies."""
    client_slug = await client_of(ctx)
    async with connection() as conn:
        return {"items": await list_library(conn, client_slug)}


@server.tool()
async def ui_list_saved_posts(ctx: Context, limit: int = 100) -> dict:
    """Read the posts written in the studio, internally; not for the agent."""
    client_slug = await client_of(ctx)
    async with connection() as conn:
        return {"items": await list_saved_posts(conn, client_slug, limit)}


@server.tool()
async def ui_get_saved_post(post_id: str, ctx: Context) -> dict:
    """Read a single saved post, internally; not for the agent."""
    client_slug = await client_of(ctx)
    async with connection() as conn:
        return {"post": await load_saved_post(conn, client_slug, UUID(post_id))}


@server.tool()
async def ui_resolve_account(principal_id: str) -> dict:
    """Resolve an identity's account, internally; not for the agent.

    Takes the principal as an argument rather than off the connection because
    the admin page will need to ask about somebody other than the caller. It is
    safe: the tool is internal, and `MODEL_VISIBLE_TOOLS` never lets the model
    see it.
    """
    async with connection() as conn:
        account = await resolve_account(conn, principal_id)
    return {"account": account.as_dict() if account is not None else None}


@server.tool()
async def ui_record_usage(
    client_slug: str,
    principal_id: str,
    kind: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_micros: int,
    cached_input_tokens: int = 0,
) -> dict:
    """Record one call's usage, internally; not for the agent."""
    async with connection() as conn:
        row_id = await record_usage(
            conn,
            client_slug=client_slug,
            principal_id=principal_id,
            kind=kind,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            cost_micros=cost_micros,
        )
    return {"id": row_id}


@server.tool()
async def ui_get_budget(client_slug: str) -> dict:
    """Read an account's allowance and usage, internally; not for the agent."""
    async with connection() as conn:
        budget = await load_budget(conn, client_slug)
    return {"budget": budget.as_dict() if budget is not None else None}


@server.tool()
async def ui_set_budget(client_slug: str, budget_micros: int) -> dict:
    """Change an account's allowance, internally; not for the agent."""
    async with connection() as conn:
        value = await set_budget(conn, client_slug, budget_micros)
    return {"budget_micros": value}


@server.tool()
async def ui_set_account_disabled(principal_id: str, disabled: bool) -> dict:
    """Suspend or reactivate an account, internally; not for the agent."""
    async with connection() as conn:
        return {"account": await set_disabled(conn, principal_id, disabled)}


@server.tool()
async def ui_list_usage() -> dict:
    """List every account's usage, internally; not for the agent."""
    async with connection() as conn:
        return {"items": await all_usage(conn)}


@server.tool()
async def ui_list_accounts() -> dict:
    """List the provisioned accounts, internally; not for the agent."""
    async with connection() as conn:
        return {"items": await list_accounts(conn)}


@server.tool()
async def ui_provision_account(
    principal_id: str,
    email: str,
    provider: str,
    display_name: str = "",
    client_slug: str = "",
) -> dict:
    """Create a principal's studio on their first sign-in; not for the agent.

    Only reached for providers named in AUTH_SELF_PROVISION_PROVIDERS, which the
    harness checks before calling - a directory only Sorin can add people to.
    Role and allowance are not parameters here; see `provision_self`.

    `client_slug` attaches the principal to a studio that already exists instead
    of making one. The harness passes it for the owner alone, whose `clients` row
    predates accounts entirely.
    """
    async with connection() as conn:
        account, created = await provision_self(
            conn,
            principal_id=principal_id,
            email=email,
            provider=provider,
            display_name=display_name,
            client_slug=client_slug or None,
        )
        if created and account is not None:
            # The first argument is a session id, and there is no session: this
            # runs while a request is being authenticated, before any run exists.
            # The sub-select finds nothing and `run_id` lands NULL, which the
            # column allows - a trail row with no run beats no trail row at all.
            await conn.execute(
                AUDIT_SQL,
                principal_id,
                event_name(ACCOUNT_PROVISIONED, account.client_slug),
            )
    return {"account": account.as_dict() if account is not None else None}


def main() -> int:
    global _engine

    # First, so that a failure in the configuration below is itself debuggable.
    attach_if_requested("content-data")

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

    # Counted off the constants, not typed out. This line said "five agent tools"
    # while ten were registered - a hand-written number is a second source of
    # truth for something the code already knows, and it drifted silently
    # because nothing reads a banner.
    print(f"content-data · {len(MODEL_VISIBLE_TOOLS)} agent tools + "
          f"{len(INTERNAL_UI_TOOLS)} internal UI operations · "
          f"http://{MCP_HOST}:{MCP_PORT}/mcp")
    print(f"Database: {describe_database(url)}")
    print("Leave it running and open the harness or a check in another terminal.\n")

    # stateless: every request is complete in itself, with no session kept between
    # them. The worker is a single process on the same machine — there is nothing
    # to gain from session state, and something to lose if it desynchronizes.
    server.run("streamable-http", host=MCP_HOST, port=MCP_PORT, stateless_http=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
