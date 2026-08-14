"""Criteriul Deciziei 5: o căutare întoarce pasaje ordonate, cu pagină.

    uv run python proba_cautare.py
    uv run python proba_cautare.py "cum spun nu fara vinovatie"

Întrebarea din plan e „vinovăția de a spune nu". Contează nu doar că se
întorc pasaje, ci că fiecare știe din ce carte, ce capitol și ce pagină vine —
altfel nu poate fi citat pe câmpul `sursa`, cum cere regula 8.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine

from db.config import ia_url_bazei
from db.import_carti import MODEL_EMBED, ca_vector

for flux in (sys.stdout, sys.stderr):
    flux.reconfigure(encoding="utf-8", errors="replace")

INTREBARE = "vinovăția de a spune nu"

SQL = """
SELECT d.title,
       d.metadata->>'autor'   AS autor,
       e.metadata->>'pagina'  AS pagina,
       e.metadata->>'capitol' AS capitol,
       e.chunk_text,
       1 - (e.embedding <=> $1::vector) AS scor
  FROM embeddings e
  JOIN documents  d ON d.id = e.document_id
 WHERE d.source = 'biblioteca'
 ORDER BY e.embedding <=> $1::vector
 LIMIT 8
"""


async def main() -> int:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("Lipsește OPENAI_API_KEY.", file=sys.stderr)
        return 1

    intrebare = sys.argv[1] if len(sys.argv) > 1 else INTREBARE
    raspuns = await AsyncOpenAI().embeddings.create(model=MODEL_EMBED, input=[intrebare])
    vector = ca_vector(raspuns.data[0].embedding)

    url, connect_args = ia_url_bazei()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn_sa:
            conn = (await conn_sa.get_raw_connection()).driver_connection
            randuri = await conn.fetch(SQL, vector)
    finally:
        await engine.dispose()

    if not randuri:
        print("Nimic în `embeddings`. Rulează întâi:  uv run python -m db.import_carti")
        return 1

    print(f"„{intrebare}”\n")
    fara_reper = 0
    for i, r in enumerate(randuri, 1):
        # Pagina bate capitolul. Titlurile de capitol din cărțile extrase din PDF
        # vin adesea tăiate pe două rânduri („## GRANIȚELE" / „## UNUI SUFLET"),
        # deci sunt de încredere doar acolo unde nu există pagină.
        if r["pagina"]:
            reper = f"pagina {r['pagina']}"
        elif r["capitol"]:
            reper = f"capitolul „{r['capitol']}”"
        else:
            reper = "fără reper"
        fara_reper += not (r["pagina"] or r["capitol"])
        autor = f" — {r['autor']}" if r["autor"] else ""
        print(f"{i}. [{r['scor']:.3f}]  {r['title']}{autor}")
        print(f"   {reper}")
        print(f"   {r['chunk_text'][:220].strip()}…\n")

    print(f"{len(randuri)} pasaje, ordonate după asemănare. Fără niciun reper: {fara_reper}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
