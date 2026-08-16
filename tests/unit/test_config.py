"""URL normalization, the part that broke three times before it was written down.

Every case here is a shape the Neon console actually hands out.
"""

import unittest

from content_studio.config import MissingConfig, normalize_url

NEON = (
    "postgresql://user:pass@ep-abc-123-pooler.eu-central-1.aws.neon.tech/db"
    "?sslmode=require&channel_binding=require"
)


class TestNormalizeUrl(unittest.TestCase):
    def test_console_string_becomes_asyncpg(self) -> None:
        url, connect_args = normalize_url(NEON)

        self.assertTrue(url.startswith("postgresql+asyncpg://"))
        self.assertNotIn("sslmode", url)
        self.assertNotIn("channel_binding", url)
        self.assertEqual(connect_args["ssl"], "require")

    def test_prepared_statements_are_disabled_on_both_levels(self) -> None:
        url, connect_args = normalize_url(NEON)

        self.assertEqual(connect_args["statement_cache_size"], 0)
        self.assertIn("prepared_statement_cache_size=0", url)

    def test_is_idempotent(self) -> None:
        once, args_once = normalize_url(NEON)
        twice, args_twice = normalize_url(once)

        self.assertEqual(once, twice)
        self.assertEqual(args_once, args_twice)

    def test_neon_host_gets_tls_even_without_sslmode(self) -> None:
        _, connect_args = normalize_url("postgresql://u:p@ep-x.neon.tech/db")

        self.assertEqual(connect_args["ssl"], "require")

    def test_sslmode_disable_is_honoured(self) -> None:
        _, connect_args = normalize_url("postgresql://u:p@localhost/db?sslmode=disable")

        self.assertNotIn("ssl", connect_args)

    def test_a_synchronous_driver_is_refused(self) -> None:
        with self.assertRaises(MissingConfig):
            normalize_url("postgresql+psycopg2://u:p@localhost/db")

    def test_something_that_is_not_a_url_is_refused(self) -> None:
        with self.assertRaises(MissingConfig):
            normalize_url("put the string from Neon here")


if __name__ == "__main__":
    unittest.main()
