"""Foaia de gardă a conversației: metadata, rezumat și închidere.

Mesajele complete rămân în tabelele SDK-ului, iar urma exactă rămâne în
``audit_log``. Aici păstrăm doar un rezumat factual, ușor de citit și de filtrat.
Nu chemăm modelul încă o dată: toate valorile sunt derivate din audit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


SQL_STATISTICI = """
SELECT count(*) FILTER (WHERE action = 'message_received')::int    AS mesaje_primite,
       count(*) FILTER (WHERE action = 'message_sent')::int        AS mesaje_trimise,
       count(*) FILTER (WHERE action = 'propuneri_generate')::int  AS seturi_propuneri,
       count(*) FILTER (WHERE action = 'postare_salvata')::int     AS postari_salvate,
       count(*) FILTER (WHERE action = 'profil_actualizat')::int   AS actualizari_profil,
       count(*) FILTER (WHERE action = 'skill_activated')::int     AS skilluri_activate,
       count(*) FILTER (WHERE action = 'capability_invoked')::int  AS unelte_folosite,
       count(*) FILTER (WHERE action = 'guardrail_tripped')::int   AS erori,
       max(created_at)                                              AS ultima_activitate,
       (SELECT payload->>'text'
          FROM audit_log
         WHERE conversation_id = $1 AND action = 'message_received'
         ORDER BY id DESC LIMIT 1)                                  AS ultima_cerere,
       (SELECT payload->>'titlu'
          FROM audit_log
         WHERE conversation_id = $1 AND action = 'postare_salvata'
         ORDER BY id DESC LIMIT 1)                                  AS ultima_postare
  FROM audit_log
 WHERE conversation_id = $1
"""

SQL_ACTUALIZEAZA = """
UPDATE conversations
   SET summary = $2,
       metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb,
       ended_at = CASE
                    WHEN $4::bool THEN COALESCE(ended_at, $5::timestamptz, NOW())
                    ELSE ended_at
                  END
 WHERE session_id = $1
"""


def metadata_initiale(model: str) -> dict[str, object]:
    """Valorile cunoscute chiar din clipa în care pornește worker-ul."""
    return {
        "worker": "content-studio-fte",
        "model": model,
        "interfata": "terminal",
        "status": "activa",
        "versiune_metadata": 1,
        "inchidere_estimata": False,
        "motiv_inchidere": None,
    }


def _numar(statistici: Mapping[str, Any], cheie: str) -> int:
    return int(statistici.get(cheie) or 0)


def _scurteaza(text: object, limita: int = 180) -> str:
    curat = " ".join(str(text or "").split())
    if len(curat) <= limita:
        return curat
    return curat[: limita - 1].rstrip() + "…"


def construieste_rezumat(statistici: Mapping[str, Any]) -> str:
    """Construiește un rezumat factual; nu interpretează și nu inventează."""
    primite = _numar(statistici, "mesaje_primite")
    trimise = _numar(statistici, "mesaje_trimise")

    if primite == 0:
        return "Conversație fără mesaje."

    mesaj = "mesaj" if primite == 1 else "mesaje"
    raspuns = "răspuns" if trimise == 1 else "răspunsuri"
    parti = [f"{primite} {mesaj} de la Viorela și {trimise} {raspuns} de la worker."]

    fara_raspuns = max(0, primite - trimise)
    if fara_raspuns:
        forma = "mesaj a rămas" if fara_raspuns == 1 else "mesaje au rămas"
        parti.append(f"{fara_raspuns} {forma} fără răspuns.")

    propuneri = _numar(statistici, "seturi_propuneri")
    if propuneri:
        forma = "set de propuneri generat" if propuneri == 1 else "seturi de propuneri generate"
        parti.append(f"{propuneri} {forma}.")

    postari = _numar(statistici, "postari_salvate")
    if postari:
        forma = "postare salvată" if postari == 1 else "postări salvate"
        ultima = _scurteaza(statistici.get("ultima_postare"), 100)
        detaliu = f", ultima: „{ultima}”" if ultima else ""
        parti.append(f"{postari} {forma}{detaliu}.")

    profil = _numar(statistici, "actualizari_profil")
    if profil:
        forma = "actualizare a profilului" if profil == 1 else "actualizări ale profilului"
        parti.append(f"{profil} {forma}.")

    erori = _numar(statistici, "erori")
    if erori:
        forma = "eroare înregistrată" if erori == 1 else "erori înregistrate"
        parti.append(f"{erori} {forma}.")

    ultima_cerere = _scurteaza(statistici.get("ultima_cerere"))
    if ultima_cerere:
        parti.append(f"Ultima cerere: „{ultima_cerere}”.")

    return " ".join(parti)


def _metadata_din(
    statistici: Mapping[str, Any],
    *,
    model: str | None,
    status: str,
    inchidere_estimata: bool,
    motiv_inchidere: str | None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "worker": "content-studio-fte",
        "interfata": "terminal",
        "status": status,
        "versiune_metadata": 1,
        "mesaje_primite": _numar(statistici, "mesaje_primite"),
        "mesaje_trimise": _numar(statistici, "mesaje_trimise"),
        "seturi_propuneri": _numar(statistici, "seturi_propuneri"),
        "postari_salvate": _numar(statistici, "postari_salvate"),
        "actualizari_profil": _numar(statistici, "actualizari_profil"),
        "skilluri_activate": _numar(statistici, "skilluri_activate"),
        "unelte_folosite": _numar(statistici, "unelte_folosite"),
        "erori": _numar(statistici, "erori"),
        "inchidere_estimata": inchidere_estimata,
        "motiv_inchidere": motiv_inchidere,
    }
    if model:
        metadata["model"] = model

    ultima = statistici.get("ultima_activitate")
    if isinstance(ultima, datetime):
        metadata["ultima_activitate"] = ultima.isoformat()

    return metadata


async def actualizeaza_conversatia(
    engine,
    session_id: str,
    *,
    model: str | None,
    status: str = "activa",
    inchide: bool = False,
    inchidere_estimata: bool = False,
    motiv_inchidere: str | None = None,
    moment_inchidere: datetime | None = None,
) -> tuple[str, dict[str, object]]:
    """Actualizează foaia de gardă și întoarce rezumatul + metadata scrise."""
    async with engine.begin() as conn:
        brut = (await conn.get_raw_connection()).driver_connection
        rand = await brut.fetchrow(SQL_STATISTICI, session_id)
        statistici = dict(rand) if rand is not None else {}
        rezumat = construieste_rezumat(statistici)
        metadata = _metadata_din(
            statistici,
            model=model,
            status=status,
            inchidere_estimata=inchidere_estimata,
            motiv_inchidere=motiv_inchidere,
        )
        if inchide and moment_inchidere is None:
            moment_inchidere = datetime.now(timezone.utc)
        await brut.execute(
            SQL_ACTUALIZEAZA,
            session_id,
            rezumat,
            json.dumps(metadata, ensure_ascii=False),
            inchide,
            moment_inchidere,
        )
    return rezumat, metadata
