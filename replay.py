"""Rejoacă o conversație din urma ei. Decizia 8.

    uv run python replay.py                 ultima conversație
    uv run python replay.py <session_id>    una anume
    uv run python replay.py --lista         ce conversații există

Criteriul: **poți reconstrui ce a făcut, fără să rulezi modelul.** Nu se cheamă
niciun API aici — se citește `audit_log` și `capability_invocations`, atât.

Dacă o tură apare cu `message_received` dar fără `message_sent`, aia e o tură
care a picat, și se vede. Ăsta e și motivul pentru care urma se scrie înainte de
rulare, nu după.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, ia_url_bazei

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

SQL_LISTA = """
SELECT c.session_id, c.started_at, count(a.id) AS randuri
  FROM conversations c
  LEFT JOIN audit_log a ON a.conversation_id = c.session_id
 GROUP BY c.session_id, c.started_at
 ORDER BY c.started_at DESC
 LIMIT 20
"""

SQL_ULTIMA = """
SELECT conversation_id FROM audit_log
 WHERE conversation_id IS NOT NULL
 ORDER BY created_at DESC LIMIT 1
"""

SQL_URMA = """
SELECT created_at, actor, action, target, payload, result
  FROM audit_log
 WHERE conversation_id = $1
 ORDER BY id
"""

SQL_CAPABILITATI = """
SELECT capability, status, count(*) AS de_cate_ori
  FROM capability_invocations
 WHERE conversation_id = $1
 GROUP BY capability, status
 ORDER BY capability
"""

#: Cum se citește fiecare acțiune. Ce nu e aici se tipărește brut.
SEMNE = {
    "message_received": ("tu>", "text"),
    "message_sent": ("worker>", "text"),
    "skill_activated": ("  skill", "skill"),
    "capability_invoked": ("  unealtă", None),
    "postare_aleasa": ("  a ales", "titlu"),
    "propuneri_generate": ("  a scos propuneri", "cate"),
    "guardrail_tripped": ("  A PICAT", "mesaj"),
    "postare_salvata": ("  SALVAT", "titlu"),
    "profil_actualizat": ("  PROFIL SCHIMBAT", "sectiune"),
    "aprobare_ceruta": ("  poartă: cerut", None),
    "aprobare_respinsa": ("  poartă: RESPINS", None),
}


def scurt(text: object, latime: int = 96) -> str:
    unul = " ".join(str(text).split())
    return textwrap.shorten(unul, latime, placeholder="…") if unul else ""


def descrie(rand) -> str:
    actiune = rand["action"]
    payload = rand["payload"] if isinstance(rand["payload"], dict) else {}
    eticheta, cheie = SEMNE.get(actiune, (f"  {actiune}", None))

    if actiune == "capability_invoked":
        argumente = ", ".join(f"{k}={scurt(v, 40)}" for k, v in payload.items())
        return f"{eticheta} {rand['target']}({argumente})"

    valoare = payload.get(cheie) if cheie else json.dumps(payload, ensure_ascii=False)
    return f"{eticheta} {scurt(valoare)}"


async def main() -> int:
    load_dotenv()
    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(f"{e}", file=sys.stderr)
        return 1

    argument = sys.argv[1] if len(sys.argv) > 1 else None
    engine = create_async_engine(url, connect_args=connect_args)

    try:
        async with engine.begin() as conn_sa:
            conn = (await conn_sa.get_raw_connection()).driver_connection

            if argument == "--lista":
                for r in await conn.fetch(SQL_LISTA):
                    print(f"{r['started_at']:%Y-%m-%d %H:%M}  {r['session_id']}  "
                          f"{r['randuri']:>4} rânduri de urmă")
                return 0

            sesiune = argument or await conn.fetchval(SQL_ULTIMA)
            if not sesiune:
                print("Nu există nicio urmă în `audit_log`. Rulează întâi worker-ul.")
                return 1

            urma = await conn.fetch(SQL_URMA, sesiune)
            capabilitati = await conn.fetch(SQL_CAPABILITATI, sesiune)
    finally:
        await engine.dispose()

    if not urma:
        print(f"Nicio urmă pentru {sesiune}.")
        return 1

    print(f"Conversația {sesiune}")
    print(f"{len(urma)} rânduri de urmă, între {urma[0]['created_at']:%H:%M:%S} "
          f"și {urma[-1]['created_at']:%H:%M:%S}\n")
    print("─" * 100)

    ture = 0
    for rand in urma:
        if rand["action"] == "message_received":
            ture += 1
            print()
        print(descrie(rand))

    print("─" * 100)
    print(f"\n{ture} ture.")
    if capabilitati:
        print("Unelte chemate:")
        for r in capabilitati:
            print(f"  {r['capability']:<28} {r['status']:<8} × {r['de_cate_ori']}")
    else:
        print("Nicio unealtă chemată.")

    primite = sum(r["action"] == "message_received" for r in urma)
    trimise = sum(r["action"] == "message_sent" for r in urma)
    if primite != trimise:
        print(f"\n⚠ {primite - trimise} ture fără răspuns — au picat pe drum.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
