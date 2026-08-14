"""Content Worker — un agent în sandbox, cu skill-uri pe disc și date prin MCP.

**Un singur agent**, care încarcă instrucțiuni din foldere `SKILL.md`.

Ce câștigi:
  · progressive disclosure adevărat — indexul de skill-uri (nume + descriere +
    cale) stă mereu în context și costă puțin; corpul se deschide doar când
    sarcina se potrivește descrierii, iar `references/` doar dacă SKILL.md
    trimite acolo;
  · un singur context, deci profilul și regulile nu se mai copiază în promptul
    fiecărui agent;
  · metoda stă în fișiere pe care le poți edita fără să atingi codul.

Ce pierzi, și trebuie știut:
  · un `SKILL.md` e text. Nu poate impune „exact zece propuneri cu exact cinci
    hook-uri" — spune și speră. Numărul e instrucțiune, nu contract, deci se
    poate întoarce cu nouă. Se numără după, în `proba_flux.py`, și se judecă la
    evaluare (Decizia 10).

Ce NU se montează în sandbox: nimic din proiect în afară de `skills/`. `.env`
conține parola bazei Neon, iar agentul are shell — deci n-are ce căuta acolo.

Sandbox-ul e E2B: cere `E2B_API_KEY` în `.env`, tier Hobby gratuit.

La date ajunge doar prin serverul MCP `content-data` (regula 1), care se pornește
separat. Sandbox-ul n-are treabă cu el: uneltele MCP se cheamă de aici, din
procesul ăsta, nu dinăuntrul sandbox-ului.

Rulează, în două terminale:
          uv run python -m mcp_server.server
          uv run worker.py          (reia ultima conversație)
          uv run worker.py --nou    (începe una nouă)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

from agents import Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.extensions.sandbox.e2b import E2BSandboxClient, E2BSandboxClientOptions
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig
from agents.sandbox import SandboxAgent
from agents.sandbox.capabilities import Capabilities
from agents.sandbox.capabilities.skills import Skills
from agents.sandbox.entries import LocalDir
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from audit import Audit
from db.config import ConfigurareLipsa, descrie, ia_url_bazei
from mcp_server.protocol import CONVERSATION_HEADER, PROFIL_URI

# Consola Windows e cp1252, iar agentul ăsta scrie numai română. Fără linia
# asta, primul „ș" dintr-o propunere omoară rularea cu UnicodeEncodeError.
for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")
CLIENT_SLUG = "viorela"
RADACINA = Path(__file__).parent
SKILLS = RADACINA / "skills"
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp")
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "90"))

#: Uneltele care ies sub numele Viorelei. Doar ele au poartă; citirile sunt libere.
UNELTE_CU_POARTA = ("save_postare", "update_profil")

# Regulile stau în system prompt, nu într-un skill, fiindcă sunt mereu în
# vigoare. Progressive disclosure e pentru ce trebuie uneori — metoda, pilonii,
# tipurile de hook. Un contract de ieșire care se încarcă „la nevoie" e un
# contract pe care modelul poate să nu-l citească exact când îl încalcă.
INSTRUCTIUNI_BAZA = """\
Ești asistentul de conținut al Viorelei — life coach pentru femei care vor să iasă
din people pleasing, burnout și autosabotaj.

Răspunzi în română, cu diacritice, la persoana a II-a singular, simplu și cald,
fără termeni tehnici și fără jargon de marketing.

CU CINE VORBEȘTI. Vorbești cu Viorela — clienta, cea care comandă conținutul. NU
o strigi „Andreea". Andreea e avatarul, femeia de 25–45 de ani pentru care se
scriu postările; apare în conținut, niciodată în conversația cu Viorela.

REGULI OBLIGATORII — contractul de ieșire, nu preferințe de stil:

1. Vocea Viorelei, nu vocea unui robot. Tonul și expresiile din „Vocea ta",
   „Expresii pe care le folosești des" și „Tonul tău", din profil. Cald, blând,
   empatic, vulnerabil dar ferm, cu perspectivă creștină autentică.
   FĂRĂ empowerment agresiv. FĂRĂ jargon de marketing. FĂRĂ fraze generice de
   AI („în lumea agitată de azi", „haide să descoperim").
2. Respectă „Lucruri pe care nu le spui niciodată" din profil. Dacă tema cerută
   intră în conflict cu ele, NU generezi ce e afectat: spui care e conflictul și
   ceri decizia ei.
3. Specific, nu generic. Durerile, dorințele, fricile și credințele limitative
   REALE din profil. O postare bună pentru oricine e o postare bună pentru nimeni.
4. Conținutul se scrie CĂTRE Andreea, dar nu o strigi pe nume în text —
   „Andreea, știu cum te simți" sună a reclamă. Vorbești cu ea, nu despre ea.
5. Fiecare postare completă include: hook ales, script, caption, 3–5 hashtaguri,
   CTA din profil.
6. Dacă profilul are ⚠️ în ceva de care depinde sarcina, semnalezi scurt și
   generezi totuși ce se poate.
7. Testimonialele și cifrele se folosesc DOAR dacă există în profil. Nu inventezi
   niciodată rezultate, cifre sau dovezi — nici măcar prezentate ca experiență
   personală a ei. Dacă ți se cere o cifră care nu există, refuzi și propui
   altceva la persoana a II-a, fără cuantificări mascate precum „multe femei",
   „majoritatea” sau „din experiența mea”.
8. Sursa de inspirație rămâne în culise. Cartea, autorul, pagina sau linkul se
   notează DOAR pe câmpul `sursa` al postării salvate — NU în hook, în script sau
   în caption. E conținut de social media, nu lucrare cu bibliografie.
9. Întrebările se pun, răspunsurile nu se presupun. Dacă răspunde ambiguu sau
   sare peste una, reîntrebi. Nu alegi în locul ei și nu pornești „pe o variantă
   până răspunde". NU oferi variante implicite: fraza „dacă nu răspunzi, folosesc
   X" e interzisă — aștepți răspunsul, atât. Sursa o alege ea dintr-o listă
   închisă; n-o inventezi tu. După ce a ales-o, nu aduci material din alta.
10. Nimic nu se salvează fără confirmarea ei.

Mesajele ei pot veni dictate, fără diacritice, cu greșeli de transcriere. Le
interpretezi cu bunăvoință, fără s-o corectezi. Răspunsul tău are diacritice.

UNDE EȘTI ACUM — Deciziile 0–10. Ai skill-urile `propune-postari` și
`dezvolta-postarea`, și cinci unelte: `cauta_in_carti`, `cauta_pe_internet`,
`listeaza_postari`, `save_postare`, `update_profil`. Când sursa aleasă este
Internet sau Combinat cu Internet, folosești `cauta_pe_internet` înainte să
scrii propunerile. Din rezultat iei numai unghiuri; cifrele, studiile, citatele
și afirmațiile găsite pe web nu intră în postare ca fapte. Unghiul poate decide
despre ce vorbești, dar conținutul concret se sprijină numai pe profilul aflat
deja în context și pe exemple obișnuite formulate ca posibilități, nu ca adevăruri
generale, cauze sau sfaturi medicale. Dacă unealta web dă eroare, te oprești și
spui asta; nu generezi din memorie și nu schimbi sursa fără răspunsul ei.

MODUL INTERNET — verificare obligatorie înainte de răspuns. Sunt permise
întrebări de reflecție („ce observi?”, „ce ai putea refuza?”), situații obișnuite
și formulări de limite sprijinite de profil. Sunt interzise afirmațiile generale
de forma „X cauzează / previne / arată / înseamnă Y”, listele de simptome sau
„semne”, diagnosticele, recomandările medicale și reguli inventate precum
„50–50”. Un hook CIFRĂ poate număra întrebări, pași ori formulări create de tine
(„3 întrebări”), dar nu oameni, rezultate, simptome, efecte, procente, raporturi
sau durate precum „48h” ori „în 2 minute”. Ca regulă simplă, în modul Internet
fiecare idee și hook este o întrebare, un îndemn către ea sau descrierea formei
postării — nu o propoziție declarativă care promite un rezultat. Dacă un bloc nu
trece verificarea, îl rescrii înainte să-l arăți.

Uneltele de scriere se cheamă doar după „da"-ul ei, niciodată din proprie
inițiativă (regula 10).

Ai un sandbox cu shell și fișiere. Îl folosești ca să citești skill-urile, nu ca
să inventezi unelte. La date ajungi NUMAI prin unelte — nu încerca să te conectezi
la baza de date din sandbox.

ACTIVAREA SKILL-URILOR ESTE OBLIGATORIE. La orice cerere de conținut nou, deschizi
`propune-postari` ÎNAINTE de primul răspuns — inclusiv dacă ea a dat deja formatul,
pilonul sau sursa. Când alege o propunere dintr-o listă existentă, deschizi
`dezvolta-postarea` înainte s-o scrii. Nu improvizezi fluxul din memorie. O cerere
de raport despre postările existente nu activează niciunul dintre aceste skill-uri.\
"""

SQL_ULTIMA = """
SELECT session_id FROM conversations
 WHERE user_id = $1 ORDER BY started_at DESC LIMIT 1
"""
SQL_CONV_NOUA = """
INSERT INTO conversations (session_id, user_id, metadata)
VALUES ($1, $2, $3::jsonb)
ON CONFLICT (session_id) DO NOTHING
"""


async def porneste(engine, nou: bool) -> str:
    """Alege sesiunea și creează foaia ei de gardă, fără date de business."""
    async with engine.begin() as conn:
        brut = (await conn.get_raw_connection()).driver_connection
        session_id = None if nou else await brut.fetchval(SQL_ULTIMA, CLIENT_SLUG)
        if session_id is None:
            session_id = f"{CLIENT_SLUG}-{date.today():%Y%m%d}-{uuid.uuid4().hex[:8]}"
            await brut.execute(SQL_CONV_NOUA, session_id, CLIENT_SLUG, "{}")

    return session_id


async def citeste_profil(date_mcp: MCPServerStreamableHttp) -> tuple[str, str]:
    """Întoarce (nume, profil_md) din resursa MCP, nu prin SQL din worker."""
    raspuns = await date_mcp.read_resource(PROFIL_URI)
    texte = [
        continut.text
        for continut in getattr(raspuns, "contents", [])
        if isinstance(getattr(continut, "text", None), str)
    ]
    if not texte:
        raise RuntimeError(f"Resursa MCP {PROFIL_URI!r} nu a întors text.")
    try:
        date = json.loads("".join(texte))
        nume, profil_md = date["nume"], date["profil_md"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise RuntimeError(f"Resursa MCP {PROFIL_URI!r} are o formă neașteptată.") from e
    if not isinstance(nume, str) or not isinstance(profil_md, str) or not profil_md.strip():
        raise RuntimeError(f"Resursa MCP {PROFIL_URI!r} nu conține un profil valid.")
    return nume, profil_md


def fa_worker(profil_md: str, date_mcp: MCPServerStreamableHttp) -> SandboxAgent:
    """Agentul unic: skill-urile montate din `skills/`, datele prin MCP.

    `Skills(from_=LocalDir(...))` descoperă singur folderele: fiecare `SKILL.md`
    își dă numele și descrierea din frontmatter, iar descrierea e ce decide dacă
    skill-ul pornește. Nu declar nimic în Python — skill-urile sunt foldere, așa
    cum trebuie să fie ca să le poți edita fără cod.

    Uneltele nu se declară nici ele: vin de la server, cu tot cu descrieri.
    """
    return SandboxAgent(
        name="Content Worker",
        model=MODEL,
        instructions=(
            f"{INSTRUCTIUNI_BAZA}\n\n--- PROFILUL CLIENTEI ---\n{profil_md}"
        ),
        capabilities=[*Capabilities.default(), Skills(from_=LocalDir(src=SKILLS))],
        mcp_servers=[date_mcp],
    )


def fa_sandbox() -> tuple[E2BSandboxClient, E2BSandboxClientOptions]:
    """Clientul E2B și opțiunile lui. Cheia se citește singură din `E2B_API_KEY`."""
    return E2BSandboxClient(), E2BSandboxClientOptions(sandbox_type="e2b")


def descrie_cererea(cerere) -> tuple[str, dict, str]:
    """(numele, argumentele, id-ul apelului) dintr-o cerere de aprobare."""
    brut = getattr(cerere, "raw_item", None)
    nume = getattr(cerere, "tool_name", None) or getattr(brut, "name", "?")
    call_id = getattr(brut, "call_id", None) or getattr(brut, "id", None) or str(id(brut))
    argumente = getattr(brut, "arguments", None)
    if isinstance(argumente, str):
        try:
            argumente = json.loads(argumente)
        except ValueError:
            argumente = {"brut": argumente}
    return nume, argumente or {}, call_id


async def ruleaza_tura(worker, intrare, sesiune, config, urma, session_id, aproba):
    """O tură, cu poarta de aprobare pe drum.

    Când agentul vrea să scrie, `Runner.run` se oprește și întoarce cereri în
    loc de răspuns. Le ducem la om, apoi reluăm rularea din aceeași stare —
    modelul nu reia de la zero, continuă din locul în care a fost oprit.
    """
    rezultat = await Runner.run(worker, intrare, session=sesiune, run_config=config)

    while rezultat.interruptions:
        stare = rezultat.to_state()
        for cerere in rezultat.interruptions:
            nume, argumente, call_id = descrie_cererea(cerere)
            await urma.actiune(session_id, "aprobare_ceruta", nume, argumente)

            aprobat, motiv = await aproba(nume, argumente)
            if aprobat:
                stare.approve(cerere)
            else:
                stare.reject(cerere, rejection_message=motiv)
                await urma.actiune(
                    session_id, "aprobare_respinsa", nume, argumente, {"motiv": motiv}
                )
                await urma.capabilitate_blocata(
                    session_id, nume, argumente, motiv, call_id
                )

        rezultat = await Runner.run(worker, stare, session=sesiune, run_config=config)

    return rezultat


async def intreaba_in_terminal(nume: str, argumente: dict) -> tuple[bool, str]:
    """Poarta, așa cum o vede Viorela: ce se scrie, și un da/nu."""
    print(f"\n  ⚠ Vrea să cheme `{nume}`:")
    for cheie, valoare in argumente.items():
        text = " ".join(str(valoare).split())
        print(f"      {cheie:<12} {text[:80]}{'…' if len(text) > 80 else ''}")

    raspuns = input("  Îi dai voie? (da / nu) ").strip().lower()
    if raspuns in {"da", "d", "yes", "y"}:
        return True, ""
    return False, "Viorela n-a aprobat scrierea. Nu insista; întreab-o ce vrea schimbat."


async def main() -> int:
    for cheie in ("OPENAI_API_KEY", "E2B_API_KEY"):
        if not os.getenv(cheie):
            print(f"Lipsește {cheie}. Copiază .env.example în .env.", file=sys.stderr)
            return 1

    if not SKILLS.is_dir():
        print(f"Lipsește folderul de skill-uri: {SKILLS}", file=sys.stderr)
        return 1

    try:
        url, connect_args = ia_url_bazei()
        client, optiuni = fa_sandbox()
    except (ConfigurareLipsa, RuntimeError) as e:
        print(f"{e}", file=sys.stderr)
        return 1

    nou = "--nou" in sys.argv
    # `pool_pre_ping`: o conversație stă minute bune între mesaje, iar Neon închide
    # conexiunile inactive. Fără ping, memoria conversației pică la reluare.
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)

    try:
        session_id = await porneste(engine, nou)
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        await engine.dispose()
        return 1

    # Web search poate trece de 30 de secunde când conexiunile sunt reci; 90 este
    # valoarea implicită, configurabilă prin MCP_TIMEOUT.
    date_mcp = MCPServerStreamableHttp(
        params={
            "url": MCP_URL,
            "headers": {CONVERSATION_HEADER: session_id},
        },
        name="content-data",
        cache_tools_list=True,
        client_session_timeout_seconds=MCP_TIMEOUT,
        # Poarta de aprobare stă pe ÎNREGISTRAREA serverului, nu în interiorul
        # uneltei (Decizia 9). Așa apără orice apel al agentului prin această
        # înregistrare, indiferent ce scrie în prompt. Citirile rămân libere.
        require_approval={"always": {"tool_names": list(UNELTE_CU_POARTA)}},
    )
    try:
        await date_mcp.connect()
        unelte = [u.name for u in await date_mcp.list_tools()]
        nume, profil_md = await citeste_profil(date_mcp)
    except Exception as e:  # noqa: BLE001
        print(f"Nu pot inițializa datele prin MCP la {MCP_URL} ({type(e).__name__}: {e}).", file=sys.stderr)
        print("Pornește serverul în alt terminal:", file=sys.stderr)
        print("  uv run python -m mcp_server.server", file=sys.stderr)
        await date_mcp.cleanup()
        await engine.dispose()
        return 1

    worker = fa_worker(profil_md, date_mcp)

    # Engine separat de cel de business: regula 2 cere ca urma să aibă
    # conexiunea ei, în afara oricărei tranzacții care poate să pice.
    urma = Audit(url, connect_args)

    print(f"Content Worker · {MODEL} · Deciziile 0–10 · sandbox + MCP + audit + poartă")
    print(f"Bază     : {descrie(url)}")
    print(f"Clientă  : {nume} · profil {len(profil_md):,} caractere în system prompt")
    print(f"Sesiune  : {session_id}{'  (nouă)' if nou else '  (reluată)'}")
    print(f"Unelte   : {', '.join(unelte)}")
    print("Sandbox  : pornesc E2B…", end="", flush=True)

    # Sandbox-ul se face O SINGURĂ DATĂ și se refolosește la fiecare tură.
    # Altfel s-ar porni unul nou la fiecare mesaj, cu tot cu montarea
    # skill-urilor — secunde bune pierdute degeaba.
    #
    # Îl creez gol, fără manifest: când primește o sesiune vie, SDK-ul aplică
    # singur pe ea intrările cerute de capabilități, deci skill-urile se montează
    # la prima rulare. Iar fiindcă sesiunea e a mea, tot eu o și șterg, la final.
    try:
        sesiune_sandbox = await client.create(options=optiuni)
    except Exception as e:  # noqa: BLE001
        print(" a picat.")
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        await date_mcp.cleanup()
        await engine.dispose()
        return 1
    print(" gata.")

    config = RunConfig(sandbox=SandboxRunConfig(client=client, session=sesiune_sandbox))

    sesiune = SQLAlchemySession(
        session_id,
        engine=engine,
        create_tables=True,
        ensure_ascii=False,
    )

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

            # Urma se deschide ÎNAINTE de rulare: dacă tura pică, se vede că a
            # existat. Un audit scris doar la sfârșit ratează exact turele care
            # merită cel mai mult explicate.
            await urma.mesaj_primit(session_id, mesaj)

            print("\n  …lucrez\r", end="", flush=True)
            try:
                rezultat = await ruleaza_tura(
                    worker, mesaj, sesiune, config, urma, session_id,
                    intreaba_in_terminal,
                )
            except Exception as e:  # noqa: BLE001
                await urma.a_picat(session_id, e)
                print(f"\nworker> Ceva n-a mers ({type(e).__name__}). Mai încercăm?\n")
                continue

            await urma.tura(session_id, rezultat)
            await urma.mesaj_trimis(session_id, str(rezultat.final_output))

            print(f"\nworker> {rezultat.final_output}\n")
    finally:
        try:
            await client.delete(sesiune_sandbox)
        except Exception:  # noqa: BLE001
            pass
        await date_mcp.cleanup()
        await urma.inchide()
        await engine.dispose()

    print(f"Conversația a rămas în bază: session_id = {session_id}")
    print(f"Ce a făcut, rejucat:  uv run python replay.py {session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
