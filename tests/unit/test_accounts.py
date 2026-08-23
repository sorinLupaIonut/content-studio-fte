"""Which client a request is allowed to see.

The important assertions here are the negative ones: that the model cannot name
a client, and that a connection which says nothing still gets the configured
default — that fallback is what lets this land without breaking the CLI.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import patch

from content_studio.config import CLIENT_SLUG
from content_studio.mcp_server import server as srv
from content_studio.mcp_server.accounts import Account, resolve_account
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    INTERNAL_UI_TOOLS,
    MODEL_VISIBLE_TOOLS,
    OWNER_HEADER,
    PROFILE_URI,
    profile_uri,
)

VIORELA_ROW = {
    "principal_id": "principal-viorela",
    "email": "viorela@example.com",
    "role": "user",
    "disabled": False,
    "client_slug": "viorela",
    "client_name": "Viorela",
}


class FakeConn:
    """Just enough asyncpg to answer one fetchrow."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.calls: list[tuple[Any, ...]] = []

    async def fetchrow(self, _sql: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append(args)
        return self.row


class FakeHeaders:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str | None:
        return self.values.get(name)


class FakeContext:
    """The shape `_header` reaches through: ctx.request_context.request.headers."""

    def __init__(self, headers: dict[str, str]) -> None:
        request = type("Request", (), {"headers": FakeHeaders(headers)})()
        self.request_context = type("RequestContext", (), {"request": request})()


class ResolveAccountTests(unittest.TestCase):
    def test_maps_the_joined_row_onto_an_account(self) -> None:
        conn = FakeConn(VIORELA_ROW)
        account = asyncio.run(resolve_account(conn, "principal-viorela"))
        self.assertEqual(
            account,
            Account(
                principal_id="principal-viorela",
                email="viorela@example.com",
                role="user",
                client_slug="viorela",
                client_name="Viorela",
            ),
        )
        self.assertEqual(conn.calls, [("principal-viorela",)])

    def test_unknown_principal_resolves_to_none(self) -> None:
        self.assertIsNone(asyncio.run(resolve_account(FakeConn(None), "nobody")))

    def test_disabled_row_resolves_to_none(self) -> None:
        # Not an exception: the caller falls back to the default client, which is
        # where an unprovisioned principal lands too. Refusing access is the
        # allowlist's job, upstream of here.
        row = {**VIORELA_ROW, "disabled": True}
        self.assertIsNone(asyncio.run(resolve_account(FakeConn(row), "principal-viorela")))

    def test_is_admin_reads_the_role(self) -> None:
        account = asyncio.run(resolve_account(FakeConn({**VIORELA_ROW, "role": "admin"}), "p"))
        assert account is not None
        self.assertTrue(account.is_admin)
        self.assertFalse(
            asyncio.run(resolve_account(FakeConn(VIORELA_ROW), "p")).is_admin  # type: ignore[union-attr]
        )


class ClientOfTests(unittest.TestCase):
    """The three sources, in the order `client_of` consults them."""

    def test_header_wins_without_touching_the_database(self) -> None:
        ctx = FakeContext({CLIENT_HEADER: "sorin", OWNER_HEADER: "principal-viorela"})
        with patch.object(srv, "connection") as connection:
            slug = asyncio.run(srv.client_of(ctx))
        self.assertEqual(slug, "sorin")
        connection.assert_not_called()

    def test_principal_is_looked_up_when_the_client_is_not_given(self) -> None:
        ctx = FakeContext({OWNER_HEADER: "principal-viorela"})
        with patch.object(srv, "resolve_account", return_value=_account("altcineva")):
            with patch.object(srv, "connection", _fake_connection()):
                slug = asyncio.run(srv.client_of(ctx))
        self.assertEqual(slug, "altcineva")

    def test_bare_connection_gets_the_configured_default(self) -> None:
        # This is the CLI, and every test written before app_users existed.
        with patch.object(srv, "connection") as connection:
            slug = asyncio.run(srv.client_of(FakeContext({})))
        self.assertEqual(slug, CLIENT_SLUG)
        connection.assert_not_called()

    def test_unprovisioned_principal_falls_back_rather_than_failing(self) -> None:
        ctx = FakeContext({OWNER_HEADER: "somebody-new"})
        with patch.object(srv, "resolve_account", return_value=None):
            with patch.object(srv, "connection", _fake_connection()):
                slug = asyncio.run(srv.client_of(ctx))
        self.assertEqual(slug, CLIENT_SLUG)


class ContractTests(unittest.TestCase):
    def test_the_model_is_never_shown_a_client_parameter(self) -> None:
        # The whole point of routing the client through the connection: a client
        # the model can name is a client the model can get wrong.
        forbidden = {"ctx", "client_slug", "client_id", "principal_id"}
        for tool in asyncio.run(srv.server.list_tools()):
            if tool.name not in MODEL_VISIBLE_TOOLS:
                continue
            properties = set((tool.input_schema or {}).get("properties", {}))
            self.assertEqual(properties & forbidden, set(), tool.name)

    def test_resolve_account_is_internal_only(self) -> None:
        self.assertIn("ui_resolve_account", INTERNAL_UI_TOOLS)
        self.assertNotIn("ui_resolve_account", MODEL_VISIBLE_TOOLS)

    def test_profile_uri_still_defaults_to_the_configured_client(self) -> None:
        self.assertEqual(PROFILE_URI, profile_uri(CLIENT_SLUG))

    def test_the_profile_resource_is_registered_as_a_template(self) -> None:
        templates = [
            str(template.uri_template)
            for template in asyncio.run(srv.server.list_resource_templates())
        ]
        self.assertIn(profile_uri("{slug}"), templates)


def _account(slug: str) -> Account:
    return Account(
        principal_id="p",
        email="p@example.com",
        role="user",
        client_slug=slug,
        client_name=slug.title(),
    )


def _fake_connection():
    class _Ctx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> bool:
            return False

    return lambda: _Ctx()


if __name__ == "__main__":
    unittest.main()


class OwnerFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Only the client the studio predates accounts for may fall through."""

    class _Directory:
        """The two answers that matter, plus the one that means 'I cannot tell'."""

        def __init__(self, outcome):
            self.outcome = outcome

        async def account_for(self, principal_id):
            if self.outcome == "outage":
                raise RuntimeError("data plane unreachable")
            return object() if self.outcome == "provisioned" else None

    async def test_provisioned_is_true(self):
        from content_studio.harness.accounts import AccountDirectory

        directory = AccountDirectory.__new__(AccountDirectory)
        directory.account_for = self._Directory("provisioned").account_for
        self.assertIs(await directory.provisioned("p"), True)

    async def test_unprovisioned_is_false(self):
        from content_studio.harness.accounts import AccountDirectory

        directory = AccountDirectory.__new__(AccountDirectory)
        directory.account_for = self._Directory("missing").account_for
        self.assertIs(await directory.provisioned("p"), False)

    async def test_an_outage_is_neither(self):
        """False locks somebody out; None must not, or one bad minute does."""
        from content_studio.harness.accounts import AccountDirectory

        directory = AccountDirectory.__new__(AccountDirectory)
        directory.account_for = self._Directory("outage").account_for
        self.assertIsNone(await directory.provisioned("p"))


class FakeProvisionConn:
    """Enough asyncpg to run `provision_self` against an in-memory directory.

    Models the two things the real statements promise and the code leans on:
    `ON CONFLICT (slug) DO NOTHING` returns no id when the slug is taken, and a
    suspended principal still has a row even though it resolves to nobody.
    """

    def __init__(
        self,
        *,
        taken_slugs: set[str] | None = None,
        existing_principal: str | None = None,
        disabled: bool = False,
    ) -> None:
        self.clients: dict[str, str] = {slug: f"id-{slug}" for slug in (taken_slugs or set())}
        # RESOLVE_SQL reads the label off `clients`, not off `app_users`. The fake
        # has to do the same or it cannot show a wrong name being written.
        self.client_names: dict[str, str] = {slug: slug for slug in self.clients}
        self.users: dict[str, dict[str, Any]] = {}
        self.disabled = disabled
        if existing_principal:
            self.clients.setdefault("existing", "id-existing")
            self.client_names.setdefault("existing", "Before")
            self.users[existing_principal] = {
                "principal_id": existing_principal,
                "email": "before@studio.invalid",
                "role": "user",
                "disabled": disabled,
                "client_slug": "existing",
                "client_name": "Before",
            }
        self.locked: list[str] = []

    async def execute(self, sql: str, *args: Any) -> None:
        if "pg_advisory_xact_lock" in sql:
            self.locked.append(args[0])
        elif "INSERT INTO public.app_users" in sql:
            principal, email, provider, client_id = args
            if principal in self.users:
                return  # ON CONFLICT DO NOTHING
            slug = next(s for s, i in self.clients.items() if i == client_id)
            self.users[principal] = {
                "principal_id": principal,
                "email": email,
                "role": "user",
                "disabled": False,
                "client_slug": slug,
                "client_name": self.client_names[slug],
            }

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "pg_advisory_xact_lock" in sql:
            self.locked.append(args[0])
            return None
        if "FROM public.app_users" in sql:
            return 1 if args[0] in self.users else None
        if "SELECT id FROM public.clients" in sql:
            return self.clients.get(args[0])
        if "INSERT INTO public.clients" in sql:
            slug, name = args[0], args[1]
            if slug in self.clients:
                return None  # ON CONFLICT DO NOTHING
            self.clients[slug] = f"id-{slug}"
            self.client_names[slug] = name
            return self.clients[slug]
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def fetchrow(self, _sql: str, *args: Any) -> dict[str, Any] | None:
        return self.users.get(args[0])


class TestSlugFromLabel(unittest.TestCase):
    def test_the_local_part_becomes_the_slug(self) -> None:
        from content_studio.mcp_server.accounts import slug_from_label

        self.assertEqual(slug_from_label("Ana.Maria+test@example.com"), "ana-maria-test")

    def test_it_matches_the_column_pattern(self) -> None:
        """`^[a-z0-9][a-z0-9-]*$` - an address can reduce to nothing usable."""
        from content_studio.mcp_server.accounts import slug_from_label

        for address in ("--weird--@example.com", "@example.com", "___@example.com"):
            with self.subTest(address=address):
                slug = slug_from_label(address)
                self.assertRegex(slug, r"^[a-z0-9][a-z0-9-]*$")


class TestProvisionIntoAnExistingClient(unittest.IsolatedAsyncioTestCase):
    """The owner path: a studio that predates `app_users` gets its principal."""

    async def test_the_principal_joins_the_named_client(self) -> None:
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn(taken_slugs={"viorela"})
        account, created = await provision_self(
            conn,
            principal_id="principal-owner",
            email="owner@example.com",
            provider="google",
            display_name="Viorela",
            client_slug="viorela",
        )

        self.assertTrue(created)
        self.assertIsNotNone(account)
        self.assertEqual(account.client_slug, "viorela")
        # The point of passing a slug is that no second studio appears.
        self.assertEqual(set(conn.clients), {"viorela"})

    async def test_an_unknown_slug_raises_rather_than_inventing_one(self) -> None:
        """A configured name that misses means the deployment is wrong.

        Claiming a fresh client here would put the owner in an empty studio that
        looks like hers and is not, which is worse than an error page.
        """
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn()
        with self.assertRaises(LookupError):
            await provision_self(
                conn,
                principal_id="principal-owner",
                email="owner@example.com",
                provider="google",
                client_slug="viorela",
            )
        self.assertEqual(conn.users, {})

    async def test_a_suspended_owner_stays_suspended(self) -> None:
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn(existing_principal="principal-owner", disabled=True)
        account, created = await provision_self(
            conn,
            principal_id="principal-owner",
            email="owner@example.com",
            provider="google",
            client_slug="existing",
        )

        self.assertIsNone(account)
        self.assertFalse(created)


class TestProvisionSelf(unittest.IsolatedAsyncioTestCase):
    async def test_a_first_time_principal_gets_its_own_client(self) -> None:
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn()
        account, created = await provision_self(
            conn, principal_id="p-1", email="tester@studio.invalid", provider="entra"
        )
        self.assertTrue(created)
        assert account is not None
        self.assertEqual(account.client_slug, "tester")
        self.assertEqual(account.role, "user")
        self.assertEqual(conn.locked, ["p-1"])

    async def test_a_taken_slug_is_never_hijacked(self) -> None:
        """The failure this guards is two people sharing one profile and budget."""
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn(taken_slugs={"tester"})
        account, _ = await provision_self(
            conn, principal_id="p-2", email="tester@studio.invalid", provider="entra"
        )
        assert account is not None
        self.assertEqual(account.client_slug, "tester-2")
        self.assertEqual(conn.clients["tester"], "id-tester")

    async def test_a_second_call_creates_nothing(self) -> None:
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn()
        await provision_self(
            conn, principal_id="p-3", email="tester@studio.invalid", provider="entra"
        )
        before = dict(conn.clients)
        account, created = await provision_self(
            conn, principal_id="p-3", email="tester@studio.invalid", provider="entra"
        )
        self.assertFalse(created)
        assert account is not None
        self.assertEqual(conn.clients, before)

    async def test_a_suspended_principal_is_not_given_a_new_studio(self) -> None:
        """Suspension is how a tester is revoked; provisioning must not undo it."""
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn(existing_principal="p-4", disabled=True)
        account, created = await provision_self(
            conn, principal_id="p-4", email="tester@studio.invalid", provider="entra"
        )
        self.assertIsNone(account)
        self.assertFalse(created)
        self.assertEqual(set(conn.clients), {"existing"})


class TestDisplayNameWins(unittest.IsolatedAsyncioTestCase):
    """The platform gives a name for some providers and an address for others."""

    async def test_the_display_name_becomes_the_slug_and_the_label(self) -> None:
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn()
        account, _ = await provision_self(
            conn,
            principal_id="p-5",
            email="ana.pop@studioviorela.ro",
            provider="entra",
            display_name="Ana Pop",
        )
        assert account is not None
        self.assertEqual(account.client_slug, "ana-pop")
        self.assertEqual(account.client_name, "Ana Pop")
        # The address still lands in the column that is named after it.
        self.assertEqual(conn.users["p-5"]["email"], "ana.pop@studioviorela.ro")

    async def test_without_one_the_address_is_used(self) -> None:
        from content_studio.mcp_server.accounts import provision_self

        conn = FakeProvisionConn()
        account, _ = await provision_self(
            conn, principal_id="p-6", email="ana.pop@studioviorela.ro", provider="entra"
        )
        assert account is not None
        self.assertEqual(account.client_slug, "ana-pop")
