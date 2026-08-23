"""Which client row a signed-in principal owns.

Kept out of `server.py` because it is the one piece of data that decides what
every other query in that file is allowed to see, and it should be readable on
its own.

Rule 1 of AGENTS.md still holds: this module runs inside the MCP server, which
is the only place allowed to touch the database. The harness asks for the answer
through `ui_resolve_account`; it does not query for it.
"""

from __future__ import annotations

import re
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


# Driven by `clients`, not by `app_users`, because the account *is* the client
# row: it owns the profile, the library and the allowance. Listing sign-ins
# instead would hide any client nobody has signed in as yet - including the one
# the studio was built for, whose budget would then be unreachable from the only
# page that can change it.
LIST_ACCOUNTS_SQL = """
SELECT c.slug          AS client_slug,
       c.name          AS client_name,
       c.created_at    AS client_created_at,
       u.principal_id,
       u.email,
       u.provider,
       u.role,
       u.disabled_at,
       u.created_at
  FROM public.clients c
  LEFT JOIN public.app_users u ON u.client_id = c.id
 ORDER BY c.created_at, u.created_at
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


# Revoking access is a timestamp, not a DELETE. The usage rows reference the
# client, the audit trail references the runs, and a deleted principal would take
# the meaning out of both. `resolve_account` already treats a stamped row as
# nobody, so setting this is the whole revocation.
SET_DISABLED_SQL = """
UPDATE public.app_users
   SET disabled_at = CASE WHEN $2 THEN NOW() ELSE NULL END
 WHERE principal_id = $1
RETURNING principal_id, disabled_at
"""


async def set_disabled(conn: Any, principal_id: str, disabled: bool) -> dict[str, Any] | None:
    row = await conn.fetchrow(SET_DISABLED_SQL, principal_id, disabled)
    if row is None:
        return None
    return {
        "principal_id": row["principal_id"],
        "disabled": row["disabled_at"] is not None,
    }


async def list_accounts(conn: Any) -> list[dict[str, Any]]:
    rows = await conn.fetch(LIST_ACCOUNTS_SQL)
    return [
        {
            # None where nobody has signed in as this client yet. The interface
            # says so rather than pretending the row is broken: a client with no
            # principal is a normal state, not a half-made account.
            "principal_id": row["principal_id"],
            "email": row["email"],
            "provider": row["provider"],
            "role": row["role"] or "user",
            "client_slug": row["client_slug"],
            "client_name": row["client_name"],
            "disabled": row["disabled_at"] is not None,
            "created_at": (row["created_at"] or row["client_created_at"]).isoformat(),
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


# ── Self-provisioning ────────────────────────────────────────────────────────
#
# A principal from a provider only Sorin can add people to arrives with no row
# anywhere, and gets a studio written for it on the spot. See
# AUTH_SELF_PROVISION_PROVIDERS in config.py for why that is safe there and
# nowhere else.
#
# WHY NOT `create_account` ABOVE. Its CREATE_CLIENT_SQL ends in
# `ON CONFLICT (slug) DO UPDATE`, which is right when a human typed the slug and
# means to correct a row - and catastrophic when the slug is derived from an
# address. Two people whose mail happens to start the same way would land on one
# client, sharing a profile, a library and an allowance. Here the slug must be
# *free*, so the insert claims it or moves on to the next candidate.

# `DO NOTHING` rather than `DO UPDATE`: a returned id means this call created the
# row, and no row means the slug belongs to somebody else and the caller must try
# another. That is the whole race protection, and Postgres does it, not us.
CLAIM_CLIENT_SQL = """
INSERT INTO public.clients (slug, name, profile_md)
VALUES ($1, $2, '')
ON CONFLICT (slug) DO NOTHING
RETURNING id
"""

# Two requests from the same brand-new principal arrive together on the first
# page load - the shell asks /api/me and /api/me/usage at once. Serialising on
# the principal turns that into one provisioning and one no-op read, instead of
# two clients of which one is immediately orphaned. Transaction-scoped, so it is
# released by the COMMIT whatever happens.
LOCK_PRINCIPAL_SQL = "SELECT pg_advisory_xact_lock(hashtext($1))"

# Existence, not resolvability. `resolve_account` answers None for a *suspended*
# row as well as a missing one, and provisioning on that answer would hand a
# revoked tester a brand new studio on their next request - and leave an orphan
# client behind on every one after that. Suspension is how a tester is revoked,
# so it has to survive this path.
USER_EXISTS_SQL = "SELECT 1 FROM public.app_users WHERE principal_id = $1"

# `DO NOTHING` again, for the same reason: if the principal was provisioned
# between the check and here, the existing row stands and this call is inert.
CLAIM_USER_SQL = """
INSERT INTO public.app_users (principal_id, email, provider, client_id, role)
VALUES ($1, $2, $3, $4, 'user')
ON CONFLICT (principal_id) DO NOTHING
"""

# Binding to a studio that already exists, rather than claiming a fresh one.
# The one caller is the owner path: the client the studio predates accounts for
# has had a `clients` row since before `app_users` existed, and what is missing
# is only the principal that points at it.
CLIENT_ID_BY_SLUG_SQL = "SELECT id FROM public.clients WHERE slug = $1"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slug_from_label(label: str) -> str:
    """A readable client slug from a name or an address, matching the column.

    Takes either, because the platform gives either: an address from Google, a
    display name from the external tenant. Anything before an "@" is used, which
    leaves a name untouched and reduces an address to its local part.

    Readability is the whole point - Sorin reads these on the admin page - so it
    is not a hash. It is a *starting* candidate: the caller has to handle the
    slug being taken, because two labels can easily reduce to one and neither
    owns it.
    """
    local = label.split("@", 1)[0].lower()
    slug = _SLUG_STRIP.sub("-", local).strip("-")[:40].strip("-")
    # The column demands it start with a letter or digit, and an address like
    # `"..."@example.com` can reduce to nothing at all.
    return slug if slug and slug[0].isalnum() else f"cont{('-' + slug) if slug else ''}"


async def provision_self(
    conn: Any,
    *,
    principal_id: str,
    email: str,
    provider: str,
    display_name: str = "",
    client_slug: str | None = None,
) -> tuple[Account | None, bool]:
    """Give a first-time principal its own empty studio. Idempotent.

    Returns the account and whether this call is what created it. The flag exists
    so the caller writes one audit row for the provisioning and none for the many
    later requests that find the work already done.

    The account is None when the principal already has a row that does not
    resolve - which means suspended, and must stay that way.

    Always role `user` and always the column's default allowance, neither of them
    a parameter: this runs unattended, on nothing but the fact that somebody
    signed in, so the two values that decide power and money are not things a
    caller can raise. An admin is still made only by `db/provision.py`.

    The library starts empty because the books are licensed material; copying
    somebody's shelf onto a new account is a decision, not a default.

    `client_slug` binds the principal to a studio that already exists instead of
    claiming a new one. Raising when that slug is unknown is deliberate: the
    caller passes a configured name, so a miss means the deployment is wrong, and
    inventing a client to paper over it would put the person somewhere nobody
    meant them to be.
    """
    await conn.execute(LOCK_PRINCIPAL_SQL, principal_id)

    if await conn.fetchval(USER_EXISTS_SQL, principal_id) is not None:
        # Provisioned already, or provisioned and then suspended. Either way this
        # call writes nothing; `resolve_account` tells the two apart for us.
        return await resolve_account(conn, principal_id), False

    # The label Sorin reads on the admin page. He typed it when he created the
    # person, so it beats an address split at the "@" - and it is the only thing
    # some providers report, which is why it is preferred for the slug too.
    label = (display_name or "").strip() or email

    if client_slug:
        client_id = await conn.fetchval(CLIENT_ID_BY_SLUG_SQL, client_slug)
        if client_id is None:
            raise LookupError(f"no client with slug {client_slug!r}")
        await conn.execute(CLAIM_USER_SQL, principal_id, email, provider, client_id)
        account = await resolve_account(conn, principal_id)
        if account is None:
            raise RuntimeError(f"provisioning {principal_id!r} left no account behind")
        return account, True

    base = slug_from_label(label)
    client_id = None
    slug = base
    # Bounded: after a few collisions the address is unusual enough that a
    # readable slug is not worth more round trips, and the principal is unique.
    for attempt in range(1, 12):
        slug = base if attempt == 1 else f"{base}-{attempt}"
        client_id = await conn.fetchval(CLAIM_CLIENT_SQL, slug, label)
        if client_id is not None:
            break
    if client_id is None:
        slug = f"{base}-{abs(hash(principal_id)) % 1_000_000:06d}"
        client_id = await conn.fetchval(CLAIM_CLIENT_SQL, slug, label)
    if client_id is None:
        raise RuntimeError(f"could not claim a client slug for {principal_id!r}")

    await conn.execute(CLAIM_USER_SQL, principal_id, email, provider, client_id)

    # Read back rather than construct: the row that ends up in the database is
    # the truth, and it is what the rest of the request will be scoped by.
    account = await resolve_account(conn, principal_id)
    if account is None:
        raise RuntimeError(f"provisioning {principal_id!r} left no account behind")
    return account, True
