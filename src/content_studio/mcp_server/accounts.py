"""Which client row a signed-in principal owns.

Kept out of `server.py` because it is the one piece of data that decides what
every other query in that file is allowed to see, and it should be readable on
its own.

Rule 1 of AGENTS.md still holds: this module runs inside the MCP server, which
is the only place allowed to touch the database. The harness asks for the answer
through `ui_resolve_account`; it does not query for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RESOLVE_SQL = """
SELECT u.principal_id,
       u.email,
       u.role,
       u.disabled_at IS NOT NULL AS disabled,
       c.slug        AS client_slug,
       c.name        AS client_name
  FROM public.app_users u
  JOIN public.clients   c ON c.id = u.client_id
 WHERE u.principal_id = $1
"""


@dataclass(frozen=True, slots=True)
class Account:
    principal_id: str
    email: str
    role: str
    client_slug: str
    client_name: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def as_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "email": self.email,
            "role": self.role,
            "client_slug": self.client_slug,
            "client_name": self.client_name,
        }


async def resolve_account(conn: Any, principal_id: str) -> Account | None:
    """The account behind one principal, or None if it has none.

    A disabled row resolves to None rather than raising. The caller's fallback is
    the default client, which is the same place an unknown principal lands, so a
    disabled user never quietly inherits somebody else's data - they are simply
    not provisioned. Refusing access is the allowlist's job, upstream of here.
    """
    row = await conn.fetchrow(RESOLVE_SQL, principal_id)
    if row is None or row["disabled"]:
        return None
    return Account(
        principal_id=row["principal_id"],
        email=row["email"],
        role=row["role"],
        client_slug=row["client_slug"],
        client_name=row["client_name"],
    )


LIST_ACCOUNTS_SQL = """
SELECT u.principal_id,
       u.email,
       u.provider,
       u.role,
       u.disabled_at,
       u.created_at,
       c.slug AS client_slug,
       c.name AS client_name
  FROM public.app_users u
  JOIN public.clients   c ON c.id = u.client_id
 ORDER BY u.created_at
"""

# A new tester needs a client row before an app_users row can point at it, and
# `profile_from` decides what that row starts with. The COALESCE gives an empty
# profile when no source is named, and the sub-select copies the text - a copy,
# never a shared reference, so one tester editing a profile can never change
# what another tester's agent writes.
CREATE_CLIENT_SQL = """
INSERT INTO public.clients (slug, name, profile_md, budget_micros)
VALUES ($1, $2, COALESCE((SELECT profile_md FROM public.clients WHERE slug = $3), ''), $4)
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

CREATE_USER_SQL = """
INSERT INTO public.app_users (principal_id, email, provider, client_id, role)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (principal_id) DO UPDATE
    SET email = EXCLUDED.email,
        provider = EXCLUDED.provider,
        client_id = EXCLUDED.client_id,
        role = EXCLUDED.role,
        disabled_at = NULL
RETURNING principal_id
"""


async def list_accounts(conn: Any) -> list[dict[str, Any]]:
    rows = await conn.fetch(LIST_ACCOUNTS_SQL)
    return [
        {
            "principal_id": row["principal_id"],
            "email": row["email"],
            "provider": row["provider"],
            "role": row["role"],
            "client_slug": row["client_slug"],
            "client_name": row["client_name"],
            "disabled": row["disabled_at"] is not None,
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


async def create_account(
    conn: Any,
    *,
    principal_id: str,
    email: str,
    client_slug: str,
    client_name: str,
    provider: str = "google",
    role: str = "user",
    profile_from: str | None = None,
    budget_micros: int = 1_000_000,
) -> Account:
    """Provision one tester: a client row, then the principal that points at it.

    Both statements share the caller's transaction, so a half-created account -
    a client with nobody able to reach it, or worse a principal pointing at
    nothing - cannot survive a failure between them.
    """
    client_id = await conn.fetchval(
        CREATE_CLIENT_SQL, client_slug, client_name, profile_from, max(0, int(budget_micros))
    )
    await conn.execute(CREATE_USER_SQL, principal_id, email, provider, client_id, role)
    return Account(
        principal_id=principal_id,
        email=email,
        role=role,
        client_slug=client_slug,
        client_name=client_name,
    )
