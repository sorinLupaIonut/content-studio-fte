"""Citirea și normalizarea lui DATABASE_URL. Decizia 3.

Există fiindcă URL-ul pe care ți-l dă consola Neon la „Copy" NU merge direct cu
`asyncpg`. Butonul lor scoate un URL în stil libpq:

    postgresql://user:parola@ep-abc-123-pooler.eu-central-1.aws.neon.tech/dbname
        ?sslmode=require&channel_binding=require

Trei lucruri se sparg dacă îl lipești așa în `.env`:

1. Schema e `postgresql://`, deci SQLAlchemy alege driverul sincron `psycopg2`
   (neinstalat) în loc de `asyncpg`. Trebuie `postgresql+asyncpg://`.
2. `sslmode` și `channel_binding` sunt parametri libpq. `asyncpg` nu-i cunoaște;
   SQLAlchemy îi pasează mai departe ca argumente de conexiune și pică cu un
   `TypeError` care nu spune nimic despre cauza reală.
3. Endpoint-ul `-pooler` e PgBouncer în mod tranzacție. `asyncpg` folosește
   implicit prepared statements cu nume, care nu supraviețuiesc reciclării
   conexiunii — apare `InvalidSQLStatementNameError`, intermitent, de obicei
   după ce merge de câteva ori. De aia cache-ul se stinge din două locuri:
   `statement_cache_size` (nivel asyncpg) și `prepared_statement_cache_size`
   (nivel dialect SQLAlchemy).

Funcția de mai jos primește orice formă și scoate una care merge, ca să poți
lipi linia din consola Neon fără s-o repari de mână.
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Parametri libpq pe care asyncpg nu-i acceptă ca argumente de conexiune.
# `sslmode` nu se pierde — se traduce în `ssl`, mai jos.
PARAMETRI_LIBPQ = {"sslmode", "channel_binding", "connect_timeout", "application_name"}

# sslmode (libpq) -> ssl (asyncpg)
TRADUCERE_SSL = {
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
    "prefer": "prefer",
    "allow": "prefer",
    "disable": "disable",
}


class ConfigurareLipsa(RuntimeError):
    """DATABASE_URL lipsește sau e nefolosibil."""


def normalizeaza_url(url: str) -> tuple[str, dict[str, object]]:
    """Întoarce `(url_sqlalchemy, connect_args)` pornind de la orice formă de URL Postgres.

    Idempotentă: un URL deja normalizat trece neatins.
    """
    parti = urlsplit(url.strip())

    if not parti.scheme:
        raise ConfigurareLipsa(
            f"DATABASE_URL nu arată a URL: {url[:40]!r}…\n"
            "Aștept ceva de forma postgresql://user:parola@host/db"
        )

    # 1. Driverul asincron, fără să stric un `+asyncpg` deja pus.
    if parti.scheme in ("postgres", "postgresql"):
        schema = "postgresql+asyncpg"
    elif parti.scheme.startswith("postgresql+"):
        schema = parti.scheme
    else:
        raise ConfigurareLipsa(
            f"Schema {parti.scheme!r} nu e Postgres. Neon dă postgresql://…"
        )

    if schema != "postgresql+asyncpg":
        raise ConfigurareLipsa(
            f"Driverul {schema!r} e sincron. SQLAlchemySession cere un engine "
            "asincron — folosește postgresql+asyncpg://"
        )

    # 2. Scot parametrii libpq, traduc sslmode în ssl.
    interogare = dict(parse_qsl(parti.query, keep_blank_values=True))
    sslmode = interogare.get("sslmode")
    pastrate = {k: v for k, v in interogare.items() if k not in PARAMETRI_LIBPQ}

    connect_args: dict[str, object] = {}
    if sslmode:
        traducere = TRADUCERE_SSL.get(sslmode.lower())
        if traducere is None:
            raise ConfigurareLipsa(f"sslmode={sslmode!r} necunoscut")
        if traducere != "disable":
            connect_args["ssl"] = traducere
    elif ".neon.tech" in (parti.hostname or ""):
        # Neon cere TLS oricum; dacă lipsește din URL, îl pun eu.
        connect_args["ssl"] = "require"

    # 3. Prepared statements stinse. Le sting mereu, nu doar pe `-pooler`:
    #    câștigul lor la volumul ăsta e nemăsurabil, iar când greșești detecția
    #    eroarea apare intermitent, în producție, și pare a fi altceva.
    connect_args["statement_cache_size"] = 0
    pastrate["prepared_statement_cache_size"] = "0"

    url_final = urlunsplit(
        (schema, parti.netloc, parti.path, urlencode(pastrate), parti.fragment)
    )
    return url_final, connect_args


def ia_url_bazei() -> tuple[str, dict[str, object]]:
    """Citește DATABASE_URL din mediu și îl normalizează."""
    brut = os.getenv("DATABASE_URL")
    if not brut:
        raise ConfigurareLipsa(
            "Lipsește DATABASE_URL.\n"
            "Copiază .env.example în .env și pune acolo șirul din consola Neon.\n"
            "Poți lipi forma lor cu sslmode=require — o normalizez eu."
        )
    return normalizeaza_url(brut)


def descrie(url: str) -> str:
    """Descriere fără parolă, pentru afișat în terminal."""
    parti = urlsplit(url)
    gazda = parti.hostname or "?"
    baza = parti.path.lstrip("/") or "?"
    pooled = "-pooler" in gazda
    return f"{gazda}/{baza}" + ("  (endpoint pooled)" if pooled else "  (direct)")
