"""The cover sheet of a conversation: metadata, summary and closing time.

Full messages stay in the SDK's own tables and the exact trail stays in
``audit_log``. What is kept here is a factual summary, easy to read and to filter
on. The model is not called a second time: every value is derived from the audit.

The summary text itself is Romanian. It quotes the client's own last request and
is the human record of a Romanian conversation — English scaffolding around
Romanian quotes would read worse, not better.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

#: Bumped when the shape of `conversations.metadata` changes, so old rows stay
#: readable instead of silently meaning something else.
METADATA_VERSION = 2

STATS_SQL = """
SELECT count(*) FILTER (WHERE action = 'message_received')::int     AS messages_received,
       count(*) FILTER (WHERE action = 'message_sent')::int         AS messages_sent,
       count(*) FILTER (WHERE action = 'proposals_generated')::int  AS proposal_sets,
       count(*) FILTER (WHERE action = 'post_saved')::int           AS posts_saved,
       count(*) FILTER (WHERE action = 'profile_updated')::int      AS profile_updates,
       count(*) FILTER (WHERE action = 'skill_activated')::int      AS skills_activated,
       count(*) FILTER (WHERE action = 'capability_invoked')::int   AS tools_used,
       count(*) FILTER (WHERE action = 'guardrail_tripped')::int    AS errors,
       max(created_at)                                              AS last_activity,
       (SELECT payload->>'text'
          FROM audit_log
         WHERE conversation_id = $1 AND action = 'message_received'
         ORDER BY id DESC LIMIT 1)                                  AS last_request,
       (SELECT payload->>'title'
          FROM audit_log
         WHERE conversation_id = $1 AND action = 'post_saved'
         ORDER BY id DESC LIMIT 1)                                  AS last_post
  FROM audit_log
 WHERE conversation_id = $1
"""

UPDATE_SQL = """
UPDATE conversations
   SET summary = $2,
       metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb,
       ended_at = CASE
                    WHEN $4::bool THEN COALESCE(ended_at, $5::timestamptz, NOW())
                    ELSE ended_at
                  END
 WHERE session_id = $1
"""


def initial_metadata(model: str) -> dict[str, object]:
    """The values known the moment the worker starts."""
    return {
        "worker": "content-studio-fte",
        "model": model,
        "interface": "terminal",
        "status": "active",
        "metadata_version": METADATA_VERSION,
        "closure_estimated": False,
        "closure_reason": None,
    }


def _count(stats: Mapping[str, Any], key: str) -> int:
    return int(stats.get(key) or 0)


def _shorten(text: object, limit: int = 180) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def build_summary(stats: Mapping[str, Any]) -> str:
    """Build a factual summary; it does not interpret and does not invent."""
    received = _count(stats, "messages_received")
    sent = _count(stats, "messages_sent")

    if received == 0:
        return "Conversație fără mesaje."

    word_in = "mesaj" if received == 1 else "mesaje"
    word_out = "răspuns" if sent == 1 else "răspunsuri"
    parts = [f"{received} {word_in} de la Viorela și {sent} {word_out} de la worker."]

    unanswered = max(0, received - sent)
    if unanswered:
        shape = "mesaj a rămas" if unanswered == 1 else "mesaje au rămas"
        parts.append(f"{unanswered} {shape} fără răspuns.")

    proposals = _count(stats, "proposal_sets")
    if proposals:
        shape = "set de propuneri generat" if proposals == 1 else "seturi de propuneri generate"
        parts.append(f"{proposals} {shape}.")

    posts = _count(stats, "posts_saved")
    if posts:
        shape = "postare salvată" if posts == 1 else "postări salvate"
        last = _shorten(stats.get("last_post"), 100)
        detail = f", ultima: „{last}”" if last else ""
        parts.append(f"{posts} {shape}{detail}.")

    profile = _count(stats, "profile_updates")
    if profile:
        shape = "actualizare a profilului" if profile == 1 else "actualizări ale profilului"
        parts.append(f"{profile} {shape}.")

    errors = _count(stats, "errors")
    if errors:
        shape = "eroare înregistrată" if errors == 1 else "erori înregistrate"
        parts.append(f"{errors} {shape}.")

    last_request = _shorten(stats.get("last_request"))
    if last_request:
        parts.append(f"Ultima cerere: „{last_request}”.")

    return " ".join(parts)


def _metadata_from(
    stats: Mapping[str, Any],
    *,
    model: str | None,
    status: str,
    closure_estimated: bool,
    closure_reason: str | None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "worker": "content-studio-fte",
        "interface": "terminal",
        "status": status,
        "metadata_version": METADATA_VERSION,
        "messages_received": _count(stats, "messages_received"),
        "messages_sent": _count(stats, "messages_sent"),
        "proposal_sets": _count(stats, "proposal_sets"),
        "posts_saved": _count(stats, "posts_saved"),
        "profile_updates": _count(stats, "profile_updates"),
        "skills_activated": _count(stats, "skills_activated"),
        "tools_used": _count(stats, "tools_used"),
        "errors": _count(stats, "errors"),
        "closure_estimated": closure_estimated,
        "closure_reason": closure_reason,
    }
    if model:
        metadata["model"] = model

    last = stats.get("last_activity")
    if isinstance(last, datetime):
        metadata["last_activity"] = last.isoformat()

    return metadata


async def update_conversation(
    engine,
    session_id: str,
    *,
    model: str | None,
    status: str = "active",
    close: bool = False,
    closure_estimated: bool = False,
    closure_reason: str | None = None,
    closed_at: datetime | None = None,
) -> tuple[str, dict[str, object]]:
    """Update the cover sheet and return the summary and metadata written."""
    async with engine.begin() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        row = await raw.fetchrow(STATS_SQL, session_id)
        stats = dict(row) if row is not None else {}
        summary = build_summary(stats)
        metadata = _metadata_from(
            stats,
            model=model,
            status=status,
            closure_estimated=closure_estimated,
            closure_reason=closure_reason,
        )
        if close and closed_at is None:
            closed_at = datetime.now(UTC)
        await raw.execute(
            UPDATE_SQL,
            session_id,
            summary,
            json.dumps(metadata, ensure_ascii=False),
            close,
            closed_at,
        )
    return summary, metadata
