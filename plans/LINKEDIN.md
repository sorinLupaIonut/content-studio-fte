# LinkedIn — publicat pe 31 august 2026

**Publicat.** Textul de mai jos e ce stă acum pe profil, păstrat aici ca să știi ce
scrie fără să deschizi LinkedIn — și ca să ai de unde edita dacă vrei altceva.

| Unde | Ce e acolo | Poziția |
|---|---|---|
| **Featured** | link GitHub cu card și thumbnail, titlu „Content Studio FTE — a production Digital FTE agent" | **primul**, peste Digital FTE și Reading Room |
| **Projects** | intrarea completă de mai jos, iul. 2026 – prezent, 5 skill-uri, **diagrama stivei ca imagine** + linkul GitHub | **primul** |
| **Skills** | LLM · Python · Software Architecture · PostgreSQL · Microsoft Azure, toate legate de proiect | — |

**Editat pe 31 august, la cererea lui Sorin:** blocul de patru puncte se numea
„What I'd want to be asked about" — suna a interviu pus in scena, nu a
descriere de proiect. Se numeste „Key engineering decisions" acum.

**Diagrama, ca imagine.** `docs/diagrams/02-deployed-stack.svg`, randată cu
Chrome headless la 2× și urcată ca media pe intrarea din Projects, prima din
listă — ca să se vadă legăturile fără să deschidă nimeni GitHub. Dacă o
actualizezi, refaci PNG-ul așa:

```
chrome --headless=new --force-device-scale-factor=2 --window-size=1000,780        --screenshot=out.png file:///.../docs/diagrams/02-deployed-stack.svg
```

**Ce n-am atins:** headline-ul, banner-ul, About. Headline-ul tău spune deja
„Agentic AI Engineer & Senior .NET Developer", iar banner-ul „AI workers you can
audit — every action traced, every claim verified" — proiectul ăsta e chiar dovada
pentru amândouă, deci n-aveau nevoie de schimbare. Paragraful de About de la §3 a
rămas nepus: e singurul loc unde ai o voce personală și merită să-l scrii tu.

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

Key engineering decisions:

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

## 4 · Linkul — rezolvat pe 31 august

**Repozitoriul e PUBLIC**, cu profilul inclus, decizia ta luată cu concluzia pusă
pe masă. `main` a fost adus la zi în același timp: era cu 100 de comituri în urmă,
deci oricine îl deschidea vedea proiectul de dinainte de serverul MCP, de UI și de
evals.

Pune oriunde scrie `[link]`:

```
https://github.com/sorinLupaIonut/content-studio-fte
```

Pentru **Featured**, cel mai bun link nu e repo-ul, ci prezentarea vizuală — un
recrutor se uită 40 de secunde, iar patru diagrame explicate spun mai mult decât
un arbore de fișiere. Repo-ul îl pui în Projects, prezentarea în Featured.

**Ce a rămas afară, și rămâne:** cele 17 cărți. Sunt volume publicate, sub drept de
autor; `.gitignore` le ține afară de la început și le ține în continuare. Ce se
vede public e inventarul din `content/books/md/README.md` — titlu, autor, pagini,
număr de cuvinte, cum a fost extras fiecare. Asta demonstrează corpusul fără să
distribuie textul, ceea ce e chiar mai bine la un interviu decât fișierele: arată
că te-ai gândit la licențiere.

## 5 · Ordinea în care aș face-o acum

1. **Featured** — prezentarea vizuală, cu titlul și descrierea de la §2.
2. **Projects** — intrarea de la §1, cu linkul de GitHub, *Currently working on
   this* bifat și data de început cea mai recentă.
3. **About** — paragraful de la §3, la final.
