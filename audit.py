"""Urma acțiunilor — Decizia 8.

Regula 2 din `AGENTS.md`: auditul are **conexiune proprie**, în afara graniței
MCP. Deci engine separat de cel al worker-ului, nu unul împrumutat. Motivul e
prozaic: dacă tranzacția de business moare, urma ei trebuie să rămână.

Ce se scrie, și de unde vine fiecare:

    message_received     mesajul ei, înainte de rulare
    skill_activated      din comenzile de shell care deschid un SKILL.md
    capability_invoked   fiecare apel de unealtă MCP, cu argumente și rezultat
    postare_aleasa       din argumentele lui save_postare
    propuneri_generate   tura care a scos zece propuneri numerotate
    guardrail_tripped    excepția din jurul lui Runner.run
    message_sent         răspunsul, după rulare

`postare_salvata` NU se scrie de aici — îl scrie serverul MCP, în aceeași
tranzacție cu INSERT-ul (regula 2, a doua jumătate).

Nimic din fișierul ăsta n-are voie să omoare tura Viorelei: fiecare scriere e
înăuntrul unui `try`. O urmă pierdută e o pagubă; o conversație picată fiindcă
n-a mers scrisul urmei ar fi o prostie.
"""

from __future__ import annotations

import json
import re
import sys

from sqlalchemy.ext.asyncio import create_async_engine

#: Uneltele care trec granița MCP. Restul (`exec_command` și tot ce ține de
#: sandbox) sunt unelte de sistem, nu capabilități de business.
UNELTE_MCP = {
    "cauta_in_carti",
    "cauta_pe_internet",
    "listeaza_postari",
    "save_postare",
    "update_profil",
}

#: `.agents/propune-postari/SKILL.md` dintr-o comandă de shell.
TIPAR_SKILL = re.compile(r"\.agents/([\w-]+)/SKILL\.md")

#: Zece propuneri numerotate la început de rând.
TIPAR_NUMEROTARE = re.compile(r"^\s*(\d{1,2})[.)]", re.MULTILINE)

SQL_AUDIT = """
INSERT INTO audit_log (conversation_id, actor, action, target, payload, result)
VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
"""

SQL_CAPABILITATE = """
INSERT INTO capability_invocations
       (conversation_id, capability, arguments, result, status)
VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
"""


def _json(x: object) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def _incarca(text: object) -> object:
    """Argumentele unei unelte vin ca șir JSON. Dacă nu-s JSON, le las cum sunt."""
    if isinstance(text, str):
        try:
            return json.loads(text)
        except ValueError:
            return {"brut": text}
    return text if text is not None else {}


def apeluri_din(rezultat) -> list[dict]:
    """Apelurile de unelte dintr-o tură, cu argumente și rezultat.

    Le iau din `new_items`, nu din `RunHooks`: hook-urile dau unealta, dar nu și
    argumentele cu care a fost chemată, iar o urmă fără argumente nu se poate
    rejuca.
    """
    apeluri: dict[str, dict] = {}
    ordine: list[str] = []

    for element in getattr(rezultat, "new_items", []):
        brut = getattr(element, "raw_item", None)
        tip = getattr(element, "type", "")
        id_apel = getattr(brut, "call_id", None) or getattr(brut, "id", None) or str(id(brut))

        if tip == "tool_call_item" and hasattr(brut, "name"):
            apeluri[id_apel] = {
                "call_id": id_apel,
                "nume": brut.name,
                "argumente": _incarca(getattr(brut, "arguments", None)),
                "rezultat": None,
            }
            ordine.append(id_apel)
        elif tip == "tool_call_output_item" and id_apel in apeluri:
            apeluri[id_apel]["rezultat"] = getattr(element, "output", None)

    return [apeluri[i] for i in ordine]


class Audit:
    """Conexiunea de audit. Se deschide o dată, la pornirea worker-ului."""

    def __init__(self, url: str, connect_args: dict) -> None:
        self._engine = create_async_engine(url, connect_args=connect_args)
        self._apeluri_blocate: set[tuple[str, str]] = set()

    async def _scrie(self, sql: str, *parametri) -> None:
        try:
            async with self._engine.begin() as conn:
                brut = (await conn.get_raw_connection()).driver_connection
                await brut.execute(sql, *parametri)
        except Exception as e:  # noqa: BLE001 — o urmă pierdută nu oprește tura
            print(f"[audit] n-am putut scrie: {type(e).__name__}: {e}", file=sys.stderr)

    async def actiune(
        self,
        conversatie: str,
        actiune: str,
        target: str | None = None,
        payload: object = None,
        rezultat: object = None,
        actor: str = "worker:content-studio",
    ) -> None:
        await self._scrie(
            SQL_AUDIT,
            conversatie,
            actor,
            actiune,
            target,
            _json(payload if payload is not None else {}),
            _json(rezultat) if rezultat is not None else None,
        )

    async def mesaj_primit(self, conversatie: str, mesaj: str) -> None:
        await self.actiune(
            conversatie, "message_received", "conversations", {"text": mesaj}, actor="viorela"
        )

    async def mesaj_trimis(self, conversatie: str, text: str) -> None:
        await self.actiune(conversatie, "message_sent", "conversations", {"text": text})

    async def a_picat(self, conversatie: str, e: Exception) -> None:
        await self.actiune(
            conversatie,
            "guardrail_tripped",
            "Runner.run",
            {"tip": type(e).__name__, "mesaj": str(e)},
        )

    async def capabilitate_blocata(
        self,
        conversatie: str,
        nume: str,
        argumente: object,
        motiv: str,
        call_id: str,
    ) -> None:
        """Înregistrează tentativa respinsă și o exclude din apelurile reușite."""
        self._apeluri_blocate.add((conversatie, call_id))
        rezultat = {"status": "blocked", "motiv": motiv}
        await self.actiune(
            conversatie, "capability_invoked", nume, argumente, rezultat
        )
        await self._scrie(
            SQL_CAPABILITATE,
            conversatie,
            f"tool:{nume}",
            _json(argumente),
            _json(rezultat),
            "blocked",
        )

    async def tura(self, conversatie: str, rezultat) -> None:
        """Tot ce s-a întâmplat într-o tură: skill-uri deschise, unelte chemate."""
        skilluri = set()

        for apel in apeluri_din(rezultat):
            nume, argumente = apel["nume"], apel["argumente"]

            # Skill-urile n-au unealtă proprie: se deschid cu shell, din sandbox.
            # Deci activarea se citește din comanda rulată, nu dintr-un hook.
            for gasit in TIPAR_SKILL.finditer(_json(argumente)):
                skilluri.add(gasit.group(1))

            if nume not in UNELTE_MCP:
                continue

            call_id = apel["call_id"]
            if (conversatie, call_id) in self._apeluri_blocate:
                self._apeluri_blocate.discard((conversatie, call_id))
                continue

            await self.actiune(
                conversatie, "capability_invoked", nume, argumente, apel["rezultat"]
            )
            await self._scrie(
                SQL_CAPABILITATE,
                conversatie,
                f"tool:{nume}",
                _json(argumente),
                _json(apel["rezultat"]),
                "ok",
            )

            # Care propunere a ales, din cele zece — se vede în ce s-a salvat.
            if nume == "save_postare" and isinstance(argumente, dict):
                await self.actiune(
                    conversatie,
                    "postare_aleasa",
                    "postari",
                    {
                        "titlu": argumente.get("titlu"),
                        "tip_hook": argumente.get("tip_hook"),
                        "hook": argumente.get("hook"),
                    },
                )

        for skill in sorted(skilluri):
            await self.actiune(conversatie, "skill_activated", skill, {"skill": skill})

        # Cele nouă propuneri refuzate sunt cel mai bun semnal despre gustul ei
        # din tot sistemul. Azi se pierd la fiecare rulare; aici rămân.
        text = str(getattr(rezultat, "final_output", "") or "")
        numere = {int(n) for n in TIPAR_NUMEROTARE.findall(text) if 1 <= int(n) <= 10}
        if len(numere) >= 8:
            await self.actiune(
                conversatie,
                "propuneri_generate",
                "propune-postari",
                {"propuneri": text, "cate": len(numere)},
            )

    async def inchide(self) -> None:
        await self._engine.dispose()
