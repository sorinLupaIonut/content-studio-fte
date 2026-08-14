"""Aplică db/schema.sql pe baza din DATABASE_URL. Decizia 3.

    uv run python -m db.apply

Idempotent — totul e `CREATE ... IF NOT EXISTS`, deci rulabil de câte ori vrei.
La final tipărește ce tabele există, ca să vezi criteriul de acceptare al
Deciziei 3 cu ochii tăi, nu pe încredere.

De ce nu merge prin SQLAlchemy direct: `schema.sql` are mai multe instrucțiuni
într-un fișier, iar dialectul asyncpg trimite fiecare `text()` ca prepared
statement — și un prepared statement acceptă exact o comandă. Coborât la
conexiunea brută asyncpg, `execute()` rulează scriptul întreg ca simple query.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, descrie, ia_url_bazei

# Consola Windows e cp1252; fără asta, primul „ă" din „Bază" omoară rularea.
for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = Path(__file__).parent / "schema.sql"

# Ce trebuie să existe la final. Primele cinci sunt coloana vertebrală din
# Concept 7, ultimele două sunt domeniul din §3. `agent_sessions` și
# `agent_messages` NU sunt aici: le face SQLAlchemySession la prima rulare
# a worker-ului, nu scriptul ăsta.
ASTEPTATE = [
    "conversations",
    "documents",
    "embeddings",
    "audit_log",
    "capability_invocations",
    "client",
    "postari",
]

INTEROGARE_TABELE = """
SELECT c.relname AS tabel,
       COALESCE(s.n_live_tup, 0) AS randuri
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
 WHERE n.nspname = 'public' AND c.relkind = 'r'
 ORDER BY c.relname
"""


async def main() -> int:
    load_dotenv()

    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(f"{e}", file=sys.stderr)
        return 1

    print(f"Bază : {descrie(url)}")
    print(f"Schemă: {SCHEMA}")

    sql = SCHEMA.read_text(encoding="utf-8")
    engine = create_async_engine(url, connect_args=connect_args, echo=False)

    try:
        async with engine.begin() as conn:
            brut = await conn.get_raw_connection()
            await brut.driver_connection.execute(sql)

        async with engine.connect() as conn:
            brut = await conn.get_raw_connection()
            randuri = await brut.driver_connection.fetch(INTEROGARE_TABELE)
    except Exception as e:  # noqa: BLE001 — vreau mesajul brut, oricare ar fi
        print(f"\nA picat aplicarea schemei:\n  {type(e).__name__}: {e}", file=sys.stderr)
        if "vector" in str(e).lower():
            print(
                "\nDacă e despre extensia `vector`: pe Neon se activează cu\n"
                "  CREATE EXTENSION vector;\n"
                "din SQL Editor-ul lor, iar contul trebuie să aibă drept de a crea extensii.",
                file=sys.stderr,
            )
        return 1
    finally:
        await engine.dispose()

    gasite = {r["tabel"]: r["randuri"] for r in randuri}

    print("\nTabele în public:")
    for nume in ASTEPTATE:
        semn = "✓" if nume in gasite else "✗ LIPSEȘTE"
        nr = f"{gasite.get(nume, 0):>6} rânduri" if nume in gasite else ""
        print(f"  {semn:<11} {nume:<24} {nr}")

    altele = sorted(set(gasite) - set(ASTEPTATE))
    if altele:
        print("\nÎn plus (create de SDK sau de tine):")
        for nume in altele:
            print(f"  ·           {nume:<24} {gasite[nume]:>6} rânduri")

    lipsa = [n for n in ASTEPTATE if n not in gasite]
    if lipsa:
        print(f"\nLipsesc: {', '.join(lipsa)}", file=sys.stderr)
        return 1

    print("\nSchema e aplicată. Următorul pas: uv run python -m db.seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
