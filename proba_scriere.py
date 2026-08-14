"""Proba scurtă pentru legătura scriere → conversație → audit.

Cere serverul pornit și nu cheamă modelul. Scrie o postare dummy într-o
conversație nouă, verifică exact un apel blocat și unul reușit, apoi șterge toate
rândurile acelei conversații. Nu atinge postările Viorelei.
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

from agents.mcp import MCPServerStreamableHttp
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from audit import Audit
from db.config import ia_url_bazei
from mcp_server.protocol import CONVERSATION_HEADER
from worker import MCP_URL, porneste

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")


def rezultat_apel(call_id: str, argumente: dict, rezultat: object):
    """Forma minimă pe care `Audit.tura` o citește din SDK."""
    apel = SimpleNamespace(
        type="tool_call_item",
        raw_item=SimpleNamespace(
            name="save_postare",
            arguments=json.dumps(argumente, ensure_ascii=False),
            call_id=call_id,
        ),
    )
    iesire = SimpleNamespace(
        type="tool_call_output_item",
        raw_item=SimpleNamespace(call_id=call_id),
        output=rezultat,
    )
    return SimpleNamespace(new_items=[apel, iesire], final_output="")


async def curata(engine, session_id: str) -> None:
    """Doar rândurile conversației de test, în ordinea sigură pentru FK-uri."""
    async with engine.begin() as conn_sa:
        conn = (await conn_sa.get_raw_connection()).driver_connection
        await conn.execute("DELETE FROM postari WHERE conversation_id = $1", session_id)
        await conn.execute("DELETE FROM audit_log WHERE conversation_id = $1", session_id)
        await conn.execute(
            "DELETE FROM capability_invocations WHERE conversation_id = $1", session_id
        )
        await conn.execute("DELETE FROM conversations WHERE session_id = $1", session_id)


async def main() -> int:
    load_dotenv()
    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    session_id = await porneste(engine, nou=True)
    urma = Audit(url, connect_args)
    server = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {CONVERSATION_HEADER: session_id},
        },
        name="content-data",
        client_session_timeout_seconds=30,
    )

    argumente = {
        "titlu": "PROBĂ — se șterge automat",
        "pilon": "Conexiune",
        "format": "Reel",
        "hook": "Hook de probă",
        "tip_hook": "CONTRAST",
        "script": "Script de probă.",
        "caption": "Caption de probă?",
        "hashtaguri": "#proba #limite #continut",
        "cta": "CTA de probă.",
        "sursa": "din memorie 🧠 (profil + avatar), fără sursă externă",
    }
    picat = 0

    try:
        await server.connect()

        call_blocat = "proba-blocata"
        motiv = "Viorela n-a aprobat scrierea."
        await urma.capabilitate_blocata(
            session_id, "save_postare", argumente, motiv, call_blocat
        )
        await urma.tura(
            session_id, rezultat_apel(call_blocat, argumente, motiv)
        )

        raspuns = await server.call_tool("save_postare", argumente)
        rezultat = raspuns.structured_content or {}
        await urma.tura(
            session_id, rezultat_apel("proba-aprobata", argumente, rezultat)
        )

        async with engine.begin() as conn_sa:
            conn = (await conn_sa.get_raw_connection()).driver_connection
            postari = await conn.fetchval(
                "SELECT count(*) FROM postari WHERE conversation_id = $1", session_id
            )
            actiuni = await conn.fetch(
                """SELECT action FROM audit_log
                    WHERE conversation_id = $1 ORDER BY id""",
                session_id,
            )
            statusuri = await conn.fetch(
                """SELECT status FROM capability_invocations
                    WHERE conversation_id = $1 AND capability = 'tool:save_postare'
                    ORDER BY status""",
                session_id,
            )

        actiuni = [r["action"] for r in actiuni]
        statusuri = [r["status"] for r in statusuri]
        verificari = [
            (postari == 1, f"o singură postare legată de conversație: {postari}"),
            (
                actiuni.count("postare_salvata") == 1,
                f"audit tranzacțional legat de conversație: {actiuni.count('postare_salvata')}",
            ),
            (
                actiuni.count("postare_aleasa") == 1,
                f"doar apelul reușit e postare aleasă: {actiuni.count('postare_aleasa')}",
            ),
            (
                statusuri == ["blocked", "ok"],
                f"capabilitatea are blocked + ok: {statusuri}",
            ),
        ]
        for reusit, mesaj in verificari:
            picat += not reusit
            print(f"{'✓' if reusit else '✗'} {mesaj}")
    finally:
        await server.cleanup()
        await urma.inchide()
        await curata(engine, session_id)
        await engine.dispose()
        print("✓ rândurile de probă au fost șterse")

    return 1 if picat else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
