"""Content Worker — Decizia 3: memorie persistentă și profilul din bază.

Ce s-a schimbat față de Decizia 0:
  · conversația trăiește în Neon, prin `SQLAlchemySession`, deci ține minte
    turele și după ce închizi terminalul;
  · profilul Viorelei se citește din tabelul `client` la pornire și intră
    ÎNTREG în system prompt, ca șir — §3, decizia de plasare: nu ca fișier,
    nu ca unealtă pe care modelul o cheamă dacă vrea. E singurul material în
    care se scrie, de aia stă în Postgres și nu în embeddings;
  · fiecare sesiune primește un rând în `conversations` — foaia de gardă pe
    care SDK-ul nu o ține: cine, când, rezumat. Se leagă de transcriere prin
    acelaşi `session_id`.

Ce NU e aici, și când vine:
  Decizia 4  — sub-agentul `propune_postari`, chemat cu `Agent.as_tool()`
  Decizia 5  — cărțile în `documents` + `embeddings`
  Decizia 6  — serverul MCP `content-data`, cu cele cinci unelte
  Decizia 8  — scrierile în `audit_log` la fiecare graniță

Rulează:  uv run worker.py          (reia ultima conversație)
          uv run worker.py --nou    (începe una nouă)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date

from agents import Agent, Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, descrie, ia_url_bazei

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")
CLIENT_SLUG = "viorela"

INSTRUCTIUNI_BAZA = (
    "Ești asistentul de conținut al Viorelei — life coach pentru femei care vor să "
    "iasă din people pleasing, burnout și autosabotaj.\n\n"
    "Răspunzi în română, cu diacritice, la persoana a II-a singular, simplu și cald, "
    "fără termeni tehnici și fără jargon de marketing.\n\n"
    "Ești la Decizia 3: ai profilul ei încărcat mai jos și ții minte conversația, "
    "dar încă nu ai unelte — nu poți căuta în cărți, nu poți salva postări și nu "
    "poți modifica profilul. Dacă ți se cere una dintre astea, spune limpede că "
    "urmează, și nu improviza.\n\n"
    "Nu inventezi niciodată rezultate, cifre sau testimoniale care nu sunt în profil."
)

SQL_CLIENT = "SELECT id, nume, profil_md FROM client WHERE slug = $1"
SQL_ULTIMA = """
SELECT session_id FROM conversations
 WHERE user_id = $1 ORDER BY started_at DESC LIMIT 1
"""
SQL_CONV_NOUA = """
INSERT INTO conversations (session_id, user_id, metadata)
VALUES ($1, $2, $3::jsonb)
ON CONFLICT (session_id) DO NOTHING
"""


async def porneste(engine, nou: bool) -> tuple[str, str, str]:
    """Întoarce (session_id, nume_client, profil_md). Creează rândul din `conversations`."""
    async with engine.begin() as conn:
        brut = (await conn.get_raw_connection()).driver_connection

        rand = await brut.fetchrow(SQL_CLIENT, CLIENT_SLUG)
        if rand is None:
            raise RuntimeError(
                f"Nu există clienta {CLIENT_SLUG!r} în tabelul `client`.\n"
                "Rulează întâi:  uv run python -m db.seed"
            )

        session_id = None if nou else await brut.fetchval(SQL_ULTIMA, CLIENT_SLUG)
        if session_id is None:
            session_id = f"{CLIENT_SLUG}-{date.today():%Y%m%d}-{uuid.uuid4().hex[:8]}"
            await brut.execute(SQL_CONV_NOUA, session_id, CLIENT_SLUG, "{}")

    return session_id, rand["nume"], rand["profil_md"]


async def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("Lipsește OPENAI_API_KEY. Copiază .env.example în .env.", file=sys.stderr)
        return 1

    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(f"{e}", file=sys.stderr)
        return 1

    nou = "--nou" in sys.argv
    engine = create_async_engine(url, connect_args=connect_args)

    try:
        session_id, nume, profil_md = await porneste(engine, nou)
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        await engine.dispose()
        return 1

    worker = Agent(
        name="Content Worker",
        model=MODEL,
        instructions=f"{INSTRUCTIUNI_BAZA}\n\n--- PROFILUL CLIENTEI ---\n{profil_md}",
    )

    # create_tables=True: `agent_sessions` și `agent_messages` se fac singure, la
    # prima rulare. Nu-s în schema.sql — §3, „nu se proiectează și nu se scriu de mână".
    #
    # ensure_ascii=False e obligatoriu, nu cosmetic: implicit SDK-ul escapează
    # non-ASCII la serializare, deci tot ce e scris în română ar ajunge în
    # `agent_messages` ca „ă" în loc de „ă" — nefolosibil când te uiți în tabel.
    sesiune = SQLAlchemySession(
        session_id,
        engine=engine,
        create_tables=True,
        ensure_ascii=False,
    )

    print(f"Content Worker · {MODEL} · Decizia 3")
    print(f"Bază     : {descrie(url)}")
    print(f"Clientă  : {nume} · profil {len(profil_md):,} caractere în system prompt")
    print(f"Sesiune  : {session_id}{'  (nouă)' if nou else '  (reluată)'}")
    print("Scrie un mesaj, sau „iesire” ca să termini.\n")

    try:
        while True:
            try:
                mesaj = input("tu> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not mesaj:
                continue
            if mesaj.lower() in {"iesire", "ieșire", "exit", "quit"}:
                break

            rezultat = await Runner.run(worker, mesaj, session=sesiune)
            print(f"\nworker> {rezultat.final_output}\n")
    finally:
        await engine.dispose()

    print(f"Conversația a rămas în bază: session_id = {session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
