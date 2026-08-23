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


class TestSelfProvisioningProvider(unittest.TestCase):
    """A provider only Sorin can add people to carries its own allowlist."""

    def headers(self, idp: str, email: str = "tester@studio.invalid") -> dict[str, str]:
        return {
            "x-ms-client-principal-id": "principal-9",
            "x-ms-client-principal-name": email,
            "x-ms-client-principal-idp": idp,
        }

    def test_named_provider_enters_without_being_on_the_allowlist(self) -> None:
        resolver = IdentityResolver(settings(self_provision_providers=("entra",)))
        identity = resolver.resolve(self.headers("entra"))
        self.assertTrue(identity.may_self_provision)
        self.assertEqual(identity.provider, "entra")

    def test_other_providers_are_still_refused(self) -> None:
        resolver = IdentityResolver(settings(self_provision_providers=("entra",)))
        with self.assertRaises(IdentityError) as caught:
            resolver.resolve(self.headers("google", "stranger@example.com"))
        self.assertEqual(caught.exception.status_code, 403)

    def test_the_allowlisted_address_does_not_carry_across_providers(self) -> None:
        """The same address from two providers is two people, on purpose.

        Matching them would be the one quiet way to hand somebody another
        person's profile, so being allowlisted for Google must not mark a
        principal from the tenant as anything other than self-provisioning.
        """
        resolver = IdentityResolver(settings(self_provision_providers=("entra",)))
        identity = resolver.resolve(self.headers("entra", "allowed@example.com"))
        self.assertTrue(identity.may_self_provision)

    def test_nothing_changes_when_no_provider_is_named(self) -> None:
        resolver = IdentityResolver(settings())
        with self.assertRaises(IdentityError) as caught:
            resolver.resolve(self.headers("entra"))
        self.assertEqual(caught.exception.status_code, 403)

    def test_an_empty_allowlist_still_refuses_other_providers(self) -> None:
        """503 rather than letting everyone in - the old fail-closed promise."""
        resolver = IdentityResolver(
            settings(allowed_emails=(), self_provision_providers=("entra",))
        )
        with self.assertRaises(IdentityError) as caught:
            resolver.resolve(self.headers("google"))
        self.assertEqual(caught.exception.status_code, 503)



class TestNameAndAddress(unittest.TestCase):
    """The name header is an address for Google and a display name elsewhere."""

    def blob(self, claims: list[dict[str, str]]) -> str:
        import base64
        import json

        return base64.b64encode(json.dumps({"claims": claims}).encode()).decode()

    def test_the_address_is_recovered_from_the_claims(self) -> None:
        resolver = IdentityResolver(settings(self_provision_providers=("entra",)))
        identity = resolver.resolve(
            {
                "x-ms-client-principal-id": "principal-9",
                "x-ms-client-principal-name": "Maria Stan",
                "x-ms-client-principal-idp": "entra",
                "x-ms-client-principal": self.blob(
                    [
                        {"typ": "name", "val": "Maria Stan"},
                        {"typ": "email", "val": "Maria.Stan@studio.invalid"},
                    ]
                ),
            }
        )
        self.assertEqual(identity.email, "maria.stan@studio.invalid")
        # Unfolded: this one is a label, not something compared to a list.
        self.assertEqual(identity.display_name, "Maria Stan")

    def test_a_missing_blob_changes_nothing(self) -> None:
        resolver = IdentityResolver(settings(self_provision_providers=("entra",)))
        identity = resolver.resolve(
            {
                "x-ms-client-principal-id": "principal-9",
                "x-ms-client-principal-name": "Maria Stan",
                "x-ms-client-principal-idp": "entra",
            }
        )
        self.assertEqual(identity.email, "maria stan")

    def test_a_corrupt_blob_never_raises(self) -> None:
        resolver = IdentityResolver(settings(self_provision_providers=("entra",)))
        identity = resolver.resolve(
            {
                "x-ms-client-principal-id": "principal-9",
                "x-ms-client-principal-name": "Maria Stan",
                "x-ms-client-principal-idp": "entra",
                "x-ms-client-principal": "not-base64-at-all!!",
            }
        )
        self.assertEqual(identity.email, "maria stan")

    def test_google_is_untouched(self) -> None:
        """The address arrives in the name header there; nothing is second-guessed."""
        resolver = IdentityResolver(settings())
        identity = resolver.resolve(
            {
                "x-ms-client-principal-id": "principal-1",
                "x-ms-client-principal-name": "Allowed@Example.com",
                "x-ms-client-principal": self.blob(
                    [{"typ": "email", "val": "someone.else@example.com"}]
                ),
            }
        )
        self.assertEqual(identity.email, "allowed@example.com")


if __name__ == "__main__":
    unittest.main()
