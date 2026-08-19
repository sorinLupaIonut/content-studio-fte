# Predare — sesiunea din 18 august 2026, seara

Notă scrisă la trecerea de la o sesiune Claude Code pornită din folderul cursului
(`C:\Users\sorin\Downloads\AI\deploying-agents`) la una pornită direct din acest
proiect. Tot ce urmează s-a întâmplat în seara asta și nu se vede din cod.

Ramura de lucru: **`deploy`**. Ultimul commit: `4ca8e97`.

---

## Ce e nesalvat în git chiar acum

Cinci fișiere modificate, toate verificate, niciunul commis:

```
 M .vscode/launch.json
 M .vscode/tasks.json
 M src/content_studio/harness/drafts.py
 M src/content_studio/harness/generator.py
 M tests/unit/test_draft_client.py
```

`uv run ruff check .` trece, `unittest discover -s tests/unit` dă 107 teste OK.

---

## 1. Bugul reparat: MCP 2.0 a redenumit câmpurile răspunsului

**Simptomul:** `POST /api/generation-batches` întorcea `502`, cu
`DraftDataError: content-data returned no unambiguous payload` din
`harness/drafts.py`. Generarea nu pornea deloc.

**Cauza:** `mcp` 2.0.0 a trecut câmpurile lui `CallToolResult` pe snake_case, iar
decodorul cerea numele vechi prin `getattr(result, "...", default)` — care nu
ridică nimic, ci întoarce tăcut valoarea implicită:

| ce citea codul | ce există în SDK | efect |
|---|---|---|
| `structuredContent` | `structured_content` | payload-ul se pierdea |
| `isError` | `is_error` | **orice eroare de la `content-data` se citea ca succes** |

A doua linie era mai gravă decât prima.

**Reparația** (`drafts.py`): un `_result_field(result, snake, camel)` care acceptă
ambele ortografii, ca decodorul să reziste indiferent ce versiune de SDK ajunge în
imagine.

**De ce n-au prins-o testele:** `tests/unit/test_draft_client.py` construia
obiecte `SimpleNamespace` cu *aceleași* nume vechi. Testul și bugul se confirmau
reciproc și suita rămânea verde. Testele folosesc acum numele reale, plus o clasă
nouă `RealResultTests` care construiește un `CallToolResult` adevărat din
`mcp_types` — aia nu poate devia de la formatul de pe sârmă.

**Verificat cu bani, cap-coadă:** batch `d0823907-7cba-4e8e-8d0f-b418066b054b`,
`HTTP 202`, titluri generate, 5 idei din 10 ajunse `ready` cu câte 5 variante
complete. Conducta merge.

---

## 2. Debug-ul local: pornire directă nu mai e viabilă, se folosește atașare

**Simptomul:** F5 pe compound-ul vechi părea că îngheață. Terminalul arăta
`Aborted!` sau un traceback terminat în `KeyboardInterrupt` — apăsat de om, nu de
program.

**Cauza, măsurată:**

| ce se importă | excepții ridicate |
|---|---|
| doar biblioteca `mcp` 2.0.0 | 46.347 |
| `content_studio.mcp_server.server` | 90.203 |
| `content_studio.harness.main` | 130.891 |

Vin aproape toate din Pydantic, care ridică și prinde excepții intern când
construiește scheme. Sunt normale. Dar un debugger prezent în timpul importurilor
le inspectează pe fiecare, iar la mărimea asta pornirea trece de la 5 secunde la
minute. Nu e o setare greșită — proiectul a crescut peste ce suportă modul launch.

**Ce s-a exclus pe drum**, ca să nu se reia investigația degeaba:

- Nu e `justMyCode` — vechiul `launch.json` avea aceeași valoare.
- Nu sunt filtrele de excepții — problema persistă cu toate debifate.
- Nu e conflictul `debugpy` 1.8.21 (venv) vs 1.8.20 (extensie) — extensia își
  încarcă toate modulele din propria copie, consistent. Verificat.

**Soluția, în `tasks.json` + `launch.json`:** compound-ul
**`Studio complet (attach pe MCP + harness)`**. Task-urile pornesc cele trei
servicii fără debugger, fiecare deschizându-și portul debugpy prin
`DEBUGPY_PORT` (5679 pentru MCP, 5678 pentru harness — vezi
`src/content_studio/debug.py`); editorul așteaptă linia
`debugger listening on port` și abia apoi se atașează. La momentul ăla importurile
s-au terminat deja.

Vechiul compound e păstrat sub numele `Studio complet (launch direct — lent)`, ca
să fie clar că nu e stricat, doar nepotrivit.

**Două capcane, ambele întâlnite pe viu:**

1. Task-urile trebuie să pornească interpretorul cu `-Xfrozen_modules=off`.
   Fără el, breakpoint-urile se pot lega la nimic, în tăcere. E în `tasks.json`
   acum, dar merită știut că avertismentul pe care îl scrie debugpy despre asta
   nu e zgomot.
2. Oprirea sesiunii de debug **nu** oprește terminalele. Dacă nu le închizi
   explicit, următorul F5 se reatașează la aceleași procese vechi — deci o
   modificare în `tasks.json` pare că n-a avut efect. Verificarea rapidă:
   citește linia de comandă reală a procesului
   (`Get-CimInstance Win32_Process`), nu ce scrie în config.

**Confirmat pe 19 august, dimineața:** steagul `-Xfrozen_modules=off` **este**
prezent în linia de comandă reală a ambelor procese, citită din
`Get-CimInstance Win32_Process`. Nu el era vinovatul.

Cauza reală a fost banală și merită scrisă, ca să nu se mai caute o zi:
**sesiunea de debug nu fusese pornită niciodată.** Logul extensiei
(`%APPDATA%\Code\logs\<data>\window1\exthost\ms-python.debugpy\Python Debugger.log`)
era gol — zero linii — iar `ms-python.debugpy` se activase doar prin
`onLanguage:python`, adică pentru că era deschis un fișier `.py`. Butonul apăsat
nu pornea nimic. Paleta de comenzi rezolvă ambiguitatea: `Ctrl+Shift+P` →
**Debug: Select and Start Debugging**.

Verificarea obiectivă a atașării, fără a te baza pe ce pare în interfață:
`netstat -ano | grep 5678` — doar `LISTENING` înseamnă neatașat, o linie
`ESTABLISHED` înseamnă că editorul e conectat.

---

## 3. Ce a mai ieșit la iveală, nerezolvat

- **`ModelBehaviorError: Invalid JSON when parsing model output`** pe câteva idei,
  cu retry automat. E problema de calitate `gpt-5-mini` deja cunoscută, nu ceva
  nou apărut azi.
- **O cerere de aprobare neașteptată** la generarea titlurilor, o singură dată,
  nereprodusă: `structured generation unexpectedly requested approval`. Mesajul
  spune acum **care** unealtă a cerut-o (`generator.py`, în `_run_on_sandbox`),
  ca data viitoare să nu mai fie nevoie de ghicit.
- **Batch-ul `d0823907` a rămas înghețat** în `generating` (5 idei din 10),
  marcat drept curent, pentru că instanța de probă a fost oprită în timpul
  generării. UI-ul arată corect „Conexiunea live se reface automat" în situația
  asta. Se curăță cu Anulează din interfață sau cu o generare nouă.
- **`/health` răspunde în ~5 secunde** din cauza pornirii la rece a Neon. Contează
  la D3: proba de liveness din Azure și `asyncio.timeout` de 3 secunde din cod
  n-ar supraviețui primului request după ce containerul doarme.

---

## 4. Unde rămăsese deployment-ul

Următoarea decizie e **D2 — Dockerfile multi-stage + `.dockerignore`**. Nu s-a
început; nu există încă `Dockerfile`, `.dockerignore` sau `infra/`.

O decizie deschisă, care blochează scrierea Dockerfile-ului: `dist/wwwroot` conține
fișiere precomprimate pe care `StaticFiles` din Starlette **nu** le servește.

| ce se livrează | mărime |
|---|---|
| necomprimat (ce se servește azi) | 10,9 MB |
| `.br` (există pe disc, nefolosit) | 2,9 MB |
| `.gz` (există pe disc, nefolosit) | 3,7 MB |

Trei căi: un middleware mic care preferă `.br` când clientul îl acceptă,
`GZipMiddleware`, sau se acceptă conștient varianta necomprimată deocamdată.

Mai e un detaliu prins la publicare și neconsumat încă: **Dockerfile-ul trebuie să
construiască explicit cu `-c Release`**. Mediul aplicației Blazor
(`Development`/`Production`) se coace în `dotnet.js` la build, nu se decide la
runtime dintr-un antet HTTP; un build Debug într-un container ar îngheța
`ApiBaseUrl`-ul greșit.

Restul planului, cu tot contextul, în [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 5. Reguli care rămân în picioare

- **Rulările care costă bani sunt decizia lui Sorin.** Nu se pornesc generări
  reale, evals sau `tests/checks/*` fără să ceară el.
- Nu se face commit și nu se dă push fără cerere explicită.
- `.env` nu intră niciodată în imagine; cheile nu apar în loguri, niciodată
  valorile — cel mult numele.
- CLI-ul (`uv run content-studio`) trebuie să rămână funcțional.
- Tot ce citește Viorela e română cu diacritice; identificatorii, comentariile,
  documentația și testele rămân engleză. Mesajele de commit: română fără
  diacritice.
- Regula 1: worker-ul nu atinge baza direct, doar prin `content-data`.
  Regula 2: rândul de audit se comite în aceeași tranzacție cu scrierea pe care o
  descrie. Regula 6: nimic nu se salvează fără confirmarea ei explicită.

---

## 6. De rezolvat, rămase din sesiunile anterioare

- Rotația parolei `neondb_owner` de la Neon (a ajuns într-o transcriere), plus
  actualizarea lui `DATABASE_URL` și `DATABASE_URL_DIRECT` în `.env`.
- Artifactul „Codul Studio Viorela" e cu un rând în urmă față de
  `docs/tutorial-ro.html` (rândul despre `ui/**/dist`).
- `docs/tutorial.html` (engleză, din era CLI) e depășit pentru harness, generator
  și UI.
- ~~Branch-ul temporar Neon `schema-check-tmp`...~~ Rezolvat pe 19 august: toate
  cele patru branch-uri secundare (`schema-check-tmp`, `pre-deployment-2026-08-17`,
  `pre-d4-course-schema-2026-08-17`, `pre-curatare-2026-08-19`) au fost șterse la
  cererea lui Sorin. Rămâne doar `main`, curat.
