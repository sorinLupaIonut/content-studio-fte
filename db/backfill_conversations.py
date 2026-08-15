"""Completează conversațiile vechi din audit, fără niciun apel la model.

Implicit doar arată ce ar modifica. Pentru aplicare:

    uv run python -m db.backfill_conversations --aplica

Conversațiile cu activitate în ultima oră sunt sărite, ca să nu închidem din
greșeală un worker care încă rulează. Ora de închidere a celor istorice este
ultima lor activitate cunoscută și este marcată explicit ca estimată.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from conversation_state import actualizeaza_conversatia
from db.config import ConfigurareLipsa, descrie, ia_url_bazei

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

SQL_CANDIDATE = """
WITH activitate AS (
    SELECT conversation_id, max(created_at) AS ultima_activitate
      FROM audit_log
     WHERE conversation_id IS NOT NULL
     GROUP BY conversation_id
)
SELECT c.session_id,
       COALESCE(a.ultima_activitate, c.started_at) AS ultima_activitate
  FROM conversations c
  LEFT JOIN activitate a ON a.conversation_id = c.session_id
 WHERE (c.summary IS NULL OR c.metadata = '{}'::jsonb OR c.ended_at IS NULL)
   AND COALESCE(a.ultima_activitate, c.started_at)
       < NOW() - ($1::double precision * INTERVAL '1 hour')
 ORDER BY c.started_at
"""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplica", action="store_true", help="scrie modificările în Neon")
    parser.add_argument(
        "--ore-inactive",
        type=float,
        default=1.0,
        help="sari conversațiile mai noi de acest prag (implicit: 1 oră)",
    )
    argumente = parser.parse_args()

    if argumente.ore_inactive < 0:
        parser.error("--ore-inactive trebuie să fie cel puțin 0")

    load_dotenv()
    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(e, file=sys.stderr)
        return 1

    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            brut = (await conn.get_raw_connection()).driver_connection
            candidate = await brut.fetch(SQL_CANDIDATE, argumente.ore_inactive)

        print(f"Bază: {descrie(url)}")
        print(f"Conversații istorice de completat: {len(candidate)}")
        if not argumente.aplica:
            for rand in candidate:
                print(f"  · {rand['session_id']}  ultima activitate: {rand['ultima_activitate']}")
            print("\nNu am scris nimic. Adaugă --aplica pentru completare.")
            return 0

        for rand in candidate:
            await actualizeaza_conversatia(
                engine,
                rand["session_id"],
                model=None,
                status="inchisa",
                inchide=True,
                inchidere_estimata=True,
                motiv_inchidere="completare_din_audit",
                moment_inchidere=rand["ultima_activitate"],
            )
            print(f"  ✓ {rand['session_id']}")
    except Exception as e:  # noqa: BLE001
        print(f"Completarea a picat: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"\nCompletate: {len(candidate)}. Nu s-a făcut niciun apel la OpenAI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
