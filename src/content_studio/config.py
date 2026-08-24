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

#: The folders the method lives in, one per skill. They stay outside the package
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

# D1b deliberately splits the cheap, short title pass from the long structured
# writing pass. The existing CLI keeps using MODEL unchanged.
# Titles moved off nano on 2026-08-24. Nano was the cheap half of the split and
# it stopped earning it: measured on batch c82d55fd, the title pass never called
# `propune-postari` at all - it reached for `list_posts` and `search_books`,
# got `[]` from both, and wrote ten titles without ever reading the method. The
# detail pass, on mini, called its tool 11 times out of 11 with the same prompt
# shape. The titles read generic afterwards, which is the part that matters.
#
# The move also stops paying twice for the same prefix. Now that a skill is a
# tool, both phases build the SAME instructions; on one model that is one cached
# prefix, and the title call warms it for the ten that follow.
#
# Since 2026-08-24 the model is a choice in the interface, one per batch, and it
# reaches both phases - see `GENERATION_MODELS`. These two stay as the fallback
# for a request that names none, and they are read only there.
GENERATION_TITLE_MODEL = os.getenv("GENERATION_TITLE_MODEL", "gpt-5-nano")
GENERATION_DETAIL_MODEL = os.getenv("GENERATION_DETAIL_MODEL", "gpt-5-nano")

#: What the interface may ask for. An allowlist, not a free string: the value
#: arrives from a browser, and `pricing.py` charges an unrecognised model at the
#: most expensive rate in its table - so an unchecked one would be a typo that
#: silently drains an allowance. First entry is the default.
#:
#: NANO IS THE DEFAULT, AND IT IS A MEASURED TRADE. On 2026-08-24, with the
#: method still fetched turn by turn, nano finished 3 detail runs out of 10:
#: four missed the structured contract and three ran out of turns. Three of
#: those seven are the failure mode `content_studio.method` removes outright,
#: which is why the preloading landed first and the default moved after. What
#: nano cannot be talked out of is its Romanian - measured in the same run:
#: "Încerc-o azi" for "Încearcă-o", "se brăzdează drumul", a CIFRĂ hook with no
#: number in it. Mini is one click away in the interface for exactly that
#: reason, and it is the right click for anything that gets published.
GENERATION_MODELS: tuple[str, ...] = ("gpt-5-nano", "gpt-5-mini")
GENERATION_CONCURRENCY = int(os.getenv("GENERATION_CONCURRENCY", "5"))
if not 1 <= GENERATION_CONCURRENCY <= 5:
    raise RuntimeError("GENERATION_CONCURRENCY must be between 1 and 5")

# Chat is separate from bulk generation so its latency/quality can be tuned
# without silently changing either half of the accepted hybrid topology.
CHAT_MODEL = os.getenv("CHAT_MODEL", MODEL)

#: Storing and searching must use the SAME model — architecture rule 3.
EMBEDDING_MODEL = "text-embedding-3-small"

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8765"))
MCP_URL = os.getenv("MCP_URL", f"http://{MCP_HOST}:{MCP_PORT}/mcp")

#: Web search can run past 30 seconds on cold connections.
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "90"))

HARNESS_HOST = os.getenv("HARNESS_HOST", "0.0.0.0")
HARNESS_PORT = int(os.getenv("PORT", os.getenv("HARNESS_PORT", "8000")))

AUTH_MODE = os.getenv("AUTH_MODE", "azure").strip().lower()
AUTH_ALLOWED_EMAILS = tuple(
    value.strip().lower()
    for value in os.getenv("AUTH_ALLOWED_EMAILS", "").split(",")
    if value.strip()
)
AUTH_ALLOWED_PRINCIPAL_IDS = tuple(
    value.strip()
    for value in os.getenv("AUTH_ALLOWED_PRINCIPAL_IDS", "").split(",")
    if value.strip()
)
# The one signed-in person who may reach `CLIENT_SLUG` without a row in
# `app_users` - the client this studio was built for, who predates accounts.
#
# Empty keeps the older behaviour, where *anyone* on the allowlist without an
# account falls through to `CLIENT_SLUG`. That fallback is what let the
# single-tenant studio keep working, and it is also the trap: allow a tester,
# forget to provision them, and they land on her profile, her library and her
# allowance. Naming the owner turns "whoever gets here" into "her".
CLIENT_OWNER_EMAIL = os.getenv("CLIENT_OWNER_EMAIL", "").strip().lower()

# Providers whose principals may enter without being on the allowlist, and get a
# studio written for them on their first request.
#
# This is safe for exactly one kind of provider: a directory only Sorin can put
# people into. Membership of the external Entra tenant then *is* the allowlist -
# "authenticated here" already means "Sorin created this person", which is the
# fact AUTH_ALLOWED_EMAILS exists to assert. It is emphatically not safe for
# Google, where membership means somebody has an email address.
#
# The value is the provider name Easy Auth reports in x-ms-client-principal-idp,
# which for a custom OpenID Connect provider is the name it was registered under.
# Empty - the default - keeps every door exactly as it was.
AUTH_SELF_PROVISION_PROVIDERS = tuple(
    value.strip().lower()
    for value in os.getenv("AUTH_SELF_PROVISION_PROVIDERS", "").split(",")
    if value.strip()
)

AUTH_DEV_PRINCIPAL_ID = os.getenv("AUTH_DEV_PRINCIPAL_ID", "local-sorin").strip()
AUTH_DEV_EMAIL = os.getenv("AUTH_DEV_EMAIL", "local@studio.invalid").strip().lower()
# Empty is a supported state, not a misconfiguration: the harness runs and logs
# to stdout, and `/health` says so plainly.
APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv(
    "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
).strip()

# The fourth surface. Empty is a supported state exactly like the one above: the
# agent's steps stay in `public.traces`, which is the durable record either way.
# Phoenix Cloud hands out a space URL; the endpoint may be given with or without
# the `/v1/traces` path - `observability._traces_endpoint` settles it.
PHOENIX_COLLECTOR_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "").strip()
PHOENIX_API_KEY = os.getenv("PHOENIX_API_KEY", "").strip()
#: The project a span lands in. One per environment, so a local experiment does
#: not sit in the same list as what the client actually ran.
PHOENIX_PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "studio-viorela").strip()

# Per principal, per minute. A ceiling on accidents - a page stuck in a retry
# loop, a held-down button - not a security boundary; the budget gate is what
# bounds deliberate spending. 0 turns it off.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

RUNNING_IN_AZURE = bool(
    os.getenv("CONTAINER_APP_NAME")
    or os.getenv("CONTAINER_APP_ENV_DNS_SUFFIX")
    or os.getenv("WEBSITE_SITE_NAME")
)

UI_STATIC_DIR = Path(
    os.getenv(
        "UI_STATIC_DIR",
        PROJECT_ROOT / "ui" / "StudioViorela" / "dist" / "wwwroot",
    )
)
UI_DEV_ORIGINS = tuple(
    value.strip().rstrip("/")
    for value in os.getenv(
        "UI_DEV_ORIGINS", "http://127.0.0.1:5178,http://localhost:5178"
    ).split(",")
    if value.strip()
)

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


def has_openai_key() -> bool:
    """Whether model calls are configured, without exposing the key."""
    return bool(os.getenv("OPENAI_API_KEY"))


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
