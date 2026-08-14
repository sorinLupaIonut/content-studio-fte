# Content Studio FTE

Content Worker pentru Viorela — life coach — construit ca **Digital FTE** cu OpenAI Agents SDK,
Neon Postgres + pgvector și un server MCP propriu.

Succesorul lui `content-studio-vio-2`, care rămâne funcțional pentru ea până când ăsta îl înlocuiește.

- **Ce face și după ce reguli** → [AGENTS.md](AGENTS.md)
- **De ce e construit așa** → [plans/digital-fte-plan.md](plans/digital-fte-plan.md)
- **Modelul de construcție** → [Building a Digital FTE](https://agentfactory.panaversity.org/docs/digital-fte-crash-course), Partea 4

## Cum se rulează

Baza: proiectul Neon `content-studio-fte` (`dry-fog-12289707`), branch `main`, Postgres 17, us-east-1.

Copiază `.env.example` în `.env`, pune cheia OpenAI și `DATABASE_URL` din Neon.
Șirul din consola Neon (cu `sslmode=require&channel_binding=require`) merge lipit ca atare —
`db/config.py` îl normalizează pentru `asyncpg`.

```bash
uv run python -m db.apply
```

```bash
uv run python -m db.seed
```

```bash
uv run worker.py
```

`worker.py` reia ultima conversație; cu `--nou` începe una nouă.

## Unde suntem

| # | Decizia | Stare |
|---|---|---|
| 0 | Agent minimal de chat — `uv`, Agents SDK, `Agent` simplu, fără sandbox | ✅ răspunde |
| 1 | `AGENTS.md` cu regulile de arhitectură | ✅ scris |
| 2 | Planul schemei și al celor doi sub-agenți | ✅ `plans/digital-fte-plan.md` |
| 3 | Neon + pgvector + schema, apoi `SQLAlchemySession` | ✅ 7 tabele, memorie peste repornire |
| 4 | `propune_postari` — sub-agent cu `output_type=Propuneri`, chemat cu `as_tool` | ⬜ |
| 5 | Import + embedding: cele 17 cărți; `metoda/` spartă pe subiecte | ⬜ |
| 6 | MCP server `content-data`, cinci unelte | ⬜ |
| 7 | `dezvolta_postarea` ca al doilea `as_tool` + salvarea | ⬜ |
| 8 | Audit la fiecare graniță + replay | ⬜ |
| 9 | Poarta de aprobare pe `save_postare` și `update_profil` | ⬜ |
| 10 | Setul de evaluare — cele 12 cazuri urâte din §5 al planului | ⬜ |

## Structura

```
worker.py                     agentul; memorie în Neon + profilul în system prompt
AGENTS.md                     specificația domeniului + contractul de arhitectură
plans/digital-fte-plan.md     planul complet, cu motivele fiecărei decizii
db/
  schema.sql                    5 tabele din Concept 7 + client și postari
  config.py                     normalizează DATABASE_URL pentru asyncpg
  apply.py                      aplică schema, idempotent
  seed.py                       profil.md → client; 26 postări → postari
content/                      materialul brut, până când intră în Postgres
  profil.md                     → client.profil_md          (Decizia 3)
  carti/md/                     doar README-ul e în git; cărțile stau local (drept de autor),
                                se copiază înainte de Decizia 5 → documents + embeddings
  postari/                      26 postări → tabelul postari (Decizia 3)
  metoda/                       manualul întreg, de spart    (Decizia 5)
mcp_server/content/metoda/    fișierele servite de get_metoda (Decizia 6)
evals/                        cele 12 cazuri urâte, cu răspunsul corect (Decizia 10)
```

## Stack

`openai-agents` · `gpt-5-mini` pentru generare · `text-embedding-3-small` pentru căutare ·
Neon Postgres + pgvector · MCP Python SDK · proiect `uv`.

Fără Docker, fără sandbox, fără infrastructură pe Windows.
