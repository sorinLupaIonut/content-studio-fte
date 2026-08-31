"""Trusted identity resolution for local development and Azure Easy Auth."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass

from content_studio.config import (
    AUTH_ALLOWED_EMAILS,
    AUTH_ALLOWED_PRINCIPAL_IDS,
    AUTH_DEV_EMAIL,
    AUTH_DEV_PRINCIPAL_ID,
    AUTH_MODE,
    AUTH_SELF_PROVISION_PROVIDERS,
    HARNESS_HOST,
    RUNNING_IN_AZURE,
)


@dataclass(frozen=True, slots=True)
class Identity:
    principal_id: str
    email: str
    provider: str
    #: What the platform calls this person. For Google it is the address again;
    #: for the external tenant it is the name Sorin typed when he created them,
    #: which is the better label for a studio and is kept separately so that
    #: resolving the real address does not throw it away.
    display_name: str = ""
    is_development: bool = False
    #: Their provider is one only Sorin can add people to, so a principal with no
    #: account yet gets one written rather than being refused. Decided here, where
    #: the provider name is trusted, and read in `main.authenticated`.
    may_self_provision: bool = False


@dataclass(slots=True)
class IdentityError(RuntimeError):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class AuthSettings:
    mode: str
    harness_host: str
    running_in_azure: bool
    allowed_emails: tuple[str, ...]
    allowed_principal_ids: tuple[str, ...]
    dev_principal_id: str
    dev_email: str
    self_provision_providers: tuple[str, ...] = ()


def configured_auth() -> AuthSettings:
    return AuthSettings(
        mode=AUTH_MODE,
        harness_host=HARNESS_HOST,
        running_in_azure=RUNNING_IN_AZURE,
        allowed_emails=AUTH_ALLOWED_EMAILS,
        allowed_principal_ids=AUTH_ALLOWED_PRINCIPAL_IDS,
        dev_principal_id=AUTH_DEV_PRINCIPAL_ID,
        dev_email=AUTH_DEV_EMAIL,
        self_provision_providers=AUTH_SELF_PROVISION_PROVIDERS,
    )


def is_loopback_host(host: str) -> bool:
    host = host.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


#: Claim types that carry an address, most specific first. The long one is the
#: SAML-style name Easy Auth uses when it normalises a token's claims.
EMAIL_CLAIM_TYPES = (
    "email",
    "emails",
    "preferred_username",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
)


def email_from_claims(headers: Mapping[str, str]) -> str:
    """The address out of the injected claims blob, or "" when there is none.

    WHY THIS EXISTS. `x-ms-client-principal-name` is an address for Google and a
    *display name* for the external tenant - verified against the live app on
    2026-08-23, and not changed by setting `nameClaimType` on the provider or by
    adding `email` as an optional claim on the application. The address is in the
    token either way, just not in that header, and `x-ms-client-principal` is
    where Easy Auth puts the whole claim set.

    Never raises. A malformed or absent blob means the caller keeps whatever the
    name header gave it, which is exactly the behaviour that existed before.
    """
    blob = headers.get("x-ms-client-principal", "").strip()
    if not blob:
        return ""
    try:
        # Base64 without padding is common enough here to be worth tolerating.
        padded = blob + "=" * (-len(blob) % 4)
        decoded = json.loads(base64.b64decode(padded))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return ""
    claims = decoded.get("claims")
    if not isinstance(claims, list):
        return ""

    found: dict[str, str] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        typ = str(claim.get("typ") or claim.get("type") or "").strip()
        val = str(claim.get("val") or claim.get("value") or "").strip()
        # "@" is the whole test. A claim named `preferred_username` can hold a
        # bare username, and a bare username is not what any caller here wants.
        if typ and "@" in val and typ not in found:
            found[typ] = val.lower()
    for typ in EMAIL_CLAIM_TYPES:
        if typ in found:
            return found[typ]
    return ""


class IdentityResolver:
    """Resolve only platform-injected headers, or one explicit local identity."""

    def __init__(self, settings: AuthSettings | None = None) -> None:
        self.settings = settings or configured_auth()

    def validate_startup(self) -> None:
        settings = self.settings
        if settings.mode not in {"azure", "development"}:
            raise RuntimeError("AUTH_MODE must be either 'azure' or 'development'")
        if settings.mode == "development":
            if settings.running_in_azure:
                raise RuntimeError("development authentication is forbidden in Azure")
            if not is_loopback_host(settings.harness_host):
                raise RuntimeError(
                    "development authentication requires HARNESS_HOST to be loopback"
                )
            if not settings.dev_principal_id or not settings.dev_email:
                raise RuntimeError("development identity is incomplete")

    def resolve(self, headers: Mapping[str, str]) -> Identity:
        settings = self.settings
        if settings.mode == "development":
            self.validate_startup()
            return Identity(
                principal_id=settings.dev_principal_id,
                email=settings.dev_email,
                provider="development",
                is_development=True,
            )

        principal_id = headers.get("x-ms-client-principal-id", "").strip()
        email = headers.get("x-ms-client-principal-name", "").strip().lower()
        provider = headers.get("x-ms-client-principal-idp", "google").strip() or "google"
        if not principal_id or not email:
            raise IdentityError(401, "Azure authentication is missing or incomplete.")

        # Read again without the lowercasing: `email` is folded for comparison
        # against the allowlist, but this one is a label a person typed and ends
        # up on the admin page, where "Maria Stan" beats "maria stan".
        display_name = headers.get("x-ms-client-principal-name", "").strip()

        # Only when the name header is not an address already - which is to say,
        # never for Google. Nothing about the existing door changes.
        if "@" not in email:
            email = email_from_claims(headers) or email

        # A provider only Sorin can add people to carries its own allowlist:
        # arriving here already proves he created this person. Checked before the
        # lists rather than after, because the point of the external tenant is
        # that a new tester costs a form in the Entra portal - not that, plus an
        # address in .env, plus a deployment to carry it.
        #
        # The two mechanisms never mix. An address is not matched across
        # providers, deliberately: the same string arriving from Google and from
        # the tenant is two different people as far as this studio is concerned,
        # and linking them by email would be the one silent way to hand somebody
        # else's profile over.
        if provider.lower() in settings.self_provision_providers:
            return Identity(
                principal_id=principal_id,
                email=email,
                provider=provider,
                display_name=display_name,
                may_self_provision=True,
            )

        if settings.allowed_principal_ids:
            allowed = principal_id in settings.allowed_principal_ids
        elif settings.allowed_emails:
            allowed = email in settings.allowed_emails
        else:
            raise IdentityError(503, "The authentication allowlist is not configured.")
        if not allowed:
            raise IdentityError(403, "This account has no access to Studio Viorela.")

        return Identity(
            principal_id=principal_id,
            email=email,
            provider=provider,
            display_name=display_name,
        )
