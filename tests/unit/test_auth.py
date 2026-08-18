"""Fail-closed authentication tests without Azure or a browser."""

import unittest

from content_studio.harness.auth import (
    AuthSettings,
    IdentityError,
    IdentityResolver,
)


def settings(**overrides) -> AuthSettings:
    values = {
        "mode": "azure",
        "harness_host": "0.0.0.0",
        "running_in_azure": True,
        "allowed_emails": ("allowed@example.com",),
        "allowed_principal_ids": (),
        "dev_principal_id": "local-user",
        "dev_email": "local@example.com",
    }
    values.update(overrides)
    return AuthSettings(**values)


class TestIdentityResolver(unittest.TestCase):
    def test_development_identity_requires_loopback(self) -> None:
        resolver = IdentityResolver(
            settings(mode="development", running_in_azure=False)
        )
        with self.assertRaisesRegex(RuntimeError, "loopback"):
            resolver.validate_startup()

    def test_development_mode_is_forbidden_in_azure(self) -> None:
        resolver = IdentityResolver(
            settings(mode="development", harness_host="127.0.0.1")
        )
        with self.assertRaisesRegex(RuntimeError, "forbidden"):
            resolver.validate_startup()

    def test_local_identity_is_explicit(self) -> None:
        resolver = IdentityResolver(
            settings(
                mode="development",
                harness_host="127.0.0.1",
                running_in_azure=False,
            )
        )
        identity = resolver.resolve({})
        self.assertEqual(identity.principal_id, "local-user")
        self.assertTrue(identity.is_development)

    def test_azure_headers_are_required(self) -> None:
        with self.assertRaises(IdentityError) as caught:
            IdentityResolver(settings()).resolve({})
        self.assertEqual(caught.exception.status_code, 401)

    def test_email_allowlist_bootstrap_is_case_insensitive(self) -> None:
        identity = IdentityResolver(settings()).resolve(
            {
                "x-ms-client-principal-id": "principal-1",
                "x-ms-client-principal-name": "Allowed@Example.com",
            }
        )
        self.assertEqual(identity.email, "allowed@example.com")

    def test_principal_allowlist_takes_priority_over_email(self) -> None:
        resolver = IdentityResolver(
            settings(allowed_principal_ids=("principal-2",))
        )
        with self.assertRaises(IdentityError) as caught:
            resolver.resolve(
                {
                    "x-ms-client-principal-id": "principal-1",
                    "x-ms-client-principal-name": "allowed@example.com",
                }
            )
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
