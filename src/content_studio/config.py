"""Environment, paths and the DATABASE_URL normalizer. Decision 3.

Everything the project reads from the outside world is collected here, so no
other module calls `os.getenv` directly and nobody has to remember where `.env`
gets loaded. Importing this module loads `.env` once, from the project root —
not from the current working directory, so a script started from anywhere still
finds it.

The URL normalizer exists because the string Neon hands you under "Copy" does
NOT work with `asyncpg` as-is. Their button produces a libpq-style URL:

    postgresql://user:password@ep-abc-123-pooler.eu-central-1.aws.neon.tech/dbname
        ?sslmode=require&channel_binding=require

Three things break if you paste that straight into `.env`:

1. The scheme is `postgresql://`, so SQLAlchemy picks the synchronous `psycopg2`
   driver (not installed) instead of `asyncpg`. It needs `postgresql+asyncpg://`.
2. `sslmode` and `channel_binding` are libpq parameters. `asyncpg` does not know
   them; SQLAlchemy forwards them as connection arguments and the call dies with
   a `TypeError` that says nothing about the real cause.
3. The `-pooler` endpoint is PgBouncer in transaction mode. `asyncpg` defaults to
   named prepared statements, which do not survive connection recycling — you get
   an intermittent `InvalidSQLStatementNameError`, usually after a few successful
   runs. That is why the cache is disabled in two places: `statement_cache_size`
   (asyncpg level) and `prepared_statement_cache_size` (SQLAlchemy dialect level).

`normalize_url` takes any of those shapes and returns one that works, so you can
paste the Neon console line without fixing it by hand.

TWO ENDPOINTS, TWO JOBS (D4). The running app uses the pooled endpoint —
PgBouncer multiplexes many app connections into few real ones, which is what
makes scale-out affordable. DDL does not go through it. In transaction pooling a
`SET` from one transaction is not guaranteed to reach the next, and a migration
that half-applies its session settings fails intermittently rather than loudly.
So `migration_url()` demands the DIRECT endpoint and refuses `-pooler`, while
`database_url()` stays exactly as it was. Put both in `.env`:

    DATABASE_URL          …-pooler.<region>.aws.neon.tech/…   the app
    DATABASE_URL_DIRECT   …<region>.aws.neon.tech/…           migrations only

The app never relies on `search_path` either — every statement names its schema
(`public.runs`). See the header of db/schema.sql.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

#: Repository root: this file is `<root>/src/content_studio/config.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Loaded from an explicit path first: `load_dotenv()` alone searches upwards from
# the current directory, which fails the moment a script is started elsewhere.
if not load_dotenv(PROJECT_ROOT / ".env"):
    load_dotenv()

#: Skill folders mounted into the sandbox. They stay outside the Python package
#: on purpose: they are prose the client's method lives in, edited without
#: touching code. Override with SKILLS_DIR when running from somewhere else.
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", PROJECT_ROOT / "skills"))

#: Raw material before it reaches Postgres: profile, books, published posts.
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", PROJECT_ROOT / "content"))

#: The only client for now. Also the prefix of every `session_id`, which is what
#: lets the worker find the last conversation to resume.
CLIENT_SLUG = os.getenv("CLIENT_SLUG", "viorela")

MODEL = os.getenv("MODEL", "gpt-5-mini")
WEB_SEARCH_MODEL = os.getenv("WEB_SEARCH_MODEL", MODEL)

#: Storing and searching must use the SAME model — architecture rule 3.
EMBEDDING_MODEL = "text-embedding-3-small"

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8765"))
MCP_URL = os.getenv("MCP_URL", f"http://{MCP_HOST}:{MCP_PORT}/mcp")

#: Web search can run past 30 seconds on cold connections.
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "90"))

# libpq parameters asyncpg refuses as connection arguments.
# `sslmode` is not dropped — it is translated into `ssl` below.
LIBPQ_PARAMS = {"sslmode", "channel_binding", "connect_timeout", "application_name"}

# sslmode (libpq) -> ssl (asyncpg)
SSL_TRANSLATION = {
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
    "prefer": "prefer",
    "allow": "prefer",
    "disable": "disable",
}


class MissingConfig(RuntimeError):
    """DATABASE_URL is absent or unusable."""


def normalize_url(url: str) -> tuple[str, dict[str, object]]:
    """Return `(sqlalchemy_url, connect_args)` for any shape of Postgres URL.

    Idempotent: an already normalized URL passes through untouched.
    """
    parts = urlsplit(url.strip())

    if not parts.scheme:
        raise MissingConfig(
            f"DATABASE_URL does not look like a URL: {url[:40]!r}…\n"
            "Expected something like postgresql://user:password@host/db"
        )

    # 1. The async driver, without breaking an explicit `+asyncpg`.
    if parts.scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    elif parts.scheme.startswith("postgresql+"):
        scheme = parts.scheme
    else:
        raise MissingConfig(
            f"Scheme {parts.scheme!r} is not Postgres. Neon hands out postgresql://…"
        )

    if scheme != "postgresql+asyncpg":
        raise MissingConfig(
            f"Driver {scheme!r} is synchronous. SQLAlchemySession needs an async "
            "engine — use postgresql+asyncpg://"
        )

    # 2. Strip libpq parameters, translate sslmode into ssl.
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.get("sslmode")
    kept = {k: v for k, v in query.items() if k not in LIBPQ_PARAMS}

    connect_args: dict[str, object] = {}
    if sslmode:
        translated = SSL_TRANSLATION.get(sslmode.lower())
        if translated is None:
            raise MissingConfig(f"Unknown sslmode={sslmode!r}")
        if translated != "disable":
            connect_args["ssl"] = translated
    elif ".neon.tech" in (parts.hostname or ""):
        # Neon requires TLS anyway; if the URL omits it, add it here.
        connect_args["ssl"] = "require"

    # 3. Prepared statements off. Always, not only for `-pooler` hosts: at this
    #    volume the gain is unmeasurable, and when the detection is wrong the
    #    error shows up intermittently, in production, looking like something else.
    connect_args["statement_cache_size"] = 0
    kept["prepared_statement_cache_size"] = "0"

    final_url = urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )
    return final_url, connect_args


def database_url() -> tuple[str, dict[str, object]]:
    """Read DATABASE_URL from the environment and normalize it."""
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise MissingConfig(
            "DATABASE_URL is missing.\n"
            "Copy .env.example to .env and put the Neon console string there.\n"
            "Their form with sslmode=require is fine — it gets normalized here."
        )
    return normalize_url(raw)


def is_pooled(url: str) -> bool:
    """True for Neon's PgBouncer endpoint, whose host carries `-pooler`."""
    return "-pooler" in (urlsplit(url).hostname or "")


def migration_url() -> tuple[str, dict[str, object]]:
    """The endpoint DDL is allowed through: direct, never `-pooler`.

    Falls back to DATABASE_URL when DATABASE_URL_DIRECT is absent — but only if
    that one is already direct. A pooled URL is refused rather than used, because
    the failure it causes is intermittent and shows up long after the migration
    appeared to succeed.
    """
    raw = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
    if not raw:
        raise MissingConfig(
            "Neither DATABASE_URL_DIRECT nor DATABASE_URL is set.\n"
            "Copy .env.example to .env and put the Neon console strings there."
        )

    url, connect_args = normalize_url(raw)
    if is_pooled(url):
        raise MissingConfig(
            "Migrations must not run through the pooled endpoint.\n"
            f"  {describe_database(url)}\n\n"
            "Add DATABASE_URL_DIRECT to .env — the same connection string with\n"
            "`-pooler` removed from the host. In the Neon console it is the string\n"
            "you get with 'Connection pooling' switched off."
        )
    return url, connect_args


def describe_database(url: str) -> str:
    """Password-free description, safe to print in a terminal."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    database = parts.path.lstrip("/") or "?"
    pooled = "-pooler" in host
    return f"{host}/{database}" + ("  (pooled endpoint)" if pooled else "  (direct)")
