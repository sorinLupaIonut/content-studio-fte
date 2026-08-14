"""Cele 17 cărți → `documents` + `embeddings`. Decizia 5.

    uv run python -m db.import_carti
    uv run python -m db.import_carti --rescrie    (reface tot, ignoră sha256)

**Unitatea de lucru e cartea, nu biblioteca.** Fiecare carte își ține `sha256`-ul
fișierului în `documents.metadata`. La rulare se compară: nechimbată → sărită;
nouă sau modificată → doar ea se sparge și se vectorizează. Adaugi a
optsprezecea carte, rulezi din nou, pleacă la OpenAI doar bucățile ei.
Indexul HNSW primește rânduri noi fără reconstrucție.

Singurul lucru care ar cere refacerea tuturor: schimbarea modelului de
embedding. Vectorii de la două modele nu sunt comparabili, iar căutarea ar
întoarce gunoi fără să se plângă — regula 3 din AGENTS.md. De-aia fiecare rând
își poartă modelul în `embeddings.model`: poți întreba baza care sunt vechi.

**Bucățile știu de unde vin.** 16 din 17 cărți au marcaje `<!-- pagina N -->`,
puse la extragerea din PDF. Se merge prin text ținând minte ultima pagină și
ultimul titlu, iar fiecare bucată pleacă cu ele în `embeddings.metadata`. Fără
asta, căutarea ar întoarce text bun fără să poți spune de unde e — iar regula 8
cere exact `„Titlu" — Autor, capitolul N / pagina N` pe câmpul `sursa`.
`cand-corpul-spune-nu.md` n-are marcaje: acolo rămâne doar capitolul, iar
documentul e marcat cu `are_marcaje_pagina: false`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ConfigurareLipsa, descrie, ia_url_bazei

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

CARTI = Path(__file__).parent.parent / "content" / "carti" / "md"
MODEL_EMBED = "text-embedding-3-small"

#: Câte caractere într-o bucată. Sub 800 pierzi contextul frazei; peste ~2000
#: un pasaj bun se îneacă în vecini și scorul de asemănare se aplatizează.
MARIME_BUCATA = 1200

#: Câte bucăți într-o cerere de embedding. 100 × 1200 caractere ≈ 40k tokeni.
LOT = 100

TIPAR_PAGINA = re.compile(r"<!--\s*pagina\s+(\d+)\s*-->")
TIPAR_TITLU = re.compile(r"^#{1,6}\s+(.+?)\s*$")
TIPAR_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

SQL_CAUTA = "SELECT id, metadata->>'sha256' AS sha FROM documents WHERE source='biblioteca' AND title=$1"
SQL_STERGE = "DELETE FROM documents WHERE source='biblioteca' AND title=$1"
SQL_DOC = """
INSERT INTO documents (source, title, body, metadata)
VALUES ('biblioteca', $1, $2, $3::jsonb) RETURNING id
"""
SQL_BUCATA = """
INSERT INTO embeddings (document_id, chunk_text, chunk_index, embedding, model, metadata)
VALUES ($1, $2, $3, $4::vector, $5, $6::jsonb)
"""


def titlu_si_autor(text: str) -> tuple[str, str | None]:
    """Din primul `# Titlu — Autor`. Autorul e opțional; unele cărți n-au unul."""
    gasit = TIPAR_H1.search(text)
    if not gasit:
        return "(fără titlu)", None
    intreg = gasit.group(1)
    for separator in (" — ", " – ", " - "):
        if separator in intreg:
            titlu, autor = intreg.split(separator, 1)
            return titlu.strip(), autor.strip()
    return intreg.strip(), None


def fara_antet(text: str) -> str:
    """Scoate blocul de note al extragerii, dinaintea conținutului cărții.

    Fiecare fișier începe cu `# Titlu` și un citat `> Sursa: …` care descrie
    cum a fost scos din PDF. Alea sunt despre fișier, nu din carte, și n-au ce
    căuta în bucăți. Tai doar citatul de la început: un `>` din mijlocul cărții
    e text adevărat și rămâne.
    """
    linii = text.splitlines()
    i = 0
    while i < len(linii) and (
        not linii[i].strip() or linii[i].startswith(">") or linii[i].startswith("#")
    ):
        i += 1
    return "\n".join(linii[i:])


def sparge(text: str) -> Iterator[tuple[str, int | None, str | None]]:
    """Bucăți de ~MARIME_BUCATA caractere, cu pagina și capitolul lor.

    Merge pe paragrafe, nu pe caractere: o bucată tăiată în mijlocul unei fraze
    se vectorizează prost și se citește și mai prost când o vede Viorela.
    """
    pagina: int | None = None
    capitol: str | None = None
    bucata: list[str] = []
    lungime = 0
    pagina_bucatii: int | None = None
    capitol_bucatii: str | None = None

    for paragraf in text.split("\n\n"):
        paragraf = paragraf.strip()
        if not paragraf:
            continue

        pagini = TIPAR_PAGINA.findall(paragraf)
        if pagini:
            pagina = int(pagini[-1])
            paragraf = TIPAR_PAGINA.sub("", paragraf).strip()
            if not paragraf:
                continue

        titlu = TIPAR_TITLU.match(paragraf)
        if titlu:
            capitol = titlu.group(1).strip("* ")

        if not bucata:
            pagina_bucatii, capitol_bucatii = pagina, capitol

        bucata.append(paragraf)
        lungime += len(paragraf)

        if lungime >= MARIME_BUCATA:
            yield "\n\n".join(bucata), pagina_bucatii, capitol_bucatii
            bucata, lungime = [], 0

    if bucata:
        yield "\n\n".join(bucata), pagina_bucatii, capitol_bucatii


async def vectorizeaza(client: AsyncOpenAI, texte: list[str]) -> list[list[float]]:
    raspuns = await client.embeddings.create(model=MODEL_EMBED, input=texte)
    return [d.embedding for d in raspuns.data]


def ca_vector(valori: list[float]) -> str:
    """asyncpg nu știe tipul `vector`; forma lui text merge cu `::vector` în SQL."""
    return "[" + ",".join(f"{v:.7f}" for v in valori) + "]"


async def importa(conn, client: AsyncOpenAI, cale: Path, rescrie: bool) -> tuple[str, int]:
    """Întoarce (ce s-a întâmplat, câte bucăți)."""
    brut = cale.read_bytes()
    sha = hashlib.sha256(brut).hexdigest()
    text = brut.decode("utf-8")
    titlu, autor = titlu_si_autor(text)

    existent = await conn.fetchrow(SQL_CAUTA, titlu)
    if existent and existent["sha"] == sha and not rescrie:
        return "neschimbată", 0

    corp = fara_antet(text)
    bucati = list(sparge(corp))
    if not bucati:
        return "goală, sărită", 0

    if existent:
        await conn.execute(SQL_STERGE, titlu)

    metadata = {
        "sha256": sha,
        "fisier": cale.name,
        "autor": autor,
        "are_marcaje_pagina": bool(TIPAR_PAGINA.search(text)),
        "este_rezumat": "rezumat" in cale.stem,
        "temei_drepturi": "copie personală, uz privat",
        "proprietar": "viorela",
    }
    doc_id = await conn.fetchval(SQL_DOC, titlu, corp, json.dumps(metadata, ensure_ascii=False))

    for pornire in range(0, len(bucati), LOT):
        lot = bucati[pornire : pornire + LOT]
        vectori = await vectorizeaza(client, [t for t, _, _ in lot])
        await conn.executemany(
            SQL_BUCATA,
            [
                (
                    doc_id,
                    text_bucata,
                    pornire + i,
                    ca_vector(vector),
                    MODEL_EMBED,
                    json.dumps({"pagina": pag, "capitol": cap}, ensure_ascii=False),
                )
                for i, ((text_bucata, pag, cap), vector) in enumerate(zip(lot, vectori))
            ],
        )

    return ("rescrisă" if existent else "importată"), len(bucati)


async def main() -> int:
    load_dotenv()

    if not os.getenv("OPENAI_API_KEY"):
        print("Lipsește OPENAI_API_KEY.", file=sys.stderr)
        return 1

    if not CARTI.is_dir():
        print(f"Lipsește folderul cu cărți: {CARTI}", file=sys.stderr)
        return 1

    try:
        url, connect_args = ia_url_bazei()
    except ConfigurareLipsa as e:
        print(f"{e}", file=sys.stderr)
        return 1

    rescrie = "--rescrie" in sys.argv
    fisiere = sorted(f for f in CARTI.glob("*.md") if f.name != "README.md")

    print(f"Bază : {descrie(url)}")
    print(f"Cărți: {len(fisiere)} fișiere · model {MODEL_EMBED}")
    if rescrie:
        print("Mod   : --rescrie, sha256 ignorat\n")
    else:
        print()

    client = AsyncOpenAI()
    engine = create_async_engine(url, connect_args=connect_args)
    total = 0

    try:
        async with engine.begin() as conn_sa:
            conn = (await conn_sa.get_raw_connection()).driver_connection
            for cale in fisiere:
                ce, cate = await importa(conn, client, cale, rescrie)
                total += cate
                marca = "·" if cate == 0 else "✓"
                print(f"  {marca} {cale.name:<48} {ce:<12} {cate or '':>5}")
    except Exception as e:  # noqa: BLE001
        print(f"\nA picat importul:\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"\n{total} bucăți noi în `embeddings`.")
    print("Verifică cu:  uv run python proba_cautare.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
