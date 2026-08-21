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
  actualizarea lui `DATABASE_URL` și `DATABASE_URL_DIRECT` în `.env`. **Rămâne
  deschisă.** Nu se poate face din MCP-ul Neon — nu există unealtă de resetare a
  parolei unui rol; se face din consola Neon, iar `.env` se actualizează după.
  Momentul e bun cât timp nimic nu e provizionat în Azure: nu are ce să strice.
- ~~Artifactul „Codul Studio Viorela" e cu un rând în urmă...~~ **Greșit.**
  Verificat pe 20 august prin descărcarea artefactului publicat și diff cu
  `docs/tutorial-ro.html`: conținutul e **identic**, rândul despre `ui/**/dist`
  este acolo. Singurele diferențe sunt învelișul injectat de platformă și un
  `<title>` diferit — artefactul se numește „Codul Studio Viorela", fișierul are
  „Codul, pe înțelesul celui care îl trimite în producție". Nu e nimic de
  republicat.
- ~~`docs/tutorial.html` și `docs/tutorial-ro.html` sunt depășite pentru harness,
  generator și UI.~~ **Închis pe 21 august**, prin ștergere, la cererea lui Sorin.
  Amândouă descriau era CLI și niciunul nu cunoștea multi-user-ul, bugetele sau
  observabilitatea. Locul lor îl ia `docs/manual.html`, scris pe starea de azi.
  Un tutorial depășit e mai rău decât niciunul: cine îl citește nu află că e
  vechi, află lucruri neadevărate.
- ~~Branch-ul temporar Neon `schema-check-tmp`...~~ Rezolvat pe 19 august: toate
  cele patru branch-uri secundare (`schema-check-tmp`, `pre-deployment-2026-08-17`,
  `pre-d4-course-schema-2026-08-17`, `pre-curatare-2026-08-19`) au fost șterse la
  cererea lui Sorin. Rămâne doar `main`, curat.

---

## 7. Predare către Codex — 19 august, continuare seara

Sorin a rămas fără credit Claude în timpul unei sesiuni **pur explicative**, fără nicio
modificare de cod. Zero fișiere schimbate — `git status` curat, ultimul commit tot
`b846c5f`. Nu e nimic de verificat cu ruff/teste, pentru că nu s-a atins nimic.

**Ce s-a discutat:** Sorin a cerut să înțeleagă, linie cu linie, un Dockerfile de
*referință* dintr-un curs (`Maya's Tier-1 Support harness`, `maya_harness.main:app`) —
**nu** aparține acestui proiect, a fost doar exemplu didactic înainte de a scrie
Dockerfile-ul real de la D2. S-a explicat:

- diferența kernel vs. SO, de ce un container nu are propriul kernel ci îl împrumută
  de la host (și de ce Docker Desktop pe Windows ține un VM Linux prin WSL2 dedesubt);
- familiile de imagini de bază Linux — `alpine` (musl, wheel-uri manylinux incompatibile
  fără recompilare), `debian:*-slim` (glibc, compromisul folosit deja de proiect prin
  `python:3.12-slim`), `debian`/`ubuntu` complet, `distroless`, `scratch`;
- `COPY --from=<imagine>` ca truc multi-stage pentru a lua binare deja compilate
  (`uv`/`uvx`) fără `pip`/`curl` în imagine;
- `WORKDIR`, structura standard de directoare Linux (`/app` e convenție Docker, nu
  standard FHS; `/opt`/`/usr/local` ar fi „corecte" clasic; `/root` vs `/home`);
- caching-ul pe layere: de ce se copiază `pyproject.toml`+`uv.lock` și se rulează
  `uv sync --no-install-project` **înainte** de `COPY src`, apoi un al doilea
  `uv sync` fără acel flag — ca modificările de cod să nu invalideze cache-ul
  dependențelor;
- ce înseamnă „instalare" de pachete Python (de regulă doar dezarhivare de wheel,
  compilare doar când lipsește un wheel precompilat pentru platformă — legătura cu
  problema `musl` de la Alpine) și diferența față de instalarea proiectului propriu
  (editable install, fără compilare, doar leagă `src/content_studio` de sistemul de
  import);
- `ENV PATH="/app/.venv/bin:$PATH"` — de ce `uvicorn` din `CMD` nu s-ar găsi altfel.

**Unde a rămas, concret:** Sorin înțelege acum fundamentele suficient ca să treacă la
scrierea Dockerfile-ului **real** al proiectului (Decizia D2). Nu a fost scris încă
niciun rând — nu există `Dockerfile`, `.dockerignore` sau `infra/` în acest repo.

**Ce trebuie să facă Codex, la reluare:**

1. Nu relua explicațiile de mai sus decât dacă Sorin cere clarificări — le are deja.
2. Următorul pas real e scrierea propriu-zisă a `Dockerfile`-ului pentru
   `content-studio-fte`, cu structura deja discutată conceptual: bază
   `python:3.12-slim`, `uv` copiat din `ghcr.io/astral-sh/uv:latest`, cache pe layere
   (deps înainte de sursă), `ENV PATH` spre `.venv/bin`.
3. Proiectul are **două componente de construit**, nu doar harness-ul Python — UI-ul
   Blazor (`ui/StudioViorela`) trebuie compilat separat, cu SDK .NET, într-un stage de
   build care nu ajunge în imaginea finală (multi-stage), iar rezultatul (`dist/wwwroot`)
   copiat peste în stage-ul final Python. **Obligatoriu `-c Release`** la publish —
   altfel `ApiBaseUrl` rămâne greșit copt în `dotnet.js` (vezi §4 mai sus).
4. Decizie deschisă, de rezolvat înainte sau în timpul scrierii Dockerfile-ului:
   `dist/wwwroot` are variante precomprimate (`.br`/`.gz`) pe care `StaticFiles` din
   Starlette nu le servește azi. Trei căi posibile — middleware mic care preferă
   `.br`, `GZipMiddleware`, sau acceptă necomprimat deocamdată — decizia îi aparține
   lui Sorin, nu presupune Codex una din ele fără să întrebe.
5. Restul contextului de deployment (D0-D1b, deja acceptate; D3/D4 neatinse încă),
   în [DEPLOYMENT.md](DEPLOYMENT.md).
6. Regulile de la §5 rămân valabile neschimbate: rulările care costă bani sunt decizia
   lui Sorin, fără commit/push fără cerere explicită, `.env` niciodată în imagine.

---

## 8. D2 — începută de Codex, dusă la capăt de Claude Code pe 19 august

Sorin a decis să păstreze arhitectura actuală cu serverul MCP `content-data`.
Discuția a clarificat că nu este obligatoriu pentru un singur Worker, dar devine
infrastructură reutilizabilă dacă apare un al doilea Digital FTE. Nu redeschide
această decizie fără motiv concret.

Sorin a aprobat D2 și a ales explicit optimizarea UI: serverul Python trebuie să
servească variantele Blazor precomprimate — **Brotli preferat**, apoi gzip, apoi
fișierul necomprimat. Aceasta este o decizie luată, nu o întrebare rămasă.

Zonele `Container + infra` și `Harness` au fost eliberate în `DEPLOYMENT.md` după
verificare; board-ul e la zi cu dovezile reale.

### Ce s-a implementat

1. **`Dockerfile` nou** — o singură imagine multi-stage:
   - `mcr.microsoft.com/dotnet/sdk:10.0` publică
     `ui/StudioViorela` cu obligatoriu `-c Release`, într-un `/ui-publish` temporar;
   - imaginea finală este `python:3.13-slim`, nu 3.12 (atât proiectul, cât și
     `uv.lock` cer `>=3.13`);
   - `uv` este fixat la `ghcr.io/astral-sh/uv:0.11.28`, versiunea instalată local;
   - dependențele sunt instalate înaintea sursei cu
     `uv sync --frozen --no-dev --no-install-project`, pentru cache;
   - apoi se copiază `README.md`, `src/`, `skills/` și numai `wwwroot` rezultat din
     stage-ul .NET; al doilea `uv sync --frozen --no-dev` instalează proiectul;
   - `PATH` include `/app/.venv/bin`, `PYTHONUNBUFFERED=1`,
     `PYTHONDONTWRITEBYTECODE=1`;
   - declară `EXPOSE 8000 8765`. Comanda implicită este harness-ul:
     `uvicorn content_studio.harness.main:app --host 0.0.0.0 --port 8000 --proxy-headers`.
     La D3, al doilea Container App va suprascrie comanda cu
     `content-studio-server` și va primi `MCP_HOST=0.0.0.0` plus `MCP_URL` intern
     corect pentru harness.

2. **`.dockerignore` nou** — exclude `.env`/`.env.*`, `.mcp.json`, medii și cache-uri
   Python, rezultate .NET (`bin`, `obj`, `dist`), `content/` (inclusiv materialele
   clientei), Git/editor state, documentație, teste și evals. Nu se copiază `.env`
   în imagine.

3. **`static_ui.py`** — `BlazorStaticFiles` a primit negociere de encoding:
   - citește `Accept-Encoding`, inclusiv `q=0`;
   - dacă există fișierul cerut cu `.br` și clientul acceptă `br`, îl servește;
   - altfel încearcă `.gz` pentru `gzip`, apoi originalul;
   - setează `Content-Encoding`, mime type-ul fișierului original și
     `Vary: Accept-Encoding`;
   - păstrează fallback-ul SPA spre `index.html`, inclusiv când o variantă
     precomprimată lipsește; rutele `/api/` nu devin fallback SPA.

4. **`test_static_ui.py`** — trei teste noi: preferință Brotli, fallback gzip când
   `br;q=0`, și fallback necomprimat. Testele `HEAD` verifică antetele fără ca
   `TestClient` să încerce să decomprime fixture-uri artificiale.

### Dovezi deja verificate (toate gratuite)

- `uv run ruff check .` — **All checks passed**.
- `uv run python -m unittest discover -s tests/unit` — **110 tests OK**.
- `dotnet test ui\StudioViorela.Tests\StudioViorela.Tests.csproj --no-restore --configuration Release`
  — exit code **0**; a compilat UI-ul și proiectul de teste în `Release`.
- Testele țintite `tests.unit.test_static_ui` au fost verzi înainte de suita completă.

Nu s-au pornit generări, evals plătite, `tests/checks/*`, nu s-a scris în Neon și
nu s-a făcut niciun save de business.

### Build Docker: reluat și dus la capăt pe 19 august, seara

Build-ul fusese **întrerupt de Sorin** la stage-ul .NET (`dotnet restore`), nu de o
eroare a Dockerfile-ului. La reluare, blocajul real nu avea legătură cu Docker
file-ul: motorul Docker răspundea `500` pe orice rută de API, pentru că
distribuția WSL `docker-desktop` — VM-ul care furnizează kernel-ul Linux — era
oprită. Pornirea distribuției singure **nu** a fost suficientă; `docker desktop
restart` a rezolvat. De reținut înainte de a suspecta iar un fișier de build.

Apoi `docker build --tag content-studio-fte:d2 .` a ieșit cu cod 0. Imaginea are
**425 MB**. Un avertisment lăsat intenționat nerezolvat: lipsește workload-ul
`wasm-tools`, deci publicarea Blazor rulează „without optimizations" — ține de
mărime/AOT, nu de compresie, și instalarea unui workload în imagine e o decizie a
lui Sorin, nu o reparație de strecurat.

### Ce s-a verificat în containere, cu rezultate

Două containere pe o rețea Docker comună, exact topologia prevăzută pentru D3
(MCP cu `content-studio-server` + `MCP_HOST=0.0.0.0`, harness cu
`MCP_URL=http://studio-mcp-test:8765/mcp`):

| verificare | rezultat |
|---|---|
| `/health` | prima cerere `degraded` — Postgres a lovit timeout-ul de 3 s la pornirea la rece a Neon, exact riscul deja notat la §3 pentru D3; a doua cerere **`ready`** în ~1 s, MCP cu 7 unelte |
| UI la `/` | HTTP 200, `Studio Viorela` |
| fallback SPA `/generator` | HTTP 200, servește `index.html` |
| rută `/api/` inexistentă | HTTP 404 — fallback-ul nu înghite rutele API |
| `Accept-Encoding: br, gzip` | `content-encoding: br`, 21.949 B, `application/wasm`, `Vary: Accept-Encoding` |
| `Accept-Encoding: br;q=0, gzip` | cade pe `gzip`, 26.333 B — `q=0` respectat |
| `Accept-Encoding: identity` | 62.741 B, fără `Content-Encoding` |

**Integritatea octeților, nu doar antetele:** răspunsul gzip se decomprimă
byte-identic cu fișierul original, iar cel Brotli e identic cu `.br`-ul produs de
.NET și se decomprimă în același original. 53 fișiere `.br` și 53 `.gz` ajung în
imagine.

**Igiena imaginii:** niciun `.env` și niciun `content/` înăuntru; `skills/` e
prezent, cum îi trebuie sandbox-ului.

**O capcană de știut:** `config.py` derivă `PROJECT_ROOT` din
`Path(__file__).resolve().parents[2]`. Nimerește `/app` **doar** pentru că
`uv sync` instalează proiectul editabil. O instalare non-editabilă l-ar duce în
`.venv`, `UI_STATIC_DIR` ar arăta spre un director inexistent, iar `mount_ui` ar
returna tăcut `False` — container care pornește perfect și nu servește nicio
interfață. Verificat explicit în imagine: `PROJECT_ROOT=/app`, UI și skills se
rezolvă corect.

`uv run ruff check .` curat, 110 teste OK. Fără rulări plătite, fără apeluri de
model, fără scriere în Neon. Containerele și rețeaua de probă au fost șterse
după verificare.

### Ce urmează

1. **D3 — Azure Container Apps** e următoarea decizie, dar rămâne blocată de
   accesul Azure (are nevoie de Sorin pentru MFA). `infra/**` e încă neatins.
2. La D3, de verificat lista de IP-uri de proxy de încredere înainte de a lărgi
   `forwarded-allow-ips`, și de rezolvat pornirea la rece a Neon: proba de
   liveness plus `asyncio.timeout` de 3 s din `health()` nu supraviețuiesc primului
   request după ce containerul doarme — s-a văzut și în proba de azi.
3. Rămâne fără dovadă, din D1b: o **rescriere** reală prin poartă (editarea unei
   postări deja salvate).

### Observații de urmărit, nu modifica fără dovadă

- `--proxy-headers` este păstrat ca în curs; la D3 trebuie verificată lista de IP-uri
  de proxy de încredere pentru Azure Container Apps înainte de a lărgi implicit
  `forwarded-allow-ips`.
- `content/` este exclus intenționat din build context: aplicația în producție nu
  trebuie să transporte materialele locale ale clientei. `skills/` nu este exclus,
  deoarece SandboxAgent îl folosește la runtime.
- În acest repo, `config.py` citește `.env` dacă acesta există, dar containerul
  trebuie să primească secretele prin `--env-file` local / secrets și environment
  configuration în Azure, nu prin `COPY .env`.
