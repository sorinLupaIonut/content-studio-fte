"""Content Worker — Decizia 4: un agent în sandbox, cu skill-uri pe disc.

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

Rulează:  uv run worker.py          (reia ultima conversație)
          uv run worker.py --nou    (începe una nouă)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date
from pathlib import Path

from agents import Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.extensions.sandbox.e2b import E2BSandboxClient, E2BSandboxClientOptions
from agents.run_config import RunConfig, SandboxRunConfig
from agents.sandbox import SandboxAgent
from agents.sandbox.capabilities import Capabilities
from agents.sandbox.capabilities.skills import Skills
from agents.sandbox.entries import LocalDir
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, descrie, ia_url_bazei

# Consola Windows e cp1252, iar agentul ăsta scrie numai română. Fără linia
# asta, primul „ș" dintr-o propunere omoară rularea cu UnicodeEncodeError.
for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")
CLIENT_SLUG = "viorela"
RADACINA = Path(__file__).parent
SKILLS = RADACINA / "skills"

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
   personală a ei. Dacă ți se cere o cifră care nu există, refuzi și propui altceva.
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

UNDE EȘTI ACUM — Decizia 4. Ai skill-ul `propune-postari`. NU ai încă: căutare în
cărți, căutare pe internet, dezvoltarea postării alese, salvarea, modificarea
profilului. Dacă ți se cere una dintre astea, spui limpede că urmează.

Ai un sandbox cu shell și fișiere. Îl folosești ca să citești skill-urile, nu ca
să inventezi unelte. Nu încerca să te conectezi la baze de date sau la internet.\
"""

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


def fa_worker(profil_md: str) -> SandboxAgent:
    """Agentul unic, cu skill-urile montate din `skills/`.

    `Skills(from_=LocalDir(...))` descoperă singur folderele: fiecare `SKILL.md`
    își dă numele și descrierea din frontmatter, iar descrierea e ce decide dacă
    skill-ul pornește. Nu declar nimic în Python — skill-urile sunt foldere, așa
    cum trebuie să fie ca să le poți edita fără cod.
    """
    return SandboxAgent(
        name="Content Worker",
        model=MODEL,
        instructions=(
            f"{INSTRUCTIUNI_BAZA}\n\n--- PROFILUL CLIENTEI ---\n{profil_md}"
        ),
        capabilities=[*Capabilities.default(), Skills(from_=LocalDir(src=SKILLS))],
    )


def fa_sandbox() -> tuple[E2BSandboxClient, E2BSandboxClientOptions]:
    """Clientul E2B și opțiunile lui. Cheia se citește singură din `E2B_API_KEY`."""
    return E2BSandboxClient(), E2BSandboxClientOptions(sandbox_type="e2b")


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
    engine = create_async_engine(url, connect_args=connect_args)

    try:
        session_id, nume, profil_md = await porneste(engine, nou)
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        await engine.dispose()
        return 1

    worker = fa_worker(profil_md)

    print(f"Content Worker · {MODEL} · Decizia 4 · sandbox")
    print(f"Bază     : {descrie(url)}")
    print(f"Clientă  : {nume} · profil {len(profil_md):,} caractere în system prompt")
    print(f"Sesiune  : {session_id}{'  (nouă)' if nou else '  (reluată)'}")
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

            print("\n  …lucrez\r", end="", flush=True)
            try:
                rezultat = await Runner.run(
                    worker, mesaj, session=sesiune, run_config=config
                )
            except Exception as e:  # noqa: BLE001
                print(f"\nworker> Ceva n-a mers ({type(e).__name__}). Mai încercăm?\n")
                continue

            print(f"\nworker> {rezultat.final_output}\n")
    finally:
        try:
            await client.delete(sesiune_sandbox)
        except Exception:  # noqa: BLE001
            pass
        await engine.dispose()

    print(f"Conversația a rămas în bază: session_id = {session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
