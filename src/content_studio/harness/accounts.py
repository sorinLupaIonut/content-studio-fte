"""Who is asking, what they are allowed to spend, and what they have spent.

Three things live here because they are the same question asked at three moments:
before a run (may this start?), during a request (whose data is this?), and after
a call returns (what did it cost?).

WHY CONTEXTVARS. The client has to reach `_data_mcp`, which is called from twenty
places across the service and both coordinators, none of which have any business
knowing about accounts. A ContextVar is per-task and is copied into tasks spawned
from it, which is exactly the shape of one HTTP request and the background work
it starts - so the value follows the request without twenty signatures growing a
parameter they would only pass along.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agents.mcp import MCPServerStreamableHttp

from content_studio.config import CLIENT_SLUG
from content_studio.harness.drafts import tool_payload
from content_studio.pricing import cost_micros, percent_used

#: The client whose data the current request may touch, and the principal that
#: asked. Both default to None, which is what every existing caller gets: the
#: connection then carries no client header and the MCP server falls back to
#: `CLIENT_SLUG`, exactly as before any of this existed.
CURRENT_CLIENT: ContextVar[str | None] = ContextVar("current_client", default=None)
CURRENT_PRINCIPAL: ContextVar[str | None] = ContextVar("current_principal", default=None)


class BudgetExhausted(RuntimeError):
    """Raised instead of starting a run that the account cannot pay for."""

    def __init__(self, client_slug: str) -> None:
        self.client_slug = client_slug
        super().__init__(f"budget exhausted for {client_slug!r}")


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


@dataclass(frozen=True, slots=True)
class Budget:
    client_slug: str
    client_name: str
    budget_micros: int
    spent_micros: int
    events: int

    @property
    def exhausted(self) -> bool:
        return self.spent_micros >= self.budget_micros

    @property
    def percent(self) -> int:
        return percent_used(self.spent_micros, self.budget_micros)


class AccountDirectory:
    """Accounts and budgets, read through the MCP server rather than by SQL."""

    def __init__(
        self,
        internal_factory: Callable[[str], MCPServerStreamableHttp],
        ttl_seconds: float = 60.0,
    ) -> None:
        self._internal_factory = internal_factory
        self._ttl = ttl_seconds
        # Accounts change when Sorin provisions somebody, which is rare, so a
        # short TTL removes a round trip from every request at the cost of a
        # minute's staleness on a change he just made himself. Budgets are NOT
        # cached: the gate has to see the spend that the previous call recorded.
        self._accounts: dict[str, tuple[float, Account | None]] = {}

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        server = self._internal_factory("accounts")
        try:
            await server.connect()
            return tool_payload(await server.call_tool(name, arguments))
        finally:
            await server.cleanup()

    # ---- who -----------------------------------------------------------------

    async def account_for(self, principal_id: str | None) -> Account | None:
        if not principal_id:
            return None
        cached = self._accounts.get(principal_id)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]

        payload = await self._call("ui_resolve_account", {"principal_id": principal_id})
        raw = (payload or {}).get("account")
        account = (
            Account(
                principal_id=raw["principal_id"],
                email=raw["email"],
                role=raw["role"],
                client_slug=raw["client_slug"],
                client_name=raw["client_name"],
            )
            if raw
            else None
        )
        self._accounts[principal_id] = (now, account)
        return account

    def forget(self, principal_id: str | None = None) -> None:
        """Drop the cache after provisioning, so a new account works immediately."""
        if principal_id is None:
            self._accounts.clear()
        else:
            self._accounts.pop(principal_id, None)

    async def bind(self, principal_id: str | None) -> str:
        """Resolve the principal and pin the answer to this request's context.

        An unprovisioned principal binds to `CLIENT_SLUG`. That is the same place
        the CLI lands, and it is what keeps this whole change inert until
        `app_users` has rows in it.
        """
        try:
            account = await self.account_for(principal_id)
        except Exception:  # noqa: BLE001
            # The data server being unreachable already breaks the request that
            # needs data. It must not additionally break the ones that do not -
            # /api/me and the UI shell answered fine before accounts existed,
            # and they still should.
            account = None
        slug = account.client_slug if account is not None else CLIENT_SLUG
        CURRENT_CLIENT.set(slug)
        CURRENT_PRINCIPAL.set(principal_id)
        return slug

    async def provisioned(self, principal_id: str | None) -> bool | None:
        """True, False, or None when the answer could not be obtained.

        Three states rather than two on purpose. A caller that refuses on False
        must not also refuse when the data plane is briefly unreachable - that
        would turn one server's bad minute into everybody being locked out of
        their own studio.
        """
        try:
            return await self.account_for(principal_id) is not None
        except Exception:  # noqa: BLE001
            return None

    # ---- how much ------------------------------------------------------------

    async def budget_for(self, client_slug: str | None = None) -> Budget | None:
        slug = client_slug or CURRENT_CLIENT.get() or CLIENT_SLUG
        payload = await self._call("ui_get_budget", {"client_slug": slug})
        raw = (payload or {}).get("budget")
        if not raw:
            return None
        return Budget(
            client_slug=raw["client_slug"],
            client_name=raw["client_name"],
            budget_micros=int(raw["budget_micros"]),
            spent_micros=int(raw["spent_micros"]),
            events=int(raw["events"]),
        )

    async def require_budget(self, client_slug: str | None = None) -> None:
        """Refuse to start a run for an account that is already at its limit.

        A STOP-GATE, NOT A CEILING. What a call costs is only known once it
        returns, so the honest promise is "nothing new starts", not "never a
        micro-dollar over". The overshoot is bounded by one call, which
        `max_tokens` already bounds - it is not unbounded, and it is not zero.
        """
        budget = await self.budget_for(client_slug)
        if budget is not None and budget.exhausted:
            raise BudgetExhausted(budget.client_slug)

    # ---- what it cost --------------------------------------------------------

    async def record_run(self, kind: str, model: str, result: Any) -> None:
        """Meter one finished run. Never raises: the answer is already delivered.

        A lost meter row under-charges by one call. An exception here would turn
        a successful answer into a 500 after the user has already been billed
        the real money at the provider - strictly worse, in both directions.
        """
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        if usage is None:
            return
        # The cache read is the single largest number in a generation run - 86%
        # of the input tokens, measured - and it is a tenth of the price. Read
        # defensively: a provider that does not report the detail leaves this at
        # zero, which charges the full rate rather than inventing a discount.
        details = getattr(usage, "input_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        await self.record(
            kind=kind,
            model=model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cached_input_tokens=cached,
        )

    async def record(
        self,
        *,
        kind: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> None:
        slug = CURRENT_CLIENT.get() or CLIENT_SLUG
        principal = CURRENT_PRINCIPAL.get() or "unknown"
        if not input_tokens and not output_tokens:
            return
        try:
            await self._call(
                "ui_record_usage",
                {
                    "client_slug": slug,
                    "principal_id": principal,
                    "kind": kind,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "cost_micros": cost_micros(
                        model, input_tokens, output_tokens, cached_input_tokens
                    ),
                },
            )
        except Exception:  # noqa: BLE001 - see the docstring above
            return

    # ---- the admin views -----------------------------------------------------

    async def all_usage(self) -> list[dict[str, Any]]:
        return ((await self._call("ui_list_usage", {})) or {}).get("items", [])

    async def all_accounts(self) -> list[dict[str, Any]]:
        return ((await self._call("ui_list_accounts", {})) or {}).get("items", [])

    async def set_budget(self, client_slug: str, budget_micros: int) -> int | None:
        payload = await self._call(
            "ui_set_budget", {"client_slug": client_slug, "budget_micros": budget_micros}
        )
        return (payload or {}).get("budget_micros")

    async def set_disabled(self, principal_id: str, disabled: bool) -> dict[str, Any] | None:
        payload = await self._call(
            "ui_set_account_disabled",
            {"principal_id": principal_id, "disabled": disabled},
        )
        # Without this the suspended person keeps working for up to the cache's
        # minute - which is exactly the minute somebody would be revoked in.
        self.forget(principal_id)
        return (payload or {}).get("account")

    async def provision_self(
        self,
        principal_id: str,
        email: str,
        provider: str,
        display_name: str = "",
        client_slug: str | None = None,
    ) -> Account | None:
        """Write a studio for a principal that signed in without one.

        Only called for providers that carry their own allowlist; `auth.py`
        decides that, and this method does not second-guess it - the check lives
        where the provider name is trusted.

        Raises rather than swallowing, unlike `bind` above. This one is not a
        read that can degrade to a default: if it fails, the alternative is
        letting the request continue scoped to `CLIENT_SLUG`, which is somebody
        else's studio. An error page is the better failure.
        """
        payload = await self._call(
            "ui_provision_account",
            {
                "principal_id": principal_id,
                "email": email,
                "provider": provider,
                "display_name": display_name,
                "client_slug": client_slug or "",
            },
        )
        raw = (payload or {}).get("account")
        # Whatever happened, the cached "no account" answer for this principal is
        # now stale - including when provisioning found them suspended.
        self.forget(principal_id)
        if not raw:
            return None
        return Account(
            principal_id=raw["principal_id"],
            email=raw["email"],
            role=raw["role"],
            client_slug=raw["client_slug"],
            client_name=raw["client_name"],
        )
