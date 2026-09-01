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

#: The sandbox the method is read from. E2B, because it is the one backend that
#: works from here: the SDK's local Unix client is `sys.platform != "win32"`
#: only, and Docker Desktop is not running on the development machine. The key
#: is read here and nowhere else - `config.py` is the only module that calls
#: `os.getenv` (see AGENTS.md, Conventions).
E2B_API_KEY = os.getenv("E2B_API_KEY", "")

#: How long a sandbox may live with nobody talking to it, in seconds. A batch is
#: eleven runs sharing one sandbox, and the longest one measured took about four
#: minutes, so ten leaves room without paying for an hour of idle container.
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "600"))

#: Raw material before it reaches Postgres: profile, books, published posts.
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", PROJECT_ROOT / "content"))

#: The only client for now. Also the prefix of every `session_id`, which is what
#: lets the worker find the last conversation to resume.
CLIENT_SLUG = os.getenv("CLIENT_SLUG", "viorela")

MODEL = os.getenv("MODEL", "gpt-5-mini")
WEB_SEARCH_MODEL = os.getenv("WEB_SEARCH_MODEL", MODEL)

# D1b deliberately split the cheap, short title pass from the long structured
# writing pass. Both are `gpt-5-mini` now, and these two names stay only as the
# fallback for a request that chooses no model.
#
# NANO IS GONE, 2026-08-27, by Sorin's decision, and it is the second time it
# failed the same way. On 2026-08-24 it finished 3 detail runs out of 10 - four
# missed the structured contract, three ran out of turns - and its Romanian was
# wrong in ways nothing can be prompted out of ("Încerc-o azi" for "Încearcă-o",
# a CIFRĂ hook with no number in it). It survived that because preloading the
# method removed the failures that were about fetching.
#
# The method moved into a sandbox on 2026-08-27 and nano failed the new shape on
# the first live run: it called `exec_command` twice with the command `bash`,
# read nothing, and wrote ten plausible titles from memory. Nobody would have
# noticed from the output. Driving a shell to open a file is the job now, and
# nano cannot do it - so it is not on the allowlist, not in the interface, and
# not in the tests. Its price stays in `pricing.py` because `usage_events` still
# holds rows that were charged at it.
GENERATION_TITLE_MODEL = os.getenv("GENERATION_TITLE_MODEL", "gpt-5-mini")
GENERATION_DETAIL_MODEL = os.getenv("GENERATION_DETAIL_MODEL", "gpt-5-mini")

#: What the interface may ask for. An allowlist, not a free string: the value
#: arrives from a browser, and `pricing.py` charges an unrecognised model at the
#: most expensive rate in its table - so an unchecked one would be a typo that
#: silently drains an allowance. First entry is the default.
#:
#: One entry from 2026-08-27 until 2026-09-01, and the sentence that stood here
#: said a second name would have to earn its place by driving the sandbox shell
#: rather than by being cheaper. `gpt-5` earns it from the other direction: it
#: is not cheaper, it is the same family one tier up, and it is here to answer a
#: question mini cannot be argued out of.
#:
#: The question is the client's. Her wife read a hook and a caption in Romanian
#: on 2026-09-01 and said neither sounded like her, nor like a person. Two evals
#: now measure that (`evals/output/`), and the fix they graded — lifting her
#: voice sections into the prompt — is a change to the INPUT. Whether the
#: remaining gap is the input or the writer is a different question, and the
#: only way to answer it is to run the same brief through a bigger model.
#:
#: First entry is the default, and it stays mini: this is an experiment the
#: client opts into, not a new floor. gpt-5 costs five times mini per token —
#: which is exactly why `MODEL_CHOICE_CLIENTS` below is not everybody.
GENERATION_MODELS: tuple[str, ...] = ("gpt-5-mini", "gpt-5")

#: Which accounts may choose. Everyone else gets `GENERATION_MODELS[0]` and no
#: picker, which is what every account had until now.
#:
#: NOT AN INTERFACE DECISION. A hidden control is not a permission — the same
#: rule `MeResponse.is_admin` is written under — so `/api/me` only says whether
#: to DRAW the picker, and `models_for` below is what the start endpoint asks
#: before it honours a model name that arrived from a browser.
#:
#: It is her account and no other on purpose. The budget is a lifetime
#: allowance in a database, and a tester who picked the expensive model out of
#: curiosity would spend theirs in two batches and be told nothing except that
#: nothing starts any more.
MODEL_CHOICE_CLIENTS: tuple[str, ...] = tuple(
    slug.strip()
    for slug in os.getenv("MODEL_CHOICE_CLIENTS", CLIENT_SLUG).split(",")
    if slug.strip()
)


def models_for(client_slug: str | None) -> tuple[str, ...]:
    """Which models this account may ask for. The whole list, or just the default.

    One answer, asked by both doors: `/api/me` draws the picker from it and the
    start endpoint refuses anything not in it. A second copy of this rule is a
    second chance to disagree with itself.
    """
    if client_slug and client_slug in MODEL_CHOICE_CLIENTS:
        return GENERATION_MODELS
    return GENERATION_MODELS[:1]

# Chat is separate from bulk generation so its latency/quality can be tuned
# without silently changing either half of the accepted hybrid topology.
CHAT_MODEL = os.getenv("CHAT_MODEL", MODEL)

#: The model that grades, never the model that writes - except it is the same
#: family now, on Sorin's call of 2026-08-30: the evals are paid out of pocket
#: and gpt-5 cost about four times this per run. What that buys back in money it
#: gives up in independence: a judge on the writer's own model scores its own
#: phrasing as good, because it is the phrasing it would have chosen. Read a
#: borderline verdict with that in mind, and set EVAL_JUDGE_MODEL=gpt-5 in `.env`
#: for a run whose numbers have to hold up.
EVAL_JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-5-mini")

#: Storing and searching must use the SAME model — architecture rule 3.
EMBEDDING_MODEL = "text-embedding-3-small"

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8765"))
MCP_URL = os.getenv("MCP_URL", f"http://{MCP_HOST}:{MCP_PORT}/mcp")

#: The ceiling on ONE MCP tool call, and `search_web` is the only tool that goes
#: anywhere near it.
#:
#: MEASURED, NOT GUESSED, 2026-08-30: three consecutive real searches took 80s,
#: 55s and 40s end to end. It was 90 here, on a note about "cold connections"
#: written when the tool returned a short synthesis; it now reads pages and fills
#: a schema, and the slowest of those three had ten seconds of headroom left.
#: `tests/checks/safe/tools.py` duly timed out on the first run of the day, which
#: is the good version of this failure - the bad one is a generation run losing
#: its `Internet` material and writing from memory, since an MCP timeout comes
#: back as a short error string rather than as an exception the run can see.
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "180"))

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

# The judge for the output evals, and deliberately NOT the family that writes
# the posts. A grader from the same lineage as the author marks its own work -
# the bias the eval course names first. DeepSeek shares no training lineage with
# gpt-5, which is the whole reason it is here; the price is a side benefit.
# Never read by the worker: nothing the client runs depends on it. Its reader,
# `evals/output/`, came back on 2026-09-01 — and then measured this address
# against the family it was meant to replace, on both control sets:
#
#     metric   deepseek-chat            gpt-5-mini
#     voice    4/4 planted, 16/16 hers  4/4 planted, 15/16 hers
#     human    2/4 planted, 15/16 hers  4/4 planted, 14/16 hers
#
# DeepSeek judges her VOICE better and cannot judge `human` at all: it passed
# two planted violations, one a caption taken verbatim from a real run. So the
# default judge is `EVAL_JUDGE_MODEL` after all, the independence is bought back
# by the controls instead, and this stays reachable — `--judge deepseek` — as
# the second opinion that made the table above.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

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
    """A required setting is absent or unusable — DATABASE_URL, E2B_API_KEY."""


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
