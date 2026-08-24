# Handoff — 2026-08-24, sesiunea de după cea de cost

Ramura: `deploy`. Ultimul handoff (munca de cost, $0.2490 → $0.0470) e la
commit-ul `bb795cf` — `git show bb795cf:HANDOFF.md`.

## ⚠️ Starea în care e agentul acum

**Promptul nu mai are contractul de ieșire.** Cele zece reguli au fost tăiate din
`BASE_INSTRUCTIONS` în constanta `OUTPUT_RULES` din
[worker.py](src/content_studio/worker.py) și **nu sunt atașate nicăieri**.

Concret, până sunt puse la loc, agentul rulează fără: „nu inventezi cifre"
(regula 7), „sursa nu intră în caption" (regula 8), „Lucruri pe care nu le spui
niciodată" (regula 2), verificarea de mod Internet, și regula 10.

**Nu se face un lot real în starea asta.** E o etapă intermediară cerută
explicit, nu o scăpare. Textul e păstrat întreg fiindcă `evals/cases.json`
asertează pe regulile 7, 8 și 10.

## Ce s-a făcut și e urcat

Două commit-uri, `bb795cf..cd8b00e`, împinse pe `origin/deploy`.

### `6a50291` — promptul spune adevărul despre uneltele pe care le are

Trei lucruri, toate din aceeași familie: text care descria o realitate veche.

1. **Nota de metodă mințea.** Spunea „nu ai fișiere: nu încerca să deschizi
   nimic", în timp ce fiecare `SKILL.md` trimitea modelul la `references/...`.
   Acum e funcție de ce e atașat efectiv: `skill_tool_method_note(references=…)`.
2. **Unealta `citeste-referinta`**, cu enum peste cele 15 fișiere de pe disc.
   Căutarea merge prin dicționar, deci `../../.env` nu e o cheie — traversarea e
   imposibilă prin construcție, nu printr-o verificare la runtime.
3. **Lista de unelte era scrisă de mână** — promitea cinci; în chat sunt șapte,
   în generare trei. `data_tool_note(server)` o citește din `tool_filter`.

Plus măsurătoarea: `evals/references.json` (când ar trebui să pornească fiecare)
și `evals/references.py` (dacă a pornit). Vezi mai jos.

### `cd8b00e` — promptul se poate inspecta fără să pornească nimic

`tests/checks/prompt.py` construiește agentul exact ca o rulare reală, dar cu un
server MCP care nu se conectează niciodată. Fără bază de date, fără OpenAI, fără
cost. Rulează ambele forme (CHAT / GENERARE).

Configurația `Prompt (build_worker)` din `.vscode/launch.json` — singura din
fișier cu `justMyCode: false` și cu `-X frozen_modules=off`.

## Cifrele de plecare, măsurate

```
prompt   CHAT       5.097 → 1.493 caractere   (~1.456 → ~426 token-i)
prompt   GENERARE   5.097 → 1.427 caractere   (~1.456 → ~407 token-i)
```

```
uv run python evals/references.py
  → 5 din 15 referințe nu sunt numite de niciun SKILL.md (nu pot porni deloc)

uv run python evals/references.py --traces --minutes 20160
  → 100 de ture de model, 0 citiri de referință
```

Astea sunt baza de comparație pentru orice se face mai departe.

## Problema nerezolvată: breakpoint-urile nu se leagă

Simptom: bulina roșie apare, la pornirea sesiunii devine cerc gol, **în orice
fișier**. Nu s-a rezolvat.

**Ce s-a eliminat deja — nu refaceți:**

- `debugpy 1.8.21` e instalat în `.venv`
- extensiile sunt toate: `ms-python.python`, `ms-python.debugpy`,
  `ms-python.vscode-pylance`, `ms-python.vscode-python-envs`
- porturile 5678 (harness) și 5679 (MCP) ascultau și **acceptau** conexiuni
- `content_studio.worker` e importat la nivel de modul în harness
  ([service.py:87](src/content_studio/harness/service.py:87),
  [chat.py:26](src/content_studio/harness/chat.py:26),
  [generator.py:41](src/content_studio/harness/generator.py:41)) — deci într-un
  attach pe harness s-AR lega; în MCP server nu, fiindcă acolo nu e importat
- nu există o a doua copie a proiectului pe disc
- nu există drive-uri substituite (`subst` e gol)
- majuscula drive-ului e consecventă (`E:`) în toate procesele

**Ce s-a găsit pe drum și era real:** la un moment dat `Code.exe` era deja
ESTABLISHED pe 5678. `debugpy` acceptă un singur client, deci al doilea attach e
refuzat tăcut — exact ce arată ca „nu se atașează". Se verifică cu:

```
netstat -ano | findstr ":5678"
```

**Următorii pași de diagnostic, în ordine:**

1. **Tooltip-ul cercului gol.** VS Code scrie acolo motivul exact. E cea mai
   informativă propoziție din tot procesul și încă n-a fost citită.
2. `Ctrl+Shift+P` → `Debug: Start Debugging` pornește configurația **selectată în
   dropdown**, nu una aleasă. Se alege explicit din `Ctrl+Shift+D`.
3. Breakpoint pe `agent = build_worker(...)` din
   [tests/checks/prompt.py](tests/checks/prompt.py) — e în fișierul pornit, nu
   într-un modul importat. Dacă **ăsta** rămâne gol, cauza nu e potrivirea de
   căi.
4. Dacă și ăla e gol: `Help → Toggle Developer Tools → Console`, și panoul
   `Output → Python Debugger`.

## Ce așteaptă o decizie

1. **Unde se duc cele zece reguli.** Trei variante puse pe masă; recomandarea
   era a doua: regulile 2, 7, 9, 10 rămân în prompt (siguranță, mereu active),
   iar 1, 3, 4, 5, 8 și blocul Internet trec în `SKILL.md` (metodă). Blochează
   tot restul.
2. **Cinci declanșatoare marcate `proposed: true`** în `evals/references.json`:
   `propune-postari/carti.md`, `dezvolta-postarea/piloni-si-cont.md`,
   `tipuri-de-reels.md`, `intrebari-frecvente.md`, `idei.md`.
   La `idei.md` (39 KB) e o suspiciune separată: conținutul e material de Faza 1,
   dar fișierul stă în skill-ul de Faza 2. Poate e în folderul greșit.
3. **`hookuri.md` e marcat `forbidden` în modul TITLURI** — acel mod nu scrie
   hook-uri, deci fișierul ar fi plătit degeaba. Decizie luată de agent, merită
   confirmată sau schimbată în `optional`.
4. **Domeniul fazei DETALII.** Rulează de zece ori per lot și nu se cachează după
   punctul de divergență: toate referințele metodei ≈ +$0.05/lot, doar cea de
   format ≈ +$0.01/lot.

## Ce urmează, după decizii

**Rescrierea celor două `SKILL.md`.** Acolo e tot rostul muncii de azi: unealta
există și merge, dar corpurile skill-urilor spun încă „deschizi
`references/piloni.md`" — verbul unui shell care nu mai există, și o cale care
nici măcar nu e cheie validă în enum (cheia e `propune-postari/piloni.md`).
De-aia măsurătoarea arată 0 din 15.

**Nu se sparge niciun fișier de referință** — instrucțiune explicită.

## Un defect găsit, neatins

[evals/run.py:45](evals/run.py:45):

```python
SKILL_PATTERN = re.compile(r"\.agents[/\]([\w-]+)[/\]SKILL\.md")
```

Se aplică pe **argumentele apelurilor de unelte**, adică pe o cale din sandbox.
De când skill-urile sunt unelte, unealta de skill nu ia niciun argument
(`_NO_ARGS`), deci regexul nu se potrivește niciodată și mulțimea `skills`
rămâne mereu goală. **Cazul 13 — „Trigger: `propune-postari` fires" — pică acum
chiar și când skill-ul chiar pornește.** Aceeași clasă de defect: cod scris
pentru sandbox care a supraviețuit sandbox-ului. Fix: skill-urile se citesc din
numele uneltelor, nu din argumente.

## Comenzi

```
uv run ruff check .
uv run python -m unittest discover -s tests/unit      # 243 de teste
uv run python tests/checks/prompt.py                  # promptul si uneltele
uv run python evals/references.py                     # auditul static
uv run python evals/references.py --traces --minutes 30
```

Deploy: `powershell -File infra/deploy.ps1 -LocalBuild` — cere Docker Desktop
pornit. CI rulează doar pe `main` și `english`, deci push-ul pe `deploy` nu
declanșează nimic.
