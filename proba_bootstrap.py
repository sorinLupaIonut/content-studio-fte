"""Probă sigură: contractul MCP și profilul de pornire, fără model sau scrieri.

    uv run python -m mcp_server.server     (în alt terminal)
    uv run python proba_bootstrap.py

Citește profilul din Neon prin resursa MCP, dar nu îi afișează conținutul și nu
îl trimite la OpenAI. Verifică și faptul că agentul vede exact cele cinci unelte.
"""

from __future__ import annotations

import asyncio
import sys

from agents.mcp import MCPServerStreamableHttp
from dotenv import load_dotenv

from worker import MCP_TIMEOUT, MCP_URL, citeste_profil

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

ASTEPTATE = {
    "cauta_in_carti",
    "cauta_pe_internet",
    "listeaza_postari",
    "save_postare",
    "update_profil",
}


async def main() -> int:
    load_dotenv()
    server = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    picat = 0
    try:
        await server.connect()
        unelte = {u.name for u in await server.list_tools()}
        nume, profil = await citeste_profil(server)

        verificari = [
            (unelte == ASTEPTATE, f"exact cele cinci unelte: {sorted(unelte)}"),
            (not any("sql" in u.lower() for u in unelte), "nicio unealtă SQL"),
            (bool(nume.strip()), "profilul are numele clientei"),
            (len(profil) > 1_000, f"profilul a venit prin MCP: {len(profil):,} caractere"),
        ]
        for reusit, mesaj in verificari:
            picat += not reusit
            print(f"{'✓' if reusit else '✗'} {mesaj}")
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await server.cleanup()

    return 1 if picat else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
