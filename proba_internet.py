"""Proba izolată pentru `cauta_pe_internet` — fără acces la cărți sau postări.

    uv run python -m mcp_server.server     (în alt terminal)
    uv run python proba_internet.py

Trimite la OpenAI numai tema generică de mai jos. Verifică contractul MCP,
unghiurile și proveniența web; nu citește nimic din Neon.
"""

from __future__ import annotations

import asyncio
import json
import sys

from agents.mcp import MCPServerStreamableHttp
from dotenv import load_dotenv

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

URL = "http://127.0.0.1:8765/mcp"
TEMA = "burnout și limite personale — teme actuale pentru conținut social"


def continut(rezultat) -> object:
    structurat = rezultat.structured_content
    if isinstance(structurat, dict) and set(structurat) == {"result"}:
        return structurat["result"]
    if structurat is not None:
        return structurat
    texte = [c.text for c in rezultat.content if getattr(c, "type", None) == "text"]
    if not texte:
        return None
    decodat = json.loads("".join(texte))
    return decodat.get("result", decodat) if isinstance(decodat, dict) else decodat


async def main() -> int:
    load_dotenv()
    server = MCPServerStreamableHttp(
        params={"url": URL},
        name="content-data",
        client_session_timeout_seconds=90,
    )
    try:
        await server.connect()
        unelte = {u.name: u for u in await server.list_tools()}
        if "cauta_pe_internet" not in unelte:
            print("✗ `cauta_pe_internet` nu este în contractul MCP")
            return 1

        rezultat = continut(
            await server.call_tool("cauta_pe_internet", {"descriere": TEMA, "limit": 3})
        )
        surse = rezultat.get("surse", [])
        verificari = [
            (rezultat.get("status") == "ok", "statusul este ok"),
            (bool(rezultat.get("unghiuri")), "a întors unghiuri"),
            (bool(surse), "a întors surse"),
            (
                all(s.get("titlu") and s.get("url", "").startswith("http") for s in surse),
                "fiecare sursă are titlu și URL",
            ),
            ("Nu prelua" in rezultat.get("regula", ""), "a întors regula anti-fapte"),
        ]
        picat = 0
        for reusit, mesaj in verificari:
            picat += not reusit
            print(f"{'✓' if reusit else '✗'} {mesaj}")
        print(f"Surse: {len(surse)}")
        for sursa in surse:
            print(f"  - {sursa['titlu']}: {sursa['url']}")
        return 1 if picat else 0
    finally:
        await server.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
