"""Umple `client` și `postari` din content/. Decizia 3.

    uv run python -m db.seed

Idempotent: rulabil de câte ori vrei. `client` se face upsert pe slug, postările
pe (client_id, fisier_sursa).

CE E GREU AICI. Cele 26 de postări existente nu au un format, au trei — s-au
scris în luni diferite, cu unelte diferite:

  A. cea mai veche (07-09): metadatele într-un blockquote, pe un rând,
     separate cu „·"        > **Pilon:** X · **Format:** Y · **Data:** Z
  B. cele de la mijloc (07-15 → 07-29): fiecare pe rândul ei
                            **Pilon:** X
  C. cea mai nouă (08-13): structura completă, cu **Hook ales:** și
     secțiuni ## HOOK / ## SCRIPT / ## CAPTION / ## HASHTAGURI

Titlurile de secțiune variază și ele: „## SCRIPT", „## Scriptul (6–9 secunde,
fără vorbit)", „## Script (text pe ecran + idee de filmare)". De aia potrivirea
se face pe primul cuvânt, fără diacritice și fără majuscule.

Ce e sigur pe toate 26: data (din numele fișierului) și titlul (`# ` pe primul
rând). Alea două plus pilonul sunt coloanele pe care §3 le vrea pentru „am mai
scris despre asta?". Restul e best-effort, iar `corp_md` ține fișierul întreg,
ca nimic să nu se piardă din ce n-a înțeles parserul.

La final tipărește un tabel de acoperire: câte postări au căpătat fiecare câmp.
Un seed care umple tăcut jumătate din coloane cu NULL e mai rău decât unul care
îți spune ce n-a găsit.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, descrie, ia_url_bazei

RADACINA = Path(__file__).resolve().parent.parent
PROFIL = RADACINA / "content" / "profil.md"
POSTARI = RADACINA / "content" / "postari"

CLIENT_SLUG = "viorela"
CLIENT_NUME = "Viorela"

DATA_DIN_NUME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
CAMP_META = re.compile(r"\*\*\s*([A-Za-zĂÂÎȘȚăâîșț ]{3,20}?)\s*:\s*\*\*\s*([^\n·]+)")
LINIE_TITLU = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
SECTIUNE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# Varianta marcată cu ⭐ dintr-o listă de cinci hook-uri:
#   3. **SECRET** ⭐ *(recomandat)* — „textul hook-ului"
#   - **ÎNTREBARE** ⭐ *(recomandat)* — „textul hook-ului"
# Ghilimelele românești sunt scrise ca escape-uri („ deschide, ” închide)
# ca să nu depindă de encodarea fișierului ăstuia.
HOOK_RECOMANDAT = re.compile(
    "\\*\\*\\s*([A-ZĂÂÎȘȚ]{4,12})\\s*\\*\\*[^\n]*?⭐[^\n]*?[„\"]([^”\"\n]+)"
)
TIPURI_HOOK = {"PROVOCARE", "CIFRA", "SECRET", "INTREBARE", "CONTRAST"}

# Piloni: NU se normalizează după o listă fixă, deliberat. Cei cinci piloni
# (Magnetism, Educație, Conexiune, Despre Business, Conversie) aparțin METODEI
# Brand Legends, nu Viorelei — stau în `skills/*/references/`. §3: metoda e
# capabilitate, nu date; călătorește cu skill-ul, nu cu clienta. Dacă mâine
# aplicația ajunge la altă coach, pilonii pleacă neschimbați. Deci aici doar
# curăț valoarea; vocabularul îl ține skill-ul.


def fara_diacritice(s: str) -> str:
    desfacut = unicodedata.normalize("NFKD", s)
    return "".join(c for c in desfacut if not unicodedata.combining(c))


def curata(s: str | None) -> str | None:
    """Scoate emoji, marcaje și spații de prisos. None dacă rămâne gol."""
    if s is None:
        return None
    s = re.sub(r"[☀-➿\U0001F300-\U0001FAFF️]", "", s)
    s = s.replace("**", "").replace("*", "").strip(" \t·—-– ")
    s = re.sub(r"\s+", " ", s)          # emoji scos lasă spații duble
    # Ghilimelele NU se ating: în titlu („Mesajul de 3 secunde") și în sursă
    # („Granițe în relații" — Cloud & Townsend) fac parte din conținut, iar
    # stripatul lor lasă perechi desfăcute. Hook-ul și-a rezolvat ghilimeaua
    # în regex-ul HOOK_RECOMANDAT, care se oprește înainte de cea de închidere.
    return s.strip() or None


def curata_pilon(s: str) -> str | None:
    """Doar numele pilonului: „Magnetism ✨ (perspectivă contrarian)" -> „Magnetism"."""
    return curata(s.split("(")[0])


@dataclass
class Postare:
    fisier: str
    data: date
    titlu: str
    corp_md: str
    pilon: str | None = None
    format: str | None = None
    hook: str | None = None
    tip_hook: str | None = None
    script: str | None = None
    caption: str | None = None
    hashtaguri: str | None = None
    cta: str | None = None
    sursa: str | None = None
    gasite: set[str] = field(default_factory=set)


def sectiuni(text: str) -> dict[str, str]:
    """Taie textul pe `## ` și indexează după primul cuvânt, normalizat."""
    out: dict[str, str] = {}
    potriviri = list(SECTIUNE.finditer(text))
    for i, m in enumerate(potriviri):
        sfarsit = potriviri[i + 1].start() if i + 1 < len(potriviri) else len(text)
        corp = text[m.end():sfarsit].strip().strip("-").strip()
        cheie = fara_diacritice(m.group(1)).lower().split()[0].strip(":(—-")
        out.setdefault(cheie, corp)
    return out


def parseaza(cale: Path) -> Postare | None:
    text = cale.read_text(encoding="utf-8")

    m = DATA_DIN_NUME.match(cale.name)
    if not m:
        return None
    zi = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    t = LINIE_TITLU.search(text)
    titlu = curata(t.group(1)) if t else cale.stem[11:].replace("-", " ")

    p = Postare(fisier=cale.name, data=zi, titlu=titlu or cale.stem, corp_md=text)
    p.gasite.update({"data", "titlu"})

    # Antetul: tot ce e înainte de prima secțiune `## `. Acoperă și forma A
    # (blockquote cu „·"), și forma B/C (câte una pe rând), fiindcă regex-ul
    # de câmp nu se uită la ce e în jur.
    prima = SECTIUNE.search(text)
    antet = text[: prima.start()] if prima else text[:1500]
    for cheie, val in CAMP_META.findall(antet):
        k = fara_diacritice(cheie).lower().strip()
        v = curata(val)
        if not v:
            continue
        if k == "pilon":
            p.pilon = curata_pilon(val)
            p.gasite.add("pilon")
        elif k == "format":
            p.format, _ = v, p.gasite.add("format")
        elif k == "sursa":
            p.sursa, _ = v, p.gasite.add("sursa")
        elif k in ("hook ales", "hook"):
            tip = fara_diacritice(v).upper().strip()
            if tip in TIPURI_HOOK:
                p.tip_hook, _ = v.upper(), p.gasite.add("tip_hook")

    s = sectiuni(text)
    for cheie, camp in (("script", "script"), ("scriptul", "script"),
                        ("caption", "caption"), ("hashtaguri", "hashtaguri"),
                        ("cta", "cta")):
        if cheie in s and not getattr(p, camp):
            setattr(p, camp, s[cheie])
            p.gasite.add(camp)

    # Hook-ul. Forma C îl are sub `## HOOK`, ca blockquote îngroșat.
    # Formele A/B listează cinci variante, una marcată ⭐ *(recomandat)* — aia e
    # cea aleasă, și tot de acolo iese și tipul.
    if "hook" in s:
        prim = next((l for l in s["hook"].splitlines() if l.strip().startswith(">")), None)
        if prim:
            p.hook, _ = curata(prim.lstrip("> ")), p.gasite.add("hook")
    if not p.hook:
        h = HOOK_RECOMANDAT.search(text)
        if h:
            p.hook = h.group(2).strip()
            p.gasite.add("hook")
            if not p.tip_hook and fara_diacritice(h.group(1)).upper() in TIPURI_HOOK:
                p.tip_hook, _ = h.group(1), p.gasite.add("tip_hook")

    return p


SQL_CLIENT = """
INSERT INTO client (slug, nume, profil_md)
VALUES ($1, $2, $3)
ON CONFLICT (slug) DO UPDATE
   SET profil_md = EXCLUDED.profil_md,
       nume = EXCLUDED.nume,
       actualizat_la = NOW()
RETURNING id
"""

SQL_POSTARE = """
INSERT INTO postari (client_id, data, titlu, pilon, format, hook, tip_hook,
                     script, caption, hashtaguri, cta, sursa, corp_md,
                     fisier_sursa, status)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'importata')
ON CONFLICT (client_id, fisier_sursa) DO UPDATE
   SET data=EXCLUDED.data, titlu=EXCLUDED.titlu, pilon=EXCLUDED.pilon,
       format=EXCLUDED.format, hook=EXCLUDED.hook, tip_hook=EXCLUDED.tip_hook,
       script=EXCLUDED.script, caption=EXCLUDED.caption,
       hashtaguri=EXCLUDED.hashtaguri, cta=EXCLUDED.cta, sursa=EXCLUDED.sursa,
       corp_md=EXCLUDED.corp_md
"""

SQL_AUDIT = """
INSERT INTO audit_log (conversation_id, actor, action, target, payload, result)
VALUES (NULL, 'system', 'corpus_seeded', $1, $2::jsonb, $3::jsonb)
"""

CAMPURI = ["pilon", "format", "hook", "tip_hook", "script",
           "caption", "hashtaguri", "cta", "sursa"]


async def main() -> int:
    load_dotenv()

    if not PROFIL.exists():
        print(f"Lipsește {PROFIL}", file=sys.stderr)
        return 1

    fisiere = sorted(f for f in POSTARI.glob("*.md") if f.name != "README.md")
    if not fisiere:
        print(f"Nicio postare în {POSTARI}", file=sys.stderr)
        return 1

    postari = [p for p in (parseaza(f) for f in fisiere) if p is not None]
    sarite = len(fisiere) - len(postari)

    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(f"{e}", file=sys.stderr)
        return 1

    print(f"Bază: {descrie(url)}\n")
    engine = create_async_engine(url, connect_args=connect_args)

    try:
        async with engine.begin() as conn:
            brut = (await conn.get_raw_connection()).driver_connection

            profil_md = PROFIL.read_text(encoding="utf-8")
            client_id = await brut.fetchval(
                SQL_CLIENT, CLIENT_SLUG, CLIENT_NUME, profil_md
            )
            print(f"client   ✓ {CLIENT_NUME} ({len(profil_md):,} caractere de profil)")

            for p in postari:
                await brut.execute(
                    SQL_POSTARE, client_id, p.data, p.titlu, p.pilon, p.format,
                    p.hook, p.tip_hook, p.script, p.caption, p.hashtaguri,
                    p.cta, p.sursa, p.corp_md, p.fisier,
                )
            print(f"postari  ✓ {len(postari)} rânduri")

            await brut.execute(
                SQL_AUDIT,
                "client,postari",
                json.dumps({"profil": PROFIL.name, "postari": len(postari)},
                           ensure_ascii=False),
                json.dumps({"status": "ok"}, ensure_ascii=False),
            )
    except Exception as e:  # noqa: BLE001
        print(f"\nA picat seed-ul:\n  {type(e).__name__}: {e}", file=sys.stderr)
        print("Ai rulat întâi `uv run python -m db.apply`?", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print("\nAcoperire pe cele 26 de postări — ce a înțeles parserul:")
    for camp in CAMPURI:
        n = sum(1 for p in postari if camp in p.gasite)
        bara = "█" * round(n / len(postari) * 24)
        print(f"  {camp:<11} {n:>2}/{len(postari)}  {bara}")

    fara_pilon = [p.fisier for p in postari if "pilon" not in p.gasite]
    if fara_pilon:
        print(f"\nFără pilon ({len(fara_pilon)}) — de completat manual dacă vrei "
              "căutarea pe pilon din §3:")
        for f in fara_pilon:
            print(f"  · {f}")

    if sarite:
        print(f"\n{sarite} fișiere sărite (numele nu începe cu AAAA-LL-ZZ)")

    print("\nCorpul întreg al fiecărei postări e în `postari.corp_md` — ce n-a "
          "prins parserul nu s-a pierdut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
