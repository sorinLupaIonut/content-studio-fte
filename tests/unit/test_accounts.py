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
