"""Criteriul Deciziei 6: serverul `content-data` răspunde peste HTTP.

    uv run python -m mcp_server.server     (în alt terminal, lăsat pornit)
    uv run python proba_mcp.py

Verifică trei lucruri, în ordinea în care contează:

1. **Exact cinci unelte**, cu numele din plan. Dacă apare alta, sau dacă apare
   vreuna cu „sql” în nume, proba pică — regula 1 nu e o preferință.
2. **`cauta_in_carti` întoarce pasaje cu proveniență.** Nu e destul să întoarcă
   text: fără titlu și pagină, pasajul nu poate ajunge pe câmpul `sursa`.
3. **`cauta_pe_internet` întoarce unghiuri și linkurile surselor.**
4. **Uneltele de scriere există și cer ce trebuie.** Nu le cheamă — o probă nu
   are ce căuta în tabelul `postari`. Se probează cap-coadă la Decizia 7.
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

ASTEPTATE = {
    "cauta_in_carti",
    "cauta_pe_internet",
    "listeaza_postari",
    "save_postare",
    "update_profil",
}
INTREBARE = "vinovăția de a spune nu"
INTREBARE_WEB = "burnout și limite personale — ce se discută acum"


def continut(rezultat) -> object:
    """Ce a întors unealta, ca obiect Python.

    `content` vine ca un TextContent per element, deci pentru o listă ar trebui
    lipite la loc. `structured_content` are răspunsul întreg, într-o singură
    bucată — pentru o listă, sub cheia `result`.
    """
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

    # 30 de secunde, nu 5 cât e implicit: `cauta_in_carti` cheamă întâi OpenAI
    # pentru embedding și abia apoi Neon. La primul apel, cu conexiunile reci,
    # cele două puse cap la cap trec lejer de cinci secunde.
    server = MCPServerStreamableHttp(
        params={"url": URL}, name="content-data", client_session_timeout_seconds=90
    )
    try:
        await server.connect()
    except Exception as e:  # noqa: BLE001
        print(f"Nu răspunde nimic la {URL} ({type(e).__name__}).", file=sys.stderr)
        print("Pornește întâi:  uv run python -m mcp_server.server", file=sys.stderr)
        return 1

    picat = 0
    try:
        unelte = {u.name: u for u in await server.list_tools()}
        print(f"Unelte: {', '.join(sorted(unelte))}\n")

        lipsa = ASTEPTATE - set(unelte)
        peste = set(unelte) - ASTEPTATE
        if lipsa or peste:
            print(f"✗ unelte: lipsesc {lipsa or '—'}, în plus {peste or '—'}")
            picat += 1
        else:
            print("✓ exact cele cinci unelte din plan")

        if any("sql" in nume.lower() for nume in unelte):
            print("✗ există o unealtă cu „sql” în nume — regula 1")
            picat += 1

        # 1. Căutarea în cărți
        pasaje = continut(
            await server.call_tool("cauta_in_carti", {"descriere": INTREBARE, "limit": 5})
        )
        print(f"\n„{INTREBARE}” → {len(pasaje)} pasaje")
        cu_reper = 0
        for p in pasaje:
            reper = (
                f"pagina {p['pagina']}"
                if p["pagina"]
                else (f"capitolul {p['capitol']}" if p["capitol"] else "fără reper")
            )
            cu_reper += bool(p["pagina"] or p["capitol"])
            print(f"  [{p['scor']:.3f}] {p['titlu']} — {p['autor']}, {reper}")
            print(f"          {p['text'][:90].strip()}…")

        if not pasaje:
            print("✗ căutarea n-a întors nimic")
            picat += 1
        elif cu_reper < len(pasaje):
            print(f"✗ {len(pasaje) - cu_reper} pasaje fără niciun reper de citare")
            picat += 1
        else:
            print("✓ fiecare pasaj știe din ce carte și de unde vine")

        # 2. Căutarea pe internet
        web = continut(
            await server.call_tool(
                "cauta_pe_internet", {"descriere": INTREBARE_WEB, "limit": 3}
            )
        )
        print(f"\nWeb: {web['tema']}")
        print(f"  {web['unghiuri'][:180].strip()}…")
        for sursa in web["surse"]:
            print(f"  - {sursa['titlu']}: {sursa['url']}")
        if not web["unghiuri"] or not web["surse"]:
            print("✗ căutarea web n-a întors unghiuri cu surse")
            picat += 1
        elif any(not s.get("titlu") or not s.get("url") for s in web["surse"]):
            print("✗ o sursă web nu are titlu și URL")
            picat += 1
        else:
            print("✓ căutarea web întoarce unghiuri cu linkurile surselor")

        # 3. Postările deja scrise
        postari = continut(await server.call_tool("listeaza_postari", {"limit": 3}))
        print(f"\nUltimele postări: {len(postari)}")
        for p in postari:
            print(f"  {p['data']}  {p['titlu'][:58]}")
        if not postari:
            print("✗ n-a întors nicio postare, deși seed-ul a pus 26")
            picat += 1
        else:
            print("✓ postările se citesc")

        # 4. Uneltele de scriere — se verifică forma, nu se cheamă
        print()
        for nume in ("save_postare", "update_profil"):
            ceruti = set(unelte[nume].input_schema.get("required", []))
            print(f"  {nume}: cere {', '.join(sorted(ceruti))}")
        if "sursa" not in set(unelte["save_postare"].input_schema.get("required", [])):
            print("✗ save_postare acceptă o postare fără `sursa` — regula 8")
            picat += 1
        else:
            print("✓ save_postare nu primește o postare fără sursă")

    finally:
        await server.cleanup()

    print(f"\n{'PICAT: ' + str(picat) + ' verificări' if picat else 'TRECUT'}")
    return 1 if picat else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
