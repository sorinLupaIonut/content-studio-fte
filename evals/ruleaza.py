"""Rulează setul Deciziei 10 pe worker-ul real.

Cere serverul MCP pornit în alt terminal:

    uv run python -m mcp_server.server
    uv run python evals/ruleaza.py

Fiecare caz pornește cu istoric gol. Sandbox-ul și conexiunea MCP se refolosesc,
dar conversațiile nu se amestecă. Orice unealtă de scriere este respinsă în
evaluare; setul n-are voie să lase postări sau modificări de profil în urmă.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

RADACINA = Path(__file__).parents[1]
if str(RADACINA) not in sys.path:
    sys.path.insert(0, str(RADACINA))

from agents import Runner  # noqa: E402
from agents.mcp import MCPServerStreamableHttp  # noqa: E402
from agents.run_config import RunConfig, SandboxRunConfig  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from audit import apeluri_din  # noqa: E402
from db.config import ia_url_bazei  # noqa: E402
from worker import (  # noqa: E402
    CLIENT_SLUG,
    MCP_URL,
    SQL_CLIENT,
    UNELTE_CU_POARTA,
    descrie_cererea,
    fa_sandbox,
    fa_worker,
)

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

FISIER_CAZURI = RADACINA / "evals" / "cazuri.json"
RAPORT_IMPLICIT = RADACINA / "evals" / "raport-latest.json"

TIPAR_SKILL = re.compile(r"\.agents[/\\]([\w-]+)[/\\]SKILL\.md")
TIPAR_NUMAR = re.compile(r"^\s*(10|[1-9])[.)]\s", re.MULTILINE)
TIPAR_HOOK = re.compile(
    r"^\s*[-*]\s*(PROVOCARE|CIFR[ĂA]|SECRET|[ÎI]NTREBARE|CONTRAST)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def argumente() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rulează evaluările Content Worker")
    parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        type=int,
        help="rulează numai cazul dat; se poate repeta",
    )
    parser.add_argument(
        "--doar-automat",
        action="store_true",
        help="sare peste cazurile marcate cu_ochiul",
    )
    parser.add_argument(
        "--raport",
        type=Path,
        default=RAPORT_IMPLICIT,
        help="fișierul JSON de ieșire",
    )
    return parser.parse_args()


def incarca_cazuri(optiuni: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    date = json.loads(FISIER_CAZURI.read_text(encoding="utf-8"))
    toate = date["cazuri"]
    alese = [c for c in toate if not optiuni.ids or c["id"] in optiuni.ids]
    if optiuni.doar_automat:
        alese = [c for c in alese if c["stare"] == "de_rulat"]
    return toate, alese


def unelte_si_skilluri(rezultat) -> tuple[set[str], set[str]]:
    unelte: set[str] = set()
    skilluri: set[str] = set()
    for apel in apeluri_din(rezultat):
        unelte.add(apel["nume"])
        text = json.dumps(apel["argumente"], ensure_ascii=False)
        skilluri.update(TIPAR_SKILL.findall(text))
    return unelte, skilluri


async def ruleaza_fara_scriere(worker, intrare, config):
    """Rulează o tură și respinge orice întrerupere de aprobare."""
    rezultat = await Runner.run(worker, intrare, run_config=config)
    incercari_scriere: list[str] = []
    reluari = 0

    while rezultat.interruptions:
        reluari += 1
        if reluari > 5:
            raise RuntimeError("Agentul insistă cu scrierea după cinci respingeri.")
        stare = rezultat.to_state()
        for cerere in rezultat.interruptions:
            nume, _, _ = descrie_cererea(cerere)
            incercari_scriere.append(nume)
            stare.reject(
                cerere,
                rejection_message="Evaluarea nu aprobă nicio scriere.",
            )
        rezultat = await Runner.run(worker, stare, run_config=config)

    return rezultat, incercari_scriere


def raspuns_cu_lista(raspunsuri: list[str]) -> str:
    """Răspunsul care seamănă cel mai mult cu lista 10 × 5."""
    return max(
        raspunsuri,
        key=lambda text: (len(set(TIPAR_NUMAR.findall(text))), len(TIPAR_HOOK.findall(text))),
        default="",
    )


def propuneri_si_hookuri(text: str) -> tuple[int, bool]:
    """Numără propunerile și verifică exact cele cinci tipuri în fiecare."""
    pozitii = list(TIPAR_NUMAR.finditer(text))
    blocuri: dict[int, str] = {}
    for index, potrivire in enumerate(pozitii):
        numar = int(potrivire.group(1))
        sfarsit = pozitii[index + 1].start() if index + 1 < len(pozitii) else len(text)
        blocuri[numar] = text[potrivire.start() : sfarsit]

    exact = True
    asteptate = {"PROVOCARE", "CIFRĂ", "SECRET", "ÎNTREBARE", "CONTRAST"}
    for numar in range(1, 11):
        gasite = []
        for tip in TIPAR_HOOK.findall(blocuri.get(numar, "")):
            normalizat = tip.upper().replace("CIFRA", "CIFRĂ").replace("INTREBARE", "ÎNTREBARE")
            gasite.append(normalizat)
        exact &= len(gasite) == 5 and set(gasite) == asteptate
    return len(blocuri), exact


def verifica(caz: dict, raspunsuri: list[str], unelte: set[str], skilluri: set[str]) -> list[str]:
    reguli = caz.get("verificare") or {}
    final = raspunsuri[-1] if raspunsuri else ""
    erori: list[str] = []

    tipare = reguli.get("contine", [])
    if tipare and not any(re.search(t, final, re.IGNORECASE) for t in tipare):
        erori.append(f"răspunsul final nu conține niciun tipar cerut: {tipare}")

    interzise = [t for t in reguli.get("nu_contine", []) if re.search(t, final, re.IGNORECASE)]
    if interzise:
        erori.append(f"răspunsul final conține tipare interzise: {interzise}")

    lipsesc = set(reguli.get("unelte", [])) - unelte
    if lipsesc:
        erori.append(f"unelte nechemate: {sorted(lipsesc)}")

    chemate_interzis = set(reguli.get("fara_unelte", [])) & unelte
    if chemate_interzis:
        erori.append(f"unelte chemate deși erau interzise: {sorted(chemate_interzis)}")

    skilluri_lipsa = set(reguli.get("skilluri", [])) - skilluri
    if skilluri_lipsa:
        erori.append(f"skill-uri neactivate: {sorted(skilluri_lipsa)}")

    if "numar_propuneri" in reguli or "tipuri_hook" in reguli:
        lista = raspuns_cu_lista(raspunsuri)
        cate, hookuri_exacte = propuneri_si_hookuri(lista)
        if "numar_propuneri" in reguli and cate != reguli["numar_propuneri"]:
            erori.append(f"propuneri: {cate}, așteptat {reguli['numar_propuneri']}")
        if "tipuri_hook" in reguli and not hookuri_exacte:
            erori.append("nu fiecare propunere are exact cele cinci tipuri de hook")

    return erori


async def ia_profilul() -> tuple[str, str, dict]:
    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn_sa:
            conn = (await conn_sa.get_raw_connection()).driver_connection
            rand = await conn.fetchrow(SQL_CLIENT, CLIENT_SLUG)
        if rand is None:
            raise RuntimeError(f"Nu există clienta {CLIENT_SLUG!r} în bază.")
        return rand["profil_md"], url, connect_args
    finally:
        await engine.dispose()


async def main() -> int:
    optiuni = argumente()
    load_dotenv(RADACINA / ".env")
    toate, cazuri = incarca_cazuri(optiuni)
    necunoscute = set(optiuni.ids or []) - {c["id"] for c in toate}
    if necunoscute:
        print(f"Nu există cazurile: {sorted(necunoscute)}", file=sys.stderr)
        return 2

    try:
        profil_md, _, _ = await ia_profilul()
    except Exception as e:  # noqa: BLE001
        print(f"Nu pot încărca profilul: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    date_mcp = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        cache_tools_list=True,
        client_session_timeout_seconds=30,
        require_approval={"always": {"tool_names": list(UNELTE_CU_POARTA)}},
    )
    try:
        await date_mcp.connect()
    except Exception as e:  # noqa: BLE001
        print(f"Nu răspunde serverul MCP la {MCP_URL}: {type(e).__name__}", file=sys.stderr)
        return 2

    client, configurare_sandbox = fa_sandbox()
    sandbox = await client.create(options=configurare_sandbox)
    config = RunConfig(sandbox=SandboxRunConfig(client=client, session=sandbox))
    worker = fa_worker(profil_md, date_mcp)
    raport: list[dict] = []
    esecuri = 0

    try:
        for caz in cazuri:
            if caz["stare"] == "amanat":
                print(f"○ {caz['id']:>2} AMÂNAT       {caz['titlu']}")
                raport.append({"id": caz["id"], "verdict": "amanat", "titlu": caz["titlu"]})
                continue

            print(f"\n[{caz['id']}/15] {caz['titlu']}", flush=True)
            pornit = time.monotonic()
            istoric: list = []
            raspunsuri: list[str] = []
            unelte: set[str] = set()
            skilluri: set[str] = set()
            eroare_rulare: str | None = None

            try:
                for mesaj in caz["ture"]:
                    rezultat, incercari = await ruleaza_fara_scriere(
                        worker,
                        istoric + [{"role": "user", "content": mesaj}],
                        config,
                    )
                    istoric = rezultat.to_input_list()
                    raspunsuri.append(str(rezultat.final_output))
                    t_unelte, t_skilluri = unelte_si_skilluri(rezultat)
                    unelte.update(t_unelte)
                    unelte.update(incercari)
                    skilluri.update(t_skilluri)
            except Exception as e:  # noqa: BLE001
                eroare_rulare = f"{type(e).__name__}: {e}"

            erori = [eroare_rulare] if eroare_rulare else verifica(
                caz, raspunsuri, unelte, skilluri
            )
            erori = [e for e in erori if e]
            necesita_ochiul = caz["stare"] == "cu_ochiul" and not erori
            verdict = "cu_ochiul" if necesita_ochiul else ("picat" if erori else "trecut")
            esecuri += verdict == "picat"
            semn = "◐" if verdict == "cu_ochiul" else ("✓" if verdict == "trecut" else "✗")
            print(
                f"{semn} {verdict.upper():<13} {time.monotonic() - pornit:.0f}s · "
                f"unelte={sorted(unelte) or ['—']} · skilluri={sorted(skilluri) or ['—']}"
            )
            for eroare in erori:
                print(f"    {eroare}")
            if necesita_ochiul:
                print("    verdictul de conținut se dă din `raspuns_final` în raport")

            raport.append(
                {
                    "id": caz["id"],
                    "titlu": caz["titlu"],
                    "stare": caz["stare"],
                    "verdict": verdict,
                    "erori": erori,
                    "unelte": sorted(unelte),
                    "skilluri": sorted(skilluri),
                    "raspuns_final": raspunsuri[-1] if raspunsuri else "",
                    "comportament_corect": caz["comportament_corect"],
                }
            )
    finally:
        await client.delete(sandbox)
        await date_mcp.cleanup()

    optiuni.raport.parent.mkdir(parents=True, exist_ok=True)
    optiuni.raport.write_text(
        json.dumps({"cazuri": raport}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    automate = sum(r["verdict"] == "trecut" for r in raport)
    cu_ochiul = sum(r["verdict"] == "cu_ochiul" for r in raport)
    amanate = sum(r["verdict"] == "amanat" for r in raport)
    print(
        f"\nRezultat: {automate} trecute · {esecuri} picate · "
        f"{cu_ochiul} cu ochiul · {amanate} amânate"
    )
    print(f"Raport: {optiuni.raport}")
    return 1 if esecuri else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
