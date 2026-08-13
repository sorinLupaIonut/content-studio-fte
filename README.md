# Content Studio FTE

Content Worker pentru Viorela — life coach — construit ca **Digital FTE** cu OpenAI Agents SDK,
Neon Postgres + pgvector și un server MCP propriu.

Succesorul lui `content-studio-vio-2`, care rămâne funcțional pentru ea până când ăsta îl înlocuiește.

- **Ce face și după ce reguli** → [AGENTS.md](AGENTS.md)
- **De ce e construit așa** → [plans/digital-fte-plan.md](plans/digital-fte-plan.md)
- **Modelul de construcție** → [Building a Digital FTE](https://agentfactory.panaversity.org/docs/digital-fte-crash-course), Partea 4

## Cum se rulează

```bash
uv run worker.py
```

Înainte de prima rulare: copiază `.env.example` în `.env` și pune-ți cheia OpenAI.

## Unde suntem

| # | Decizia | Stare |
|---|---|---|
| 0 | Agent minimal de chat — `uv`, Agents SDK, `Agent` simplu, fără sandbox | ✅ răspunde |
| 1 | `AGENTS.md` cu regulile de arhitectură | ✅ scris |
| 2 | Planul schemei și al celor doi sub-agenți | ✅ `plans/digital-fte-plan.md` |
| 3 | Neon + pgvector + schema, apoi `SQLAlchemySession` | ⬜ |
| 4 | `propune_postari` — sub-agent cu `output_type=Propuneri`, chemat cu `as_tool` | ⬜ |
| 5 | Import + embedding: cele 17 cărți; `metoda/` spartă pe subiecte | ⬜ |
| 6 | MCP server `content-data`, cinci unelte | ⬜ |
| 7 | `dezvolta_postarea` ca al doilea `as_tool` + salvarea | ⬜ |
| 8 | Audit la fiecare graniță + replay | ⬜ |
| 9 | Poarta de aprobare pe `save_postare` și `update_profil` | ⬜ |
| 10 | Setul de evaluare — cele 12 cazuri urâte din §5 al planului | ⬜ |

## Structura

```
worker.py                     agentul; azi doar chat, crește cu fiecare Decizie
AGENTS.md                     specificația domeniului + contractul de arhitectură
plans/digital-fte-plan.md     planul complet, cu motivele fiecărei decizii
content/                      materialul brut, până când intră în Postgres
  profil.md                     → client.profil_md          (Decizia 3)
  carti/md/                     17 cărți → documents + embeddings  (Decizia 5)
  postari/                      26 postări → tabelul postari (Decizia 3)
  metoda/                       manualul întreg, de spart    (Decizia 5)
mcp_server/content/metoda/    fișierele servite de get_metoda (Decizia 6)
evals/                        cele 12 cazuri urâte, cu răspunsul corect (Decizia 10)
```

## Stack

`openai-agents` · `gpt-5-mini` pentru generare · `text-embedding-3-small` pentru căutare ·
Neon Postgres + pgvector · MCP Python SDK · proiect `uv`.

Fără Docker, fără sandbox, fără infrastructură pe Windows.
