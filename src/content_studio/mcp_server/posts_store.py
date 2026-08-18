"""Persistence for saved posts: the batch write, the rewrite, and the two reads.

`public.posts` is the client's own work, not a draft table. Everything here runs
inside one caller-supplied transaction so the audit rows in `server.py` land with
the write they describe (rule 2) — and so a batch of ten is all or nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from content_studio.harness.posts import (
    HOOK_TYPE_LABELS,
    SavedPostContent,
    SavePostsBatch,
)

CLIENT_ID_SQL = "SELECT id FROM public.clients WHERE slug = $1"

# Only variants the client actually chose can become posts. `is_selected` is
# already unique per idea, so this is also what stops the same idea being saved
# twice in one batch. The order of the request is preserved so the returned rows
# line up with what the browser asked for.
SELECTED_VARIANTS_SQL = """
SELECT v.id, v.hook_type, v.hook, v.script, v.caption, v.hashtags, v.cta,
       v.source, v.format_details, i.title, b.pillar, b.format
  FROM public.generation_variants v
  JOIN public.generation_ideas i    ON i.id = v.idea_id
  JOIN public.generation_batches b  ON b.id = i.batch_id
 WHERE v.id = ANY($1::uuid[])
   AND b.owner_principal_id = $2
   AND v.status = 'ready'
   AND v.is_selected
 ORDER BY array_position($1::uuid[], v.id)
"""

INSERT_POST_SQL = """
INSERT INTO public.posts (client_id, conversation_id, posted_on, title, pillar,
                          format, hook, hook_type, script, caption, hashtags,
                          cta, source, format_details, status, body_md)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb,
        'draft', $15)
RETURNING *
"""

# `source_file IS NULL` is the line between the archive imported from disk and
# the posts written in the studio. The imported ones keep `body_md` exactly as
# the file arrived; rewriting them through this editor would destroy that.
UPDATE_POST_SQL = """
UPDATE public.posts
   SET title = $3, pillar = $4, format = $5, hook = $6, hook_type = $7,
       script = $8, caption = $9, hashtags = $10, cta = $11, source = $12,
       format_details = $13::jsonb, body_md = $14
 WHERE id = $1 AND client_id = $2 AND source_file IS NULL
RETURNING *
"""

LIST_SAVED_SQL = """
SELECT * FROM public.posts
 WHERE client_id = $1 AND source_file IS NULL
 ORDER BY created_at DESC, id
 LIMIT $2
"""

GET_SAVED_SQL = """
SELECT * FROM public.posts
 WHERE id = $1 AND client_id = $2 AND source_file IS NULL
"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_or_null(value: object | None) -> str | None:
    """SQL NULL for an absent production block, not the JSON string "null"."""

    return None if value is None else _json(value)


def _wire(value: Any) -> Any:
    if isinstance(value, (UUID, date, datetime)):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if isinstance(value, Mapping):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_wire(item) for item in value]
    return value


def _row(row: Any) -> dict[str, Any]:
    value = dict(row)
    if isinstance(value.get("format_details"), str):
        value["format_details"] = json.loads(value["format_details"])
    return _wire(value)


def as_markdown(fields: dict, format_details: dict | None = None) -> str:
    """The whole post as Markdown, for the `body_md` column.

    Built here from the fields rather than asked of the model: `body_md` has to be
    exactly what was saved in the columns, not a second version written separately.
    """
    document = [
        f"# {fields['title']}",
        "",
        f"**Pilon:** {fields['pillar']} · **Format:** {fields['format']}",
        f"**Hook ({fields['hook_type']}):** {fields['hook']}",
        "",
    ]
    # A silent reel has neither section. Printing empty headings would put two
    # promises in `body_md` that the columns do not keep.
    if fields["script"]:
        document += ["## Script", fields["script"], ""]
    if format_details:
        blocks = format_details["content_blocks"]
        document += [
            f"## Producție ({format_details['duration_or_count']})",
            format_details["visual_direction"],
            "",
            *(f"{index}. {block}" for index, block in enumerate(blocks, 1)),
            "",
        ]
    document += [
        "## Caption",
        fields["caption"],
        "",
        f"**Hashtaguri:** {fields['hashtags']}",
        f"**CTA:** {fields['cta']}",
        f"**Sursa:** {fields['source']}",
        "",
    ]
    return "\n".join(document)


def _columns(
    content: SavedPostContent,
) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
    """One validated post as (column values, format details, body_md)."""

    details = (
        None if content.format_details is None else content.format_details.model_dump()
    )
    fields = {
        "title": content.title,
        "pillar": content.pillar,
        "format": content.format,
        "hook": content.hook,
        "hook_type": HOOK_TYPE_LABELS[content.hook_type],
        "script": content.script,
        "caption": content.caption,
        "hashtags": " ".join(content.hashtags),
        "cta": content.cta,
        "source": content.source,
    }
    return fields, details, as_markdown(fields, details)


async def client_id(conn, client_slug: str) -> UUID:
    value = await conn.fetchval(CLIENT_ID_SQL, client_slug)
    if value is None:
        raise ValueError(f"There is no client {client_slug!r} in the `clients` table.")
    return value


async def save_selected_variants(
    conn,
    *,
    client_slug: str,
    session_id: str,
    owner_principal_id: str,
    variant_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Copy chosen draft variants into `public.posts`, all of them or none."""

    owner = await client_id(conn, client_slug)
    rows = await conn.fetch(SELECTED_VARIANTS_SQL, variant_ids, owner_principal_id)
    found = {str(row["id"]) for row in rows}
    missing = [str(value) for value in variant_ids if str(value) not in found]
    if missing:
        raise ValueError(
            "these variants are not chosen, not ready, or not owned by this "
            "identity: " + ", ".join(missing)
        )

    # Validated before the first INSERT rather than row by row: a batch that
    # would fail halfway must not leave the client with half her posts saved.
    batch = SavePostsBatch.model_validate(
        {
            "posts": [
                {
                    "title": row["title"],
                    "pillar": row["pillar"],
                    "format": row["format"],
                    "hook": row["hook"],
                    "hook_type": row["hook_type"],
                    "script": row["script"],
                    "caption": row["caption"],
                    "hashtags": _row(row)["hashtags"],
                    "cta": row["cta"],
                    "source": row["source"],
                    "format_details": _row(row)["format_details"],
                }
                for row in rows
            ]
        }
    )

    saved = []
    for content in batch.posts:
        fields, details, body_md = _columns(content)
        row = await conn.fetchrow(
            INSERT_POST_SQL,
            owner,
            session_id,
            date.today(),
            fields["title"],
            fields["pillar"],
            fields["format"],
            fields["hook"],
            fields["hook_type"],
            fields["script"],
            fields["caption"],
            fields["hashtags"],
            fields["cta"],
            fields["source"],
            _json_or_null(details),
            body_md,
        )
        saved.append(_row(row))
    return saved


async def update_saved_post(
    conn,
    *,
    client_slug: str,
    post_id: UUID,
    content: SavedPostContent,
) -> dict[str, Any]:
    """Replace one studio-written post with the browser's complete draft."""

    owner = await client_id(conn, client_slug)
    fields, details, body_md = _columns(content)
    row = await conn.fetchrow(
        UPDATE_POST_SQL,
        post_id,
        owner,
        fields["title"],
        fields["pillar"],
        fields["format"],
        fields["hook"],
        fields["hook_type"],
        fields["script"],
        fields["caption"],
        fields["hashtags"],
        fields["cta"],
        fields["source"],
        _json_or_null(details),
        body_md,
    )
    if row is None:
        raise ValueError("no studio-written post with that id belongs to this client")
    return _row(row)


async def list_saved_posts(
    conn, client_slug: str, limit: int = 100
) -> list[dict[str, Any]]:
    owner = await client_id(conn, client_slug)
    rows = await conn.fetch(LIST_SAVED_SQL, owner, max(1, min(limit, 200)))
    return [_row(row) for row in rows]


async def load_saved_post(conn, client_slug: str, post_id: UUID) -> dict[str, Any]:
    owner = await client_id(conn, client_slug)
    row = await conn.fetchrow(GET_SAVED_SQL, post_id, owner)
    if row is None:
        raise ValueError("no studio-written post with that id belongs to this client")
    return _row(row)
