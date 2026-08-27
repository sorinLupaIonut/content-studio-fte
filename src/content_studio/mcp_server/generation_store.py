"""Typed persistence primitives for the current D1b generation draft."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from content_studio.harness.generation import (
    HOOK_TYPES,
    GenerationBatchRequest,
    IdeaDetails,
    IdeaTitles,
    IdeaVariant,
)

CLIENT_ID_SQL = "SELECT id FROM public.clients WHERE slug = $1"

REPLACE_CURRENT_SQL = """
UPDATE public.generation_batches
   SET status = 'replaced', is_current = false, updated_at = now()
 WHERE owner_principal_id = $1 AND is_current
"""

INSERT_BATCH_SQL = """
INSERT INTO public.generation_batches (
    client_id, owner_principal_id, session_id, source, pillar, format, focus,
    material_ids, source_packet, model
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8::uuid[], $9::jsonb, $10)
RETURNING *
"""

UPSERT_IDEA_SQL = """
INSERT INTO public.generation_ideas (batch_id, ordinal, title, angle)
VALUES ($1, $2, $3, $4)
ON CONFLICT (batch_id, ordinal) DO UPDATE
   SET title = EXCLUDED.title, angle = EXCLUDED.angle, status = 'waiting',
       retry_count = 0, last_error = NULL, updated_at = now()
RETURNING id
"""

UPSERT_EMPTY_VARIANT_SQL = """
INSERT INTO public.generation_variants (idea_id, hook_type)
VALUES ($1, $2)
ON CONFLICT (idea_id, hook_type) DO UPDATE
   SET status = 'waiting', hook = NULL, script = NULL, caption = NULL,
       hashtags = NULL, cta = NULL, source = NULL, format_details = NULL,
       is_selected = false, updated_at = now()
"""

START_IDEA_SQL = """
UPDATE public.generation_ideas i
   SET status = 'generating', last_error = NULL, updated_at = now()
  FROM public.generation_batches b
 WHERE i.batch_id = b.id AND b.id = $1 AND i.ordinal = $2
   AND b.is_current AND NOT b.cancel_requested
RETURNING i.id, i.ordinal, i.title, i.angle
"""

MARK_VARIANTS_GENERATING_SQL = """
UPDATE public.generation_variants
   SET status = 'generating', updated_at = now()
 WHERE idea_id = $1
"""

UPSERT_READY_VARIANT_SQL = """
INSERT INTO public.generation_variants (
    idea_id, hook_type, status, hook, script, caption, hashtags, cta, source,
    format_details
)
VALUES ($1, $2, 'ready', $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb)
ON CONFLICT (idea_id, hook_type) DO UPDATE
   SET status = 'ready', hook = EXCLUDED.hook, script = EXCLUDED.script,
       caption = EXCLUDED.caption, hashtags = EXCLUDED.hashtags,
       cta = EXCLUDED.cta, source = EXCLUDED.source,
       format_details = EXCLUDED.format_details, updated_at = now()
"""

READY_IDEA_SQL = """
UPDATE public.generation_ideas
   SET status = 'ready', last_error = NULL, updated_at = now()
 WHERE id = $1
"""

FIND_ACTIVE_IDEA_SQL = """
SELECT i.id
  FROM public.generation_ideas i
  JOIN public.generation_batches b ON b.id = i.batch_id
 WHERE b.id = $1 AND i.ordinal = $2
   AND b.is_current AND NOT b.cancel_requested
"""

# A batch is working only while an idea is ACTUALLY being written - not while
# one is merely undeveloped.
#
# This used to read `status NOT IN ('ready', 'failed')`, which was right while
# all ten details were written the moment the titles landed: an idea still
# `waiting` then meant a queue that had not reached it yet. Since 2026-08-24
# details are written when she opens an idea, so nine ideas sit at `waiting` by
# design, possibly for days - and that condition pinned every batch at
# 'generating' for ever, with a spinner and a cancel button over work nobody was
# doing.
#
# 'failed' stays reserved for the case where nothing at all came back, and
# 'titles_ready' is now a resting state rather than a moment in passing.
REFRESH_BATCH_STATUS_SQL = """
UPDATE public.generation_batches b
   SET status = CASE
       WHEN b.cancel_requested THEN 'cancelled'
       WHEN EXISTS (
           SELECT 1 FROM public.generation_ideas i
            WHERE i.batch_id = b.id AND i.status IN ('generating', 'retrying')
       ) THEN 'generating'
       WHEN EXISTS (
           SELECT 1 FROM public.generation_ideas i
            WHERE i.batch_id = b.id AND i.status = 'ready'
       ) THEN 'ready'
       WHEN EXISTS (
           SELECT 1 FROM public.generation_ideas i
            WHERE i.batch_id = b.id AND i.status = 'waiting'
       ) THEN 'titles_ready'
       ELSE 'failed'
   END,
       updated_at = now()
 WHERE b.id = $1
RETURNING status
"""

FAIL_IDEA_SQL = """
UPDATE public.generation_ideas i
   SET status = CASE WHEN $4 THEN 'retrying' ELSE 'failed' END,
       retry_count = retry_count + 1, last_error = $3, updated_at = now()
  FROM public.generation_batches b
 WHERE i.batch_id = b.id AND b.id = $1 AND i.ordinal = $2
   AND b.is_current AND NOT b.cancel_requested
RETURNING i.id, i.status, i.retry_count
"""

CANCEL_BATCH_SQL = """
UPDATE public.generation_batches
   SET status = 'cancelled', cancel_requested = true, updated_at = now()
 WHERE id = $1 AND owner_principal_id = $2 AND is_current
RETURNING id
"""

CANCEL_IDEAS_SQL = """
UPDATE public.generation_ideas
   SET status = 'cancelled', updated_at = now()
 WHERE batch_id = $1 AND status IN ('waiting', 'generating', 'retrying')
"""

CANCEL_VARIANTS_SQL = """
UPDATE public.generation_variants v
   SET status = 'cancelled', updated_at = now()
  FROM public.generation_ideas i
 WHERE v.idea_id = i.id AND i.batch_id = $1
   AND v.status IN ('waiting', 'generating')
"""

FIND_SELECTABLE_SQL = """
SELECT v.id, v.idea_id, v.hook_type, i.ordinal, i.title
  FROM public.generation_variants v
  JOIN public.generation_ideas i ON i.id = v.idea_id
  JOIN public.generation_batches b ON b.id = i.batch_id
 WHERE v.id = $1 AND b.owner_principal_id = $2 AND b.is_current
   AND v.status = 'ready'
"""

UNSELECT_IDEA_SQL = """
UPDATE public.generation_variants
   SET is_selected = false, updated_at = now()
 WHERE idea_id = $1
"""

SELECT_VARIANT_SQL = """
UPDATE public.generation_variants
   SET is_selected = true, updated_at = now()
 WHERE id = $1
"""

FIND_PATCHABLE_VARIANT_SQL = """
SELECT v.id, v.idea_id, v.hook_type, v.script, i.batch_id
  FROM public.generation_variants v
  JOIN public.generation_ideas i ON i.id = v.idea_id
  JOIN public.generation_batches b ON b.id = i.batch_id
 WHERE v.id = $1 AND b.owner_principal_id = $2 AND b.is_current
   AND NOT b.cancel_requested AND v.status = 'ready'
 FOR UPDATE OF v
"""

PATCH_VARIANT_SQL = """
UPDATE public.generation_variants
   SET hook = $2, script = $3, caption = $4, hashtags = $5::jsonb,
       cta = $6, source = $7, format_details = $8::jsonb, updated_at = now()
 WHERE id = $1
"""

TOUCH_PATCH_IDEA_SQL = (
    "UPDATE public.generation_ideas SET updated_at = now() WHERE id = $1"
)
TOUCH_PATCH_BATCH_SQL = (
    "UPDATE public.generation_batches SET updated_at = now() WHERE id = $1"
)

GET_BATCH_SQL = "SELECT * FROM public.generation_batches WHERE id = $1"

GET_CURRENT_BATCH_SQL = """
SELECT * FROM public.generation_batches
 WHERE owner_principal_id = $1 AND is_current
"""

GET_IDEAS_SQL = """
SELECT * FROM public.generation_ideas
 WHERE batch_id = $1 ORDER BY ordinal
"""

GET_VARIANTS_SQL = """
SELECT v.*
  FROM public.generation_variants v
  JOIN public.generation_ideas i ON i.id = v.idea_id
 WHERE i.batch_id = $1
 ORDER BY i.ordinal,
          array_position(ARRAY['PROVOCARE','CIFRA','SECRET','INTREBARE','CONTRAST'],
                         v.hook_type)
"""

FAIL_BATCH_SQL = """
UPDATE public.generation_batches
   SET status = 'failed', updated_at = now()
 WHERE id = $1 AND is_current AND NOT cancel_requested
RETURNING id
"""

# Joined through `clients` on the slug rather than taking a client id, because
# every other store function in this module takes the slug and resolving it in
# two places is how the two drift.
LIST_LIBRARY_SQL = """
SELECT d.id, d.title, d.metadata
  FROM public.documents d
  JOIN public.clients   c ON c.id = d.client_id
 WHERE d.source = 'library'
   AND c.slug = $1
 ORDER BY lower(d.title), d.id
"""


def _production(variant: IdeaVariant) -> str | None:
    """The production block as JSONB, or SQL NULL for a silent reel.

    `_json(None)` would write the JSON string "null" into the column, which is
    not the same thing as an absent block and would defeat the check that keeps
    `script` and `format_details` together.
    """

    if variant.format_details is None:
        return None
    return _json(variant.format_details.model_dump())


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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
    for key in ("source_packet", "hashtags", "format_details", "metadata"):
        if isinstance(value.get(key), str):
            value[key] = json.loads(value[key])
    return _wire(value)


async def create_batch(
    conn,
    *,
    client_slug: str,
    owner_principal_id: str,
    session_id: str,
    request: GenerationBatchRequest,
    source_packet: dict[str, Any],
) -> dict[str, Any]:
    owner = owner_principal_id.strip()
    if not owner or len(owner) > 500:
        raise ValueError("owner_principal_id is missing or too long")

    client_id = await conn.fetchval(CLIENT_ID_SQL, client_slug)
    if client_id is None:
        raise ValueError(f"There is no client {client_slug!r} in public.clients.")

    await conn.execute(REPLACE_CURRENT_SQL, owner)
    row = await conn.fetchrow(
        INSERT_BATCH_SQL,
        client_id,
        owner,
        session_id,
        request.source,
        request.pillar,
        request.format,
        request.focus,
        request.material_ids,
        _json(source_packet),
        request.model,
    )
    return _row(row)


async def put_titles(conn, batch_id: UUID, value: IdeaTitles) -> dict[str, Any]:
    for idea in value.ideas:
        idea_id = await conn.fetchval(
            UPSERT_IDEA_SQL, batch_id, idea.ordinal, idea.title, idea.angle
        )
        for hook_type in HOOK_TYPES:
            await conn.execute(UPSERT_EMPTY_VARIANT_SQL, idea_id, hook_type)

    status = await conn.fetchval(
        """
        UPDATE public.generation_batches
           SET status = 'titles_ready', updated_at = now()
         WHERE id = $1 AND is_current AND NOT cancel_requested
        RETURNING status
        """,
        batch_id,
    )
    if status is None:
        raise ValueError("the batch is no longer current or was cancelled")
    return await load_batch(conn, batch_id)


async def start_idea(conn, batch_id: UUID, ordinal: int) -> dict[str, Any]:
    row = await conn.fetchrow(START_IDEA_SQL, batch_id, ordinal)
    if row is None:
        raise ValueError("the idea cannot start because the batch is unavailable")
    await conn.execute(MARK_VARIANTS_GENERATING_SQL, row["id"])
    await conn.execute(
        """
        UPDATE public.generation_batches SET status = 'generating', updated_at = now()
         WHERE id = $1 AND status IN ('titles_ready', 'generating')
        """,
        batch_id,
    )
    return _row(row)


async def complete_idea(conn, batch_id: UUID, value: IdeaDetails) -> dict[str, Any]:
    idea_id = await conn.fetchval(
        FIND_ACTIVE_IDEA_SQL,
        batch_id,
        value.idea_ordinal,
    )
    if idea_id is None:
        raise ValueError("the batch was cancelled, replaced, or does not contain the idea")

    for variant in value.variants:
        await conn.execute(
            UPSERT_READY_VARIANT_SQL,
            idea_id,
            variant.hook_type,
            variant.hook,
            variant.script,
            variant.caption,
            _json(variant.hashtags),
            variant.cta,
            variant.source,
            _production(variant),
        )
    await conn.execute(READY_IDEA_SQL, idea_id)
    await conn.fetchval(REFRESH_BATCH_STATUS_SQL, batch_id)
    return await load_batch(conn, batch_id)


async def fail_idea(
    conn,
    batch_id: UUID,
    ordinal: int,
    error: str,
    *,
    retryable: bool,
) -> dict[str, Any]:
    safe_error = " ".join(error.split())[:500] or "generation failed"
    row = await conn.fetchrow(FAIL_IDEA_SQL, batch_id, ordinal, safe_error, retryable)
    if row is None:
        raise ValueError("the batch was cancelled, replaced, or does not contain the idea")
    # One idea giving up is not the batch giving up. Let the same rule that
    # promotes a batch to 'ready' decide, so nine good ideas survive the tenth.
    await conn.fetchval(REFRESH_BATCH_STATUS_SQL, batch_id)
    return _row(row)


async def fail_batch(conn, batch_id: UUID) -> dict[str, Any]:
    failed = await conn.fetchval(FAIL_BATCH_SQL, batch_id)
    if failed is None:
        raise ValueError("the batch was cancelled, replaced, or unavailable")
    return {"batch_id": str(failed), "status": "failed"}


async def select_variant(
    conn, variant_id: UUID, owner_principal_id: str
) -> dict[str, Any]:
    row = await conn.fetchrow(FIND_SELECTABLE_SQL, variant_id, owner_principal_id)
    if row is None:
        raise ValueError("the variant is not ready or does not belong to this identity")
    await conn.execute(UNSELECT_IDEA_SQL, row["idea_id"])
    await conn.execute(SELECT_VARIANT_SQL, row["id"])
    # The idea's place and the hook's name ride back so the caller can speak
    # the choice into the conversation without a second read.
    return {
        "variant_id": str(row["id"]),
        "idea_id": str(row["idea_id"]),
        "idea_ordinal": int(row["ordinal"]),
        "idea_title": str(row["title"]),
        "hook_type": str(row["hook_type"]),
    }


async def patch_variant(
    conn,
    variant_id: UUID,
    owner_principal_id: str,
    value: IdeaVariant,
) -> dict[str, Any]:
    """Replace one ready draft variant after the complete patch validated."""

    row = await conn.fetchrow(
        FIND_PATCHABLE_VARIANT_SQL, variant_id, owner_principal_id
    )
    if row is None:
        raise ValueError("the variant is not ready or does not belong to this identity")
    if row["hook_type"] != value.hook_type:
        raise ValueError("a chat patch cannot change the variant hook type")
    # Whether a variant is a silent reel was decided by the batch's format, not
    # by the chat model. A rewrite may change every word; it may not grow a
    # script onto a silent reel or strip one off a carousel.
    if (row["script"] is None) != (value.script is None):
        raise ValueError("a chat patch cannot add or remove the script of a variant")
    await conn.execute(
        PATCH_VARIANT_SQL,
        variant_id,
        value.hook,
        value.script,
        value.caption,
        _json(value.hashtags),
        value.cta,
        value.source,
        _production(value),
    )
    await conn.execute(TOUCH_PATCH_IDEA_SQL, row["idea_id"])
    await conn.execute(TOUCH_PATCH_BATCH_SQL, row["batch_id"])
    return {
        "variant_id": str(variant_id),
        "idea_id": str(row["idea_id"]),
        "batch_id": str(row["batch_id"]),
    }


async def cancel_batch(
    conn, batch_id: UUID, owner_principal_id: str
) -> dict[str, Any]:
    cancelled = await conn.fetchval(CANCEL_BATCH_SQL, batch_id, owner_principal_id)
    if cancelled is None:
        raise ValueError("the current batch does not belong to this identity")
    await conn.execute(CANCEL_IDEAS_SQL, batch_id)
    await conn.execute(CANCEL_VARIANTS_SQL, batch_id)
    return {"batch_id": str(batch_id), "status": "cancelled"}


async def load_batch(conn, batch_id: UUID) -> dict[str, Any]:
    batch = await conn.fetchrow(GET_BATCH_SQL, batch_id)
    if batch is None:
        raise ValueError("generation batch not found")
    ideas = await conn.fetch(GET_IDEAS_SQL, batch_id)
    variants = await conn.fetch(GET_VARIANTS_SQL, batch_id)
    by_idea: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        item = _row(variant)
        by_idea.setdefault(str(item["idea_id"]), []).append(item)

    idea_items = []
    for idea in ideas:
        item = _row(idea)
        item["variants"] = by_idea.get(str(item["id"]), [])
        idea_items.append(item)
    result = _row(batch)
    result["ideas"] = idea_items
    return result


async def load_current_batch(conn, owner_principal_id: str) -> dict[str, Any] | None:
    batch = await conn.fetchrow(GET_CURRENT_BATCH_SQL, owner_principal_id)
    return None if batch is None else await load_batch(conn, batch["id"])


async def list_library(conn, client_slug: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(LIST_LIBRARY_SQL, client_slug)
    items = []
    for row in rows:
        value = _row(row)
        metadata = value.pop("metadata", {})
        items.append(
            {
                **value,
                "author": metadata.get("author"),
                "is_summary": bool(metadata.get("is_summary", False)),
            }
        )
    return items
