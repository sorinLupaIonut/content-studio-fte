"""Proba cap-coadă: skill-uri în sandbox, date prin MCP, poartă și urmă.

Cere serverul pornit:  uv run python -m mcp_server.server

Nouă ture, pe drumul lung, fiindcă acolo se vede dacă skill-urile chiar sunt
citite:

  1. „vreau ceva despre limite"   → întreabă formatul
  2. „reel"                       → întreabă pilonul
  3. „conexiune"                  → întreabă sursa
  4. „din cărți"                  → propune 3–4 titluri, nu lista de 17
  5. „caută în toate"             → cheamă `cauta_in_carti`, apoi scoate cele zece
  6. „dezvoltă a treia…"          → al doilea skill: postarea întreagă
  7. „da, salveaz-o"              → poarta îl oprește, iar noi îl RESPINGEM
  8. „ba da, sunt sigură"         → poarta îl oprește, iar noi APROBĂM
  9. „acum și a șaptea"           → încă una, FĂRĂ să regenereze lista

Ce probează fiecare decizie:

- **4 și 5** — progressive disclosure. Că se propun 3–4 titluri și niciodată
  toate șaptesprezece e scris NUMAI în `references/surse.md`; nu e în `SKILL.md`
  și nu e în system prompt. Dacă agentul face asta, lanțul index → SKILL.md →
  references funcționează. Dacă nu, skill-urile sunt decor.
- **6** — `cauta_in_carti` chiar e chemată. Mă uit în apelurile turei, nu în
  cuvintele răspunsului: un agent care *spune* că a căutat arată la fel.
- **7** — ciclul întreg, plus tura 9: a doua propunere din aceeași listă, fără
  să se regenereze nimic.
- **8** — urma. La final se poate rula `replay.py` pe sesiunea asta.
- **9** — poarta, în ambele sensuri: respins nu scrie nimic, aprobat scrie.

Postarea scrisă la tura 8 se șterge la final, ca proba să se poată rula de câte
ori vrei fără să adune ciorne în bază. Urma ei rămâne în audit pentru replay.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time

from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from audit import Audit
from db.config import ia_url_bazei
from worker import (
    MCP_URL,
    UNELTE_CU_POARTA,
    fa_sandbox,
    fa_worker,
    porneste,
    ruleaza_tura,
)
from mcp_server.protocol import CONVERSATION_HEADER

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

TURE = [
    "vreau ceva despre limite",
    "reel",
    "conexiune",
    "din cărți",
    "caută în toate",
    "dezvoltă a treia, cu contrastul",
    "da, e bună. salveaz-o",
    "ba da, sunt sigură. salveaz-o",
    "acum dezvoltă și a șaptea, tot cu contrastul",
]

#: Cele cinci tipuri, tolerant la diacritice — modelul scrie „CIFRĂ" sau „CIFRA".
TIPURI_HOOK = {
    "PROVOCARE": r"PROVOCARE",
    "CIFRĂ": r"CIFR[ĂA]",
    "SECRET": r"SECRET",
    "ÎNTREBARE": r"[ÎI]NTREBARE",
    "CONTRAST": r"CONTRAST",
}

#: Orice procent e un rezultat inventat — regula 7. Prinde clasa evidentă
#: („30% mai mult timp"), nu și pe cea vicleană („30 de minute de respiro").
#: Aia rămâne pentru setul de evaluare de la Decizia 10.
TIPAR_PROCENT = re.compile(r"\d\s*%|\bla sută\b", re.IGNORECASE)

#: „dacă nu răspunzi, folosesc X" — regula 9 o interzice explicit.
TIPAR_IMPLICIT = re.compile(
    r"dac[ăa] nu r[ăa]spunzi|folosesc implicit|implicit[,:]", re.IGNORECASE
)

TIPAR_NUMEROTARE = re.compile(r"^\s*(\d{1,2})[.)]", re.MULTILINE)


def numere_din(text: str) -> set[int]:
    """Numerele de propunere 1–10 găsite la început de rând."""
    return {int(n) for n in TIPAR_NUMEROTARE.findall(text) if 1 <= int(n) <= 10}


def gaseste_lista(raspunsuri: list[str]) -> tuple[int, str]:
    """Răspunsul care conține lista, plus indexul lui (de la 1).

    Nu presupun tura. Iau răspunsul cu cele mai multe numere distincte de
    propunere; la egalitate, ultimul, fiindcă ăla e cel mai probabil final.
    """
    scoruri = [(len(numere_din(r)), i) for i, r in enumerate(raspunsuri)]
    _, i = max(scoruri)
    return i + 1, raspunsuri[i]


def unelte_chemate(rezultat) -> list[str]:
    """Numele uneltelor chemate în tura asta.

    Mă uit în apelurile propriu-zise, nu în text: un agent care *spune* că a
    căutat în cărți și unul care chiar a căutat arată la fel în răspuns.
    """
    nume = []
    for element in rezultat.new_items:
        brut = getattr(element, "raw_item", None)
        if getattr(element, "type", "") == "tool_call_item" and hasattr(brut, "name"):
            nume.append(brut.name)
    return nume


class Portar:
    """Omul de la poartă, scriptat: primul „nu", apoi „da".

    Ambele sensuri într-o singură rulare — respins nu scrie nimic, aprobat
    scrie. E criteriul Deciziei 9, și n-are rost probat pe jumătate.
    """

    def __init__(self) -> None:
        self.cereri: list[tuple[str, bool]] = []

    async def __call__(self, nume: str, argumente: dict) -> tuple[bool, str]:
        aprobat = len(self.cereri) > 0
        self.cereri.append((nume, aprobat))
        print(f"   [poartă: {nume} → {'APROBAT' if aprobat else 'RESPINS'}]")
        if aprobat:
            return True, ""
        return False, "Viorela n-a aprobat scrierea. Întreab-o ce vrea schimbat."


async def ciornele_sesiunii_si_sterge(session_id: str) -> list[dict]:
    """Ce a scris proba în `postari`, apoi curăță exact rândurile sesiunii.

    Urma din audit rămâne intenționat, ca `replay.py` să poată reconstitui proba.
    """
    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            brut = (await conn.get_raw_connection()).driver_connection
            randuri = await brut.fetch(
                """SELECT id, titlu, tip_hook, sursa, length(script) AS script,
                          length(caption) AS caption, hashtaguri, cta
                     FROM postari
                    WHERE status = 'ciorna' AND conversation_id = $1""",
                session_id,
            )
            scrise = [dict(r) | {"id": str(r["id"])} for r in randuri]
            for r in scrise:
                await brut.execute("DELETE FROM postari WHERE id = $1::uuid", r["id"])
        return scrise
    finally:
        await engine.dispose()


async def urma_sesiunii(session_id: str) -> list[str]:
    """Acțiunile scrise în `audit_log` pentru sesiunea asta, în ordine."""
    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            brut = (await conn.get_raw_connection()).driver_connection
            randuri = await brut.fetch(
                "SELECT action FROM audit_log WHERE conversation_id = $1 ORDER BY id",
                session_id,
            )
        return [r["action"] for r in randuri]
    finally:
        await engine.dispose()


async def capabilitati_sesiune(session_id: str) -> list[tuple[str, str]]:
    """(capabilitate, status) pentru a distinge respins de executat."""
    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            brut = (await conn.get_raw_connection()).driver_connection
            randuri = await brut.fetch(
                """SELECT capability, status FROM capability_invocations
                    WHERE conversation_id = $1 ORDER BY created_at, id""",
                session_id,
            )
        return [(r["capability"], r["status"]) for r in randuri]
    finally:
        await engine.dispose()


async def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("Lipsește OPENAI_API_KEY.", file=sys.stderr)
        return 1

    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    session_id, _, profil_md = await porneste(engine, nou=True)
    async with engine.begin() as conn:
        brut = (await conn.get_raw_connection()).driver_connection
        titluri_carti = [
            r["title"]
            for r in await brut.fetch(
                "SELECT title FROM documents WHERE source = 'biblioteca' ORDER BY title"
            )
        ]
    await engine.dispose()

    date_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {CONVERSATION_HEADER: session_id},
        },
        name="content-data",
        client_session_timeout_seconds=30,
        require_approval={"always": {"tool_names": list(UNELTE_CU_POARTA)}},
    )
    try:
        await date_mcp.connect()
    except Exception as e:  # noqa: BLE001
        print(f"Nu răspunde nimic la {MCP_URL} ({type(e).__name__}).", file=sys.stderr)
        print("Pornește:  uv run python -m mcp_server.server", file=sys.stderr)
        return 1

    worker = fa_worker(profil_md, date_mcp)
    urma = Audit(url, connect_args)
    client, optiuni = fa_sandbox()
    portar = Portar()

    pornit = time.monotonic()
    sandbox = await client.create(options=optiuni)
    print(f"Sandbox pornit în {time.monotonic() - pornit:.0f}s")
    print(f"Profil: {len(profil_md):,} caractere · {len(titluri_carti)} cărți")
    print(f"Sesiune: {session_id}\n")

    config = RunConfig(sandbox=SandboxRunConfig(client=client, session=sandbox))
    istoric: list = []
    raspunsuri: list[str] = []
    chemate: list[str] = []

    try:
        for mesaj in TURE:
            t0 = time.monotonic()
            await urma.mesaj_primit(session_id, mesaj)
            print(f"tu> {mesaj}")

            rezultat = await ruleaza_tura(
                worker,
                istoric + [{"role": "user", "content": mesaj}],
                None,
                config,
                urma,
                session_id,
                portar,
            )

            istoric = rezultat.to_input_list()
            raspuns = str(rezultat.final_output)
            raspunsuri.append(raspuns)
            unelte = unelte_chemate(rezultat)
            chemate += unelte

            await urma.tura(session_id, rezultat)
            await urma.mesaj_trimis(session_id, raspuns)

            print(f"   ({time.monotonic() - t0:.0f}s)")
            if unelte:
                print(f"   [unelte: {', '.join(unelte)}]")
            print(f"worker> {raspuns}\n")
            print("-" * 72)
    finally:
        await client.delete(sandbox)
        await date_mcp.cleanup()
        await urma.inchide()

    print()
    print("=" * 72)
    greseli = 0

    def verifica(reusit: bool, eticheta: str) -> None:
        nonlocal greseli
        greseli += not reusit
        print(f"{'✓' if reusit else '✗'} {eticheta}")

    # Tura 4 — a citit references/surse.md? Acolo scrie „3–4 titluri, niciodată
    # lista de 17". Număr câte titluri reale din bibliotecă a numit.
    a_patra = raspunsuri[3].lower()
    numite = [t for t in titluri_carti if t.lower()[:24] in a_patra]
    verifica(
        3 <= len(numite) <= 4,
        f"tura 4: a propus {len(numite)} titluri din bibliotecă (aștept 3–4, nu 17)",
    )

    piloni_ceruti = ("Poziționare", "Educație", "Conexiune", "Conversie", "Magnetism")
    verifica(
        all(p in raspunsuri[1] for p in piloni_ceruti)
        and "Inspirație" not in raspunsuri[1],
        "tura 2 oferă exact vocabularul închis al celor 5 piloni",
    )
    surse_cerute = ("Cărți", "Internet", "Memorie", "Combinat")
    verifica(
        all(s in raspunsuri[2] for s in surse_cerute),
        "tura 3 oferă toate cele 4 surse, inclusiv Internet ca indisponibil azi",
    )

    verifica(
        "cauta_in_carti" in chemate,
        f"a chemat cauta_in_carti (unelte: {sorted(set(chemate)) or '—'})",
    )

    unde, lista = gaseste_lista(raspunsuri)
    distincte = numere_din(lista)
    verifica(
        len(distincte) == 10,
        f"propuneri numerotate 1–10: {len(distincte)} găsite (în tura {unde})",
    )

    # Decizia 9 — poarta, în ambele sensuri.
    respinse = [n for n, aprobat in portar.cereri if not aprobat]
    aprobate = [n for n, aprobat in portar.cereri if aprobat]
    verifica(
        len(respinse) >= 1 and len(aprobate) >= 1,
        f"poarta s-a deschis în ambele sensuri: {len(respinse)} respinse, "
        f"{len(aprobate)} aprobate",
    )
    verifica(
        all(n in UNELTE_CU_POARTA for n, _ in portar.cereri),
        f"poarta a oprit doar uneltele de scriere: {[n for n, _ in portar.cereri]}",
    )

    # Decizia 7 — o singură ciornă, cea aprobată. Cea respinsă n-a scris nimic.
    scrise = await ciornele_sesiunii_si_sterge(session_id)
    verifica(len(scrise) == 1, f"o singură ciornă în `postari`: {len(scrise)}")
    for r in scrise:
        print(
            f"    „{r['titlu']}” · hook {r['tip_hook']} · script {r['script']} car. · "
            f"caption {r['caption']} car. · {r['hashtaguri']}"
        )
        print(f"    sursa: {r['sursa']}")
        verifica(bool(r["cta"]), "ciorna are CTA")
        verifica(bool(r["sursa"]), "ciorna are sursa completată")
    print("    (ștearsă, ca proba să rămână repetabilă)")

    # Tura 9 — a doua propunere din aceeași listă, fără regenerare.
    verifica(
        len(numere_din(raspunsuri[8])) < 8,
        f"tura 9 n-a regenerat lista: {len(numere_din(raspunsuri[8]))} numere",
    )

    # Decizia 8 — urma.
    actiuni = await urma_sesiunii(session_id)
    for ceruta in (
        "message_received",
        "message_sent",
        "skill_activated",
        "capability_invoked",
        "aprobare_ceruta",
        "aprobare_respinsa",
        "postare_aleasa",
        "propuneri_generate",
    ):
        verifica(ceruta in actiuni, f"urma are `{ceruta}`")
    verifica(
        actiuni.count("message_received") == len(TURE),
        f"urma are toate cele {len(TURE)} ture: {actiuni.count('message_received')}",
    )
    verifica(
        actiuni.count("postare_aleasa") == 1,
        f"doar apelul aprobat e `postare_aleasa`: {actiuni.count('postare_aleasa')}",
    )
    verifica(
        actiuni.count("postare_salvata") == 1,
        f"salvarea serverului e legată de sesiune: {actiuni.count('postare_salvata')}",
    )
    capabilitati = await capabilitati_sesiune(session_id)
    statusuri_save = [s for c, s in capabilitati if c == "tool:save_postare"]
    verifica(
        sorted(statusuri_save) == ["blocked", "ok"],
        f"save_postare are un blocked și un ok: {statusuri_save}",
    )

    for eticheta, tipar in TIPURI_HOOK.items():
        cate = len(re.findall(tipar, lista))
        verifica(cate >= 10, f"hook {eticheta:<10} apare de {cate} ori (aștept ≥10)")

    # Regulile 7 și 9 se verifică pe TOT ce a spus, nu doar pe lista finală.
    tot = "\n".join(raspunsuri)

    # Un procent nu e automat o încălcare a regulii 7: „30% mai mult timp" e o
    # cifră inventată, „ambele părți fac 50%" e o metaforă pentru reciprocitate.
    # Tiparul nu le deosebește, deci semnalează pentru ochiul omului în loc să
    # pice proba. Judecata propriu-zisă e treaba setului de evaluare, Decizia 10.
    for gasit in TIPAR_PROCENT.finditer(tot):
        context = tot[max(0, gasit.start() - 60) : gasit.end() + 10].replace("\n", " ")
        print(f"⚠ procent, de citit cu ochiul: …{context.strip()}…")

    implicite = TIPAR_IMPLICIT.findall(tot)
    verifica(not implicite, f"variante implicite oferite (regula 9): {len(implicite)}")
    verifica(
        "Andreea" not in " ".join(raspunsuri[:4]),
        "avatarul nestrigat pe nume în conversație",
    )

    print("=" * 72)
    print(f"Urma:  uv run python replay.py {session_id}")
    return 1 if greseli else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
