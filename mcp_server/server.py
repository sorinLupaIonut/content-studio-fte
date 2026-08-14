"""Serverul MCP `content-data` — singura ușă către datele Viorelei. Decizia 6.

    uv run python -m mcp_server.server

Cinci unelte, atât:

    cauta_in_carti     citire   — căutare după înțeles în cele 17 cărți
    cauta_pe_internet  citire   — unghiuri actuale, cu linkurile surselor
    listeaza_postari   citire   — ce s-a scris deja
    save_postare       scriere  — o postare, plus rândul ei de audit
    update_profil      scriere  — o secțiune din profil, plus rândul de audit

Nu există `run_sql`, nu există DDL, și nicio unealtă nu primește text din care
se construiește SQL. Regula 1 din `AGENTS.md`: worker-ul nu atinge baza direct.

Cele două unelte de scriere își scriu rândul de audit în ACEEAȘI tranzacție cu
scrierea (regula 2). Ori intră amândouă, ori niciuna — o postare fără urmă nu se
poate întâmpla nici dacă pică conexiunea între cele două comenzi.

Poarta de aprobare nu e în corpul uneltei: worker-ul o pune pe înregistrarea
serverului MCP. Astfel, scrierile se întrerup înainte de apel și se reiau doar
după răspunsul Viorelei.

Transportul e HTTP, deci serverul se pornește separat de worker, în alt terminal.
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import Context, MCPServer
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, descrie, ia_url_bazei
from mcp_server.protocol import CONVERSATION_HEADER, PROFIL_URI

# Același model la stocare și la căutare — regula 3. Îl iau chiar din scriptul
# care a scris vectorii, ca să nu poată ajunge diferit fără să se rupă importul.
from db.import_carti import MODEL_EMBED, ca_vector

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

RADACINA = Path(__file__).parents[1]
# Opțiunile de mai jos se calculează la import. `.env` trebuie încărcat înainte,
# altfel WEB_SEARCH_MODEL, MCP_HOST și MCP_PORT scrise acolo sunt ignorate.
load_dotenv(RADACINA / ".env")

CLIENT_SLUG = "viorela"
GAZDA = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8765"))
MODEL_WEB = os.getenv("WEB_SEARCH_MODEL", os.getenv("MODEL", "gpt-5-mini"))

server = MCPServer(
    "content-data",
    instructions=(
        "Datele Viorelei: biblioteca ei de 17 cărți, postările deja scrise și "
        "profilul ei de brand."
    ),
)

# Se face în `main()`, înainte de a porni serverul.
_engine = None


@asynccontextmanager
async def baza():
    """O conexiune asyncpg brută, într-o tranzacție.

    Brută, nu prin SQLAlchemy: `schema.sql` și restul proiectului vorbesc SQL
    direct, iar aici am nevoie de `$1::vector`, pe care dialectul nu-l ajută cu
    nimic. Engine-ul rămâne doar pentru pool și pentru normalizarea URL-ului.
    """
    async with _engine.begin() as conn:
        yield (await conn.get_raw_connection()).driver_connection


SQL_PROFIL = "SELECT id, nume, profil_md FROM client WHERE slug = $1"


@server.resource(
    PROFIL_URI,
    name="profil-viorela",
    title="Profilul complet al Viorelei",
    description="Bootstrap intern pentru system prompt; nu este unealtă a agentului.",
    mime_type="application/json",
)
async def profil_client() -> str:
    """Profilul live, citit prin MCP înainte de construirea agentului."""
    async with baza() as conn:
        rand = await conn.fetchrow(SQL_PROFIL, CLIENT_SLUG)
    if rand is None:
        raise ValueError(f"Nu există clienta {CLIENT_SLUG!r} în tabelul `client`.")
    return json.dumps(
        {"slug": CLIENT_SLUG, "nume": rand["nume"], "profil_md": rand["profil_md"]},
        ensure_ascii=False,
    )


SQL_CAUTA = """
SELECT d.title                                              AS titlu,
       d.metadata->>'autor'                                 AS autor,
       COALESCE(d.metadata->>'clasa',
                'context de lucru — inspirație')            AS clasa,
       COALESCE(d.metadata->>'versiune',
                'ediție neînregistrată')                    AS versiune,
       COALESCE(d.metadata->>'este_rezumat', 'false')::bool AS este_rezumat,
       COALESCE(d.metadata->>'are_marcaje_pagina',
                'false')::bool                              AS are_marcaje_pagina,
       d.metadata->>'temei_drepturi'                        AS temei_drepturi,
       d.metadata->>'proprietar'                            AS proprietar,
       e.metadata->>'pagina'                                AS pagina,
       e.metadata->>'capitol'                               AS capitol,
       e.chunk_text                                         AS text,
       e.model                                              AS model_embedding,
       1 - (e.embedding <=> $1::vector)                     AS scor
  FROM embeddings e
  JOIN documents  d ON d.id = e.document_id
 WHERE d.source = 'biblioteca'
   AND ($2::text[] IS NULL OR d.title = ANY($2::text[]))
 ORDER BY e.embedding <=> $1::vector
 LIMIT $3
"""


@server.tool()
async def cauta_in_carti(
    descriere: str,
    titluri: list[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    """Caută după înțeles în cele 17 cărți din biblioteca Viorelei.

    Folosește-o DOAR când ea a ales sursa „Cărți" sau „Combinat". Descrie ce
    cauți în cuvintele ei („vinovăția de a spune nu"), nu cu cuvinte-cheie.

    `titluri` filtrează pe cărțile alese de ea, cu titlul exact; lipsă = toate.

    Fiecare pasaj vine cu proveniența lui: titlul, autorul, pagina sau capitolul,
    și dacă e rezumat. Pune-le pe câmpul `sursa` al postării — niciodată în hook,
    script sau caption. Un pasaj fără pagină NU primește un număr inventat: scrii
    titlul și autorul, atât.

    `scor` e cât de aproape e pasajul de ce ai cerut, între 0 și 1. Pe corpusul
    ăsta, potrivirile bune stau pe la 0,45–0,55; sub 0,35 e mai degrabă zgomot.
    Pragul e doar un minim: verifică și dacă pasajul chiar tratează subiectul.
    O potrivire vagă despre brand nu e material despre fonturi sau Canva. Dacă
    nimic nu e relevant semantic, spune asta și nu întinde un pasaj slab.
    """
    limit = max(1, min(limit, 20))
    raspuns = await AsyncOpenAI().embeddings.create(model=MODEL_EMBED, input=[descriere])
    vector = ca_vector(raspuns.data[0].embedding)

    async with baza() as conn:
        randuri = await conn.fetch(SQL_CAUTA, vector, titluri, limit)

    return [
        {
            "text": r["text"],
            "titlu": r["titlu"],
            "autor": r["autor"],
            "clasa": r["clasa"],
            "versiune": r["versiune"],
            # Pagina bate capitolul: titlurile de capitol extrase din PDF vin
            # adesea tăiate pe două rânduri, deci sunt de încredere doar acolo
            # unde nu există pagină.
            "pagina": r["pagina"],
            "capitol": r["capitol"] if not r["pagina"] else None,
            "este_rezumat": r["este_rezumat"],
            "are_marcaje_pagina": r["are_marcaje_pagina"],
            "temei_drepturi": r["temei_drepturi"],
            "proprietar": r["proprietar"],
            "model_embedding": r["model_embedding"],
            "scor": round(r["scor"], 3),
        }
        for r in randuri
    ]


def sursele_web(response, limit: int) -> list[dict]:
    """Titlurile și URL-urile citate de Responses API, fără duplicate."""
    vazute: set[str] = set()
    surse: list[dict] = []
    for item in response.output:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []):
            for annotation in getattr(content, "annotations", []):
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                url = getattr(annotation, "url", "")
                if not url or url in vazute:
                    continue
                vazute.add(url)
                surse.append(
                    {
                        "titlu": getattr(annotation, "title", "") or url,
                        "url": url,
                    }
                )
                if len(surse) >= limit:
                    return surse
    return surse


@server.tool()
async def cauta_pe_internet(
    descriere: str,
    limit: int = 5,
) -> dict:
    """Caută unghiuri actuale pe internet pentru tema aleasă de Viorela.

    Folosește-o DOAR când sursa aleasă este „Internet” sau „Combinat”. Rezultatul
    este inspirație: teme de sezon și lucruri discutate acum. Nu transforma
    cifrele, studiile sau citatele găsite pe web în fapte pentru postare.

    Pune subiectul în `descriere`. `surse` conține titlul și linkul paginilor
    citate. Ele merg numai în câmpul `sursa` la salvare, nu în hook, script sau
    caption.
    """
    cautare = descriere.strip()
    if not cautare:
        return {
            "status": "eroare",
            "mesaj": "Lipsește descrierea temei pentru căutare.",
            "unghiuri": "",
            "surse": [],
        }
    limit = max(1, min(limit, 8))
    prompt = f"""Caută pe web idei actuale pentru conținut social în limba română
pe tema: {cautare!r}.

Întoarce cel mult {limit} denumiri scurte de unghiuri, ca sintagme, fără să le
explici și fără să afirmi nimic despre cauze, efecte, simptome, prevenție sau
tratament. Exemple de formă: „limite după concediu”, „presiunea de a fi mereu
disponibilă”. Nu da procente, statistici, rezultate de studii, citate ori
afirmații medicale. Nu scrie o postare și nu da reguli; oferă numai subiecte de
explorat și citează paginile consultate."""
    response = await AsyncOpenAI().responses.create(
        model=MODEL_WEB,
        tools=[{"type": "web_search", "search_context_size": "low"}],
        input=prompt,
    )
    return {
        "status": "ok",
        "tema": cautare,
        "unghiuri": response.output_text,
        "surse": sursele_web(response, limit),
        "regula": (
            "Unghiurile spun numai despre ce poți vorbi. Nu afirma cauze, efecte, "
            "simptome, prevenție, diagnostice sau reguli. Nu prelua cifre, studii "
            "ori citate. Linkurile merg doar la sursa."
        ),
    }


SQL_POSTARI = """
SELECT p.data, p.titlu, p.pilon, p.format, p.hook, p.tip_hook, p.sursa, p.status
  FROM postari p
  JOIN client  c ON c.id = p.client_id
 WHERE c.slug = $1
   AND ($2::text IS NULL OR p.pilon  ILIKE '%' || $2 || '%')
   AND ($3::text IS NULL OR p.format ILIKE '%' || $3 || '%')
   AND ($4::date IS NULL OR p.data >= $4)
 ORDER BY p.data DESC
 LIMIT $5
"""


@server.tool()
async def listeaza_postari(
    pilon: str | None = None,
    format: str | None = None,
    de_la: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Postările deja scrise, cele mai noi întâi.

    Pentru „am mai scris despre asta?" și pentru „ce am dat luna asta".
    `pilon` și `format` caută pe bucată de text, nu pe potrivire exactă.
    `de_la` e o dată, în forma 2026-07-01.
    """
    limit = max(1, min(limit, 100))
    zi = date.fromisoformat(de_la) if de_la else None

    async with baza() as conn:
        randuri = await conn.fetch(SQL_POSTARI, CLIENT_SLUG, pilon, format, zi, limit)

    return [{**dict(r), "data": r["data"].isoformat()} for r in randuri]


SQL_ID_CLIENT = "SELECT id FROM client WHERE slug = $1"

SQL_INSEREAZA_POSTARE = """
INSERT INTO postari (client_id, conversation_id, data, titlu, pilon, format,
                     hook, tip_hook, script, caption, hashtaguri, cta, sursa,
                     status, corp_md)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'ciorna', $14)
RETURNING id
"""

SQL_AUDIT = """
INSERT INTO audit_log (conversation_id, actor, action, target, payload, result)
VALUES ($1, 'worker:content-studio', $2, $3, $4::jsonb, $5::jsonb)
"""


def ca_markdown(camp: dict) -> str:
    """Postarea întreagă, ca Markdown, pentru coloana `corp_md`.

    O construiesc eu din câmpuri, nu o cer modelului: `corp_md` trebuie să fie
    exact ce s-a salvat pe coloane, nu o a doua versiune, scrisă separat.
    """
    return "\n".join(
        [
            f"# {camp['titlu']}",
            "",
            f"**Pilon:** {camp['pilon']} · **Format:** {camp['format']}",
            f"**Hook ({camp['tip_hook']}):** {camp['hook']}",
            "",
            "## Script",
            camp["script"],
            "",
            "## Caption",
            camp["caption"],
            "",
            f"**Hashtaguri:** {camp['hashtaguri']}",
            f"**CTA:** {camp['cta']}",
            f"**Sursa:** {camp['sursa']}",
            "",
        ]
    )


def conversatia_din(ctx: Context) -> str:
    """ID-ul pus de worker pe conexiunea MCP, nu inventat de model."""
    cerere = ctx.request_context.request
    headers = getattr(cerere, "headers", None)
    conversation_id = headers.get(CONVERSATION_HEADER) if headers else None
    if not conversation_id:
        raise ValueError(
            f"Lipsește antetul intern {CONVERSATION_HEADER}; scrierea a fost oprită."
        )
    return conversation_id


@server.tool()
async def save_postare(
    titlu: str,
    pilon: str,
    format: str,
    hook: str,
    tip_hook: str,
    script: str,
    caption: str,
    hashtaguri: str,
    cta: str,
    sursa: str,
    ctx: Context,
) -> dict:
    """Salvează postarea confirmată de Viorela. UNA singură, cea aleasă.

    Nu o chema până nu i-ai arătat postarea întreagă în chat și nu ți-a spus „da"
    (regula 10). Celelalte nouă propuneri nu se salvează.

    `sursa` e obligatorie și spune adevărul: titlul și pagina cărții, linkul, sau
    „din memorie 🧠 (profil + avatar), fără sursă externă".
    `tip_hook` e unul din PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE, CONTRAST.
    `hashtaguri` e un singur șir, cu spații între ele: „#burnout #limite".
    """
    conversation_id = conversatia_din(ctx)
    camp = {
        "titlu": titlu,
        "pilon": pilon,
        "format": format,
        "hook": hook,
        "tip_hook": tip_hook,
        "script": script,
        "caption": caption,
        "hashtaguri": hashtaguri,
        "cta": cta,
        "sursa": sursa,
    }

    async with baza() as conn:
        client_id = await conn.fetchval(SQL_ID_CLIENT, CLIENT_SLUG)
        if client_id is None:
            raise ValueError(f"Nu există clienta {CLIENT_SLUG!r} în tabelul `client`.")

        id_postare = await conn.fetchval(
            SQL_INSEREAZA_POSTARE,
            client_id,
            conversation_id,
            date.today(),
            titlu,
            pilon,
            format,
            hook,
            tip_hook,
            script,
            caption,
            hashtaguri,
            cta,
            sursa,
            ca_markdown(camp),
        )
        await conn.execute(
            SQL_AUDIT,
            conversation_id,
            "postare_salvata",
            "postari",
            json.dumps(camp, ensure_ascii=False),
            json.dumps({"id": str(id_postare)}, ensure_ascii=False),
        )

    return {"id": str(id_postare), "titlu": titlu, "data": date.today().isoformat()}


SQL_SCRIE_PROFIL = """
UPDATE client SET profil_md = $2, actualizat_la = NOW() WHERE id = $1
"""


def inlocuieste_sectiune(profil: str, sectiune: str, text_nou: str) -> str:
    """Schimbă corpul unei secțiuni `## …`, lăsând restul profilului neatins.

    Titlul secțiunii rămâne cum e scris în profil, nu cum l-a scris modelul —
    altfel o diferență de diacritice sau de emoji ar rescrie antetul.
    """
    # Doar spații orizontale în jurul titlului. `\s` ar înghiți și rândurile
    # goale de după antet, apoi ar introduce spațiere suplimentară la rescriere.
    titluri = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", profil, re.MULTILINE))
    cautat = sectiune.strip().lower()

    for i, titlu in enumerate(titluri):
        if cautat not in titlu.group(1).lower():
            continue
        inceput = titlu.end()
        sfarsit = titluri[i + 1].start() if i + 1 < len(titluri) else len(profil)
        return profil[:inceput] + "\n\n" + text_nou.strip() + "\n\n" + profil[sfarsit:]

    existente = "\n".join(f"  · {t.group(1)}" for t in titluri)
    raise ValueError(
        f"Nu există o secțiune care să conțină {sectiune!r} în profil.\n"
        f"Secțiunile de azi sunt:\n{existente}"
    )


@server.tool()
async def update_profil(sectiune: str, text_nou: str, ctx: Context) -> dict:
    """Rescrie o secțiune din profilul Viorelei. Doar la cererea ei explicită.

    `sectiune` e o bucată din titlul secțiunii, așa cum apare în profil („Oferte",
    „CTA"). `text_nou` e corpul întreg al secțiunii, fără linia de titlu — ce
    trimiți înlocuiește tot ce era acolo, deci scrie-l complet, nu doar adaosul.

    Ce era înainte rămâne în `audit_log`, deci o greșeală se poate întoarce.
    """
    conversation_id = conversatia_din(ctx)
    async with baza() as conn:
        rand = await conn.fetchrow(SQL_PROFIL, CLIENT_SLUG)
        if rand is None:
            raise ValueError(f"Nu există clienta {CLIENT_SLUG!r} în tabelul `client`.")

        profil_nou = inlocuieste_sectiune(rand["profil_md"], sectiune, text_nou)
        await conn.execute(SQL_SCRIE_PROFIL, rand["id"], profil_nou)
        await conn.execute(
            SQL_AUDIT,
            conversation_id,
            "profil_actualizat",
            "client",
            json.dumps(
                {"sectiune": sectiune, "text_vechi": rand["profil_md"]},
                ensure_ascii=False,
            ),
            json.dumps({"caractere": len(profil_nou)}, ensure_ascii=False),
        )

    return {
        "sectiune": sectiune,
        "profil_avea": len(rand["profil_md"]),
        "profil_are": len(profil_nou),
    }


def main() -> int:
    global _engine

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("Lipsește OPENAI_API_KEY. Fără el nu merge căutarea.", file=sys.stderr)
        return 1

    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(f"{e}", file=sys.stderr)
        return 1

    _engine = create_async_engine(url, connect_args=connect_args)

    print(f"content-data · cinci unelte · http://{GAZDA}:{PORT}/mcp")
    print(f"Bază: {descrie(url)}")
    print("Lasă-l pornit și deschide worker-ul în alt terminal.\n")

    # stateless: fiecare cerere e completă în ea însăși, fără sesiune ținută
    # între ele. Worker-ul e un singur proces, pe aceeași mașină — n-am ce
    # câștiga dintr-o stare de sesiune, dar am ce pierde dacă se desincronizează.
    server.run("streamable-http", host=GAZDA, port=PORT, stateless_http=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
