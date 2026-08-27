"""Typed persistence for the studio's one-conversation-per-lot rule.

The row here is a pointer, not a transcript: messages live in the SDK's own
`agent_sessions` / `agent_messages`, keyed by `session_id`. What this table
answers is the question those tables cannot: which session is the ACTIVE
conversation of an account, and which generation batch was born in it.

The lifecycle rule (2026-08-27): one conversation carries at most one lot.
Starting a new lot archives the conversation, marks the old batch replaced so
it leaves the interface, and begins a fresh session. Saved posts are untouched
by any of this — they live in `posts`, permanently.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from uuid import UUID

CLIENT_ID_SQL = "SELECT id FROM public.clients WHERE slug = $1"

ACTIVE_SQL = """
SELECT * FROM public.conversations
 WHERE owner_principal_id = $1 AND status = 'active'
"""

INSERT_SQL = """
INSERT INTO public.conversations (client_id, owner_principal_id, session_id)
VALUES ($1, $2, $3)
RETURNING *
"""

ARCHIVE_SQL = """
UPDATE public.conversations
   SET status = 'archived', updated_at = now()
 WHERE owner_principal_id = $1 AND status = 'active'
"""

#: The old lot leaves the interface when its conversation is archived. Same
#: two-column change `create_batch` makes when a batch is explicitly replaced,
#: so every reader of `is_current` keeps one meaning.
RETIRE_CURRENT_BATCH_SQL = """
UPDATE public.generation_batches
   SET status = 'replaced', is_current = false, updated_at = now()
 WHERE owner_principal_id = $1 AND is_current
"""

BIND_SQL = """
UPDATE public.conversations
   SET batch_id = $2, updated_at = now()
 WHERE owner_principal_id = $1 AND status = 'active'
RETURNING *
"""


def _value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row(row: Any) -> dict[str, Any]:
    return {key: _value(row[key]) for key in row.keys()}


def new_conversation_session_id() -> str:
    """A fresh session id, valid for HTTP headers and the SDK's session table."""

    return f"conv-{uuid.uuid4().hex}"


async def _client_id(conn, client_slug: str) -> Any:
    client_id = await conn.fetchval(CLIENT_ID_SQL, client_slug)
    if client_id is None:
        raise ValueError(f"There is no client {client_slug!r} in public.clients.")
    return client_id


def _owner(owner_principal_id: str) -> str:
    owner = owner_principal_id.strip()
    if not owner or len(owner) > 500:
        raise ValueError("owner_principal_id is missing or too long")
    return owner


async def current_conversation(
    conn, *, client_slug: str, owner_principal_id: str
) -> tuple[dict[str, Any], bool]:
    """The active conversation, created on first ask. Returns (row, created)."""

    owner = _owner(owner_principal_id)
    row = await conn.fetchrow(ACTIVE_SQL, owner)
    if row is not None:
        return _row(row), False
    client_id = await _client_id(conn, client_slug)
    row = await conn.fetchrow(
        INSERT_SQL, client_id, owner, new_conversation_session_id()
    )
    return _row(row), True


async def new_conversation(
    conn, *, client_slug: str, owner_principal_id: str
) -> dict[str, Any]:
    """Archive the active conversation and begin a fresh one.

    The old batch is retired in the same transaction: the conversation and its
    lot leave the interface together, or not at all.
    """

    owner = _owner(owner_principal_id)
    client_id = await _client_id(conn, client_slug)
    await conn.execute(ARCHIVE_SQL, owner)
    await conn.execute(RETIRE_CURRENT_BATCH_SQL, owner)
    row = await conn.fetchrow(
        INSERT_SQL, client_id, owner, new_conversation_session_id()
    )
    return _row(row)


async def bind_conversation_batch(
    conn, *, owner_principal_id: str, batch_id: UUID
) -> dict[str, Any]:
    """Record which batch was born in the active conversation."""

    owner = _owner(owner_principal_id)
    row = await conn.fetchrow(BIND_SQL, owner, batch_id)
    if row is None:
        raise ValueError("the account has no active conversation to bind to")
    return _row(row)
