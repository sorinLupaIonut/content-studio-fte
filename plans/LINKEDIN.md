# LinkedIn — gata de lipit

Textul pentru profil, pregătit pe 2026-08-30. **Nepublicat**: profilul e public și
e al tău, așa că ultimul pas — Save — rămâne al tău.

Ordinea de mai jos e ordinea în care aș face-o: 10 minute în total.

---

## 1 · Secțiunea „Projects" — proiectul principal

**Project name**

```
Content Studio FTE — a production Digital FTE agent
```

**Description** (LinkedIn taie la ~2.000 de caractere; textul ăsta intră)

```
A Digital FTE — a digital full-time employee, not a chatbot with a prompt. One
agent does a content assistant's job for a real coaching business: it asks what it
needs, gathers material from a private library of 17 books (4,778 embedded chunks)
or the live web, proposes ten posts, develops the chosen one, and saves nothing
without a human "yes".

Stack: OpenAI Agents SDK (Python 3.13) · a purpose-built MCP server, 10
model-visible tools and 25 internal · Neon Postgres + pgvector, 18 tables · skills
as editable folders mounted into an E2B container per run · .NET 10 Blazor
WebAssembly + FastAPI · OpenTelemetry to Application Insights and Arize Phoenix.

What I'd want to be asked about:

• Architecture selection, with the rejections written down. Single agent + ReAct,
  with the plan supplied as a read-only skill folder the domain expert edits
  herself. Multi-agent was rejected on a measured bottleneck test, not on taste: a
  28,639-character client profile would be copied into a second context for a
  5–20x cost multiplier.

• Cost engineering: $0.2490 → $0.0470 per batch, 5.3x, without changing the model.
  The biggest single win was counter-intuitive — the cheapest reasoning setting
  was a false economy. At "minimal", 15 of 16 runs fetched the reference file OR
  called the search tool, never both, and stopped themselves well under the turn
  limit. One step up cost 640 tokens (~$0.0013/run) and took the pass rate from
  3/12 to 12/12 with the prompt cache intact.

• Eval-driven development against the 9-layer pyramid: unit (408 tests), tool-use
  (a 240-square domain grid), trace, RAG-with-an-LLM-judge-and-a-negative-control,
  safety, and a Phoenix regression dataset where six scores land on the run they
  belong to. Layer 3 — output evals — is still empty, and the case study says so.

• Governance built in, not bolted on: every write commits in the same transaction
  as its audit row; the approval gate sits on the MCP registration rather than
  inside the tool; the client is resolved from the connection and can never be a
  tool argument.

Full engineering case study, including the defects that only appeared because
something was measuring: [link]
```

**Skills to tag on the project**

```
Artificial Intelligence (AI) · Large Language Models (LLM) · Python ·
PostgreSQL · Software Architecture · Microsoft Azure · .NET · System Design
```

> **Cum îl faci „cel mai tare dintre toate":** LinkedIn nu are „pin" pe Projects.
> Ce contează, în ordine: (1) *Currently working on this project* bifat, ca să
> apară primul; (2) datele — dacă are cea mai recentă dată de început, urcă;
> (3) îl adaugi și în **Featured**, care e secțiunea care chiar se vede sus pe
> profil. Featured e locul unde „cel mai tare" devine vizibil, nu Projects.

---

## 2 · Secțiunea „Featured" — aici se vede

Adaugi un link cu:

**Title**

```
Content Studio FTE — engineering case study
```

**Description**

```
Architecture chosen and four rejected, the 9-layer eval pyramid mapped onto what
is actually built, and how one batch went from $0.2490 to $0.0470.
```

**Link** — vezi §4, e singura problemă reală.

---

## 3 · „About" — paragraful de adăugat la final

```
Most recently I built Content Studio FTE: a production Digital FTE agent for a
coaching business — OpenAI Agents SDK, a purpose-built MCP server over Neon
Postgres with pgvector, method held in editable skill folders rather than in code,
and an eval suite built against the nine-layer pyramid. The part I care about is
the part that is not the model: an audit row that commits in the same transaction
as the write it describes, an approval gate that sits where the prompt cannot
reach it, and a cost curve that went down 5.3x because something was measuring.
```

---

## 4 · Problema de rezolvat înainte: `[link]`

**Repozitoriul e PRIVAT.** Un recrutor nu-l poate deschide, deci linkul de mai sus
nu poate fi încă `github.com/sorinLupaIonut/content-studio-fte`.

Trei opțiuni, în ordinea în care le-aș lua:

1. **Un repo public separat, „vitrină".** Doar `docs/CASE-STUDY.md`, diagramele,
   `AGENTS.md` și schema — fără `content/`, fără cod care atinge datele ei. Cel
   mai bun raport între ce arăți și ce riști. ~30 de minute.
2. **Faci public repo-ul actual după ce scoți `content/`.** Cărțile sunt deja
   ignorate, dar `content/profile.md` (profilul ei complet de brand) și 28 de
   postări publicate ale ei sunt urmărite în git. Ar trebui scoase din istoric,
   nu doar din HEAD — și e materialul ei, deci e o decizie pe care o iei cu ea,
   nu una tehnică.
3. **Fără link.** Descrierea de mai sus stă în picioare și singură; pui linkul
   când există.

Recomandarea mea: **1**.
