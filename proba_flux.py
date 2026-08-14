"""Proba Deciziei 4 în forma cu sandbox și skill-uri.

Criteriul din §7: la „vreau ceva despre limite" agentul pune întrebările și
scoate zece propuneri. Dar conversația de aici merge dinadins pe drumul urât,
fiindcă acolo se vede dacă skill-ul chiar e citit:

  1. „vreau ceva despre limite"  → întreabă formatul
  2. „reel"                      → întreabă pilonul
  3. „conexiune"                 → întreabă sursa
  4. „din cărți"                 → spune că nu merge azi     ⟵ testul care contează
  5. „hai pe memorie"            → scoate zece propuneri

**Tura 4 e proba de progressive disclosure.** Faptul că azi funcționează doar
sursa Memorie e scris NUMAI în `skills/propune-postari/references/surse.md`.
Nu e în SKILL.md și nu e în system prompt. Dacă agentul răspunde corect acolo,
înseamnă că a deschis referința — adică lanțul index → SKILL.md → references
chiar funcționează. Dacă răspunde greșit, skill-urile sunt decor.

Iar ce nu se mai poate garanta, față de varianta cu sub-agent și `output_type`:
numărul de propuneri și de hook-uri. Aici se numără după, nu se impune înainte.

Verificările NU presupun în ce tură vine lista. Prima oară au presupus, agentul
a livrat-o cu două ture mai devreme decât mă așteptam, iar tot ce urma s-a
măsurat pe un mesaj gol — inclusiv un „✓ cifre inventate: 0" complet fals, pe un
răspuns care nu avea niciun cuvânt. Acum lista se caută acolo unde e.

Rulează:  uv run python proba_flux.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time

from agents import Runner
from agents.run_config import RunConfig, SandboxRunConfig
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ia_url_bazei
from worker import CLIENT_SLUG, SQL_CLIENT, fa_sandbox, fa_worker

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

TURE = [
    "vreau ceva despre limite",
    "reel",
    "conexiune",
    "din cărți",
    "nu, hai pe memorie atunci",
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

#: Semne că a înțeles că sursa Cărți nu e disponibilă azi.
SEMNE_REFUZ = ("memorie", "nu e disponibil", "nu sunt gata", "nu pot", "decizia 6")

#: „dacă nu răspunzi, folosesc X" — regula 9 o interzice explicit.
TIPAR_IMPLICIT = re.compile(r"dac[ăa] nu r[ăa]spunzi|folosesc implicit|implicit[,:]", re.IGNORECASE)

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


async def ia_profilul() -> str:
    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            brut = (await conn.get_raw_connection()).driver_connection
            rand = await brut.fetchrow(SQL_CLIENT, CLIENT_SLUG)
        return rand["profil_md"]
    finally:
        await engine.dispose()


async def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("Lipsește OPENAI_API_KEY.", file=sys.stderr)
        return 1

    profil_md = await ia_profilul()
    worker = fa_worker(profil_md)
    client, optiuni = fa_sandbox()

    pornit = time.monotonic()
    sandbox = await client.create(options=optiuni)
    print(f"Sandbox pornit în {time.monotonic() - pornit:.0f}s")
    print(f"Profil: {len(profil_md):,} caractere\n")

    config = RunConfig(sandbox=SandboxRunConfig(client=client, session=sandbox))
    istoric: list = []
    raspunsuri: list[str] = []

    try:
        for mesaj in TURE:
            t0 = time.monotonic()
            rezultat = await Runner.run(
                worker,
                istoric + [{"role": "user", "content": mesaj}],
                run_config=config,
            )
            durata = time.monotonic() - t0
            istoric = rezultat.to_input_list()
            raspuns = str(rezultat.final_output)
            raspunsuri.append(raspuns)

            print(f"tu> {mesaj}   ({durata:.0f}s)")
            print(f"worker> {raspuns}\n")
            print("-" * 72)
    finally:
        await client.delete(sandbox)

    print()
    print("=" * 72)
    greseli = 0

    def verifica(reusit: bool, eticheta: str) -> None:
        nonlocal greseli
        greseli += not reusit
        print(f"{'✓' if reusit else '✗'} {eticheta}")

    # Tura 4 — a citit references/surse.md?
    a_patra = raspunsuri[3].lower()
    verifica(
        any(s in a_patra for s in SEMNE_REFUZ),
        "tura 4: a aflat din references/surse.md că sursa Cărți nu merge azi",
    )

    unde, lista = gaseste_lista(raspunsuri)
    distincte = numere_din(lista)
    verifica(
        len(distincte) == 10,
        f"propuneri numerotate 1–10: {len(distincte)} găsite (în tura {unde})",
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

    verifica("Andreea" not in " ".join(raspunsuri[:4]), "avatarul nestrigat pe nume în conversație")

    print("=" * 72)
    return 1 if greseli else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
