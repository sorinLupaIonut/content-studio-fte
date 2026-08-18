"""Trusted identity resolution for local development and Azure Easy Auth."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

from content_studio.config import (
    AUTH_ALLOWED_EMAILS,
    AUTH_ALLOWED_PRINCIPAL_IDS,
    AUTH_DEV_EMAIL,
    AUTH_DEV_PRINCIPAL_ID,
    AUTH_MODE,
    HARNESS_HOST,
    RUNNING_IN_AZURE,
)


@dataclass(frozen=True, slots=True)
class Identity:
    principal_id: str
    email: str
    provider: str
    is_development: bool = False


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


def configured_auth() -> AuthSettings:
    return AuthSettings(
        mode=AUTH_MODE,
        harness_host=HARNESS_HOST,
        running_in_azure=RUNNING_IN_AZURE,
        allowed_emails=AUTH_ALLOWED_EMAILS,
        allowed_principal_ids=AUTH_ALLOWED_PRINCIPAL_IDS,
        dev_principal_id=AUTH_DEV_PRINCIPAL_ID,
        dev_email=AUTH_DEV_EMAIL,
    )


def is_loopback_host(host: str) -> bool:
    host = host.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


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
            raise IdentityError(401, "Autentificarea Azure lipsește sau este incompletă.")

        if settings.allowed_principal_ids:
            allowed = principal_id in settings.allowed_principal_ids
        elif settings.allowed_emails:
            allowed = email in settings.allowed_emails
        else:
            raise IdentityError(503, "Allowlist-ul de autentificare nu este configurat.")
        if not allowed:
            raise IdentityError(403, "Acest cont nu are acces la Studio Viorela.")

        return Identity(
            principal_id=principal_id,
            email=email,
            provider=provider,
        )
