"""Content Worker — Decizia 0: agentul minimal de chat.

Punctul de plecare din `plans/digital-fte-plan.md`, secțiunea 7. Deocamdată e un
singur `Agent` care răspunde în terminal: fără unelte, fără profil, fără memorie
între ture. Crește pas cu pas, o Decizie pe rând.

Ce NU e aici, și când vine:
  Decizia 3  — memorie persistentă (`SQLAlchemySession` peste Neon)
  Decizia 4  — sub-agentul `propune_postari`, chemat cu `Agent.as_tool()`
  Decizia 6  — serverul MCP `content-data`, cu cele cinci unelte
  Decizia 7  — sub-agentul `dezvolta_postarea` și salvarea

Fără `SandboxAgent` — vezi Revizia 4 din plan: niciun declanșator de sandbox nu
se aprinde, pentru că agentul nu are nevoie de shell, pachete sau fișiere proprii.

Rulează:  uv run worker.py
"""

import asyncio
import os
import sys

from agents import Agent, Runner
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")

worker = Agent(
    name="Content Worker",
    model=MODEL,
    instructions=(
        "Ești asistentul de conținut al Viorelei — life coach pentru femei care vor să "
        "iasă din people pleasing, burnout și autosabotaj.\n\n"
        "Răspunzi în română, cu diacritice, la persoana a II-a singular, simplu și cald, "
        "fără termeni tehnici și fără jargon de marketing.\n\n"
        "Deocamdată ești la Decizia 0: nu ai nicio unealtă, nu ai profilul încărcat și nu "
        "ții minte turele anterioare. Dacă ți se cere o postare, spune limpede că încă nu "
        "poți și că urmează să fii construit pas cu pas — nu improviza una din memorie."
    ),
)


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "Lipsește OPENAI_API_KEY.\n"
            "Copiază .env.example în .env și pune cheia acolo."
        )

    print(f"Content Worker · {MODEL} · Decizia 0")
    print("Scrie un mesaj, sau „iesire” ca să termini.")
    print("(Încă nu ține minte turele anterioare — memoria vine la Decizia 3.)\n")

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

        rezultat = await Runner.run(worker, mesaj)
        print(f"\nworker> {rezultat.final_output}\n")


if __name__ == "__main__":
    asyncio.run(main())
