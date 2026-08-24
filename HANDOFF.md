# Handoff — 2026-08-24

Ce s-a făcut azi, unde s-a oprit, și ce urmează. Ramura: `deploy`.

## Rezultatul

Un lot de 10 idei, cu aceleași alegeri (`Memorie · Educație · Reel`):

| | $/lot | loturi din $1 |
|---|---|---|
| La început — cât se **taxa** | $0.2490 | 4 |
| La început — cât **costa** cu adevărat | $0.0886 | 11 |
| **Acum** | **$0.0470** | **21** |

Din cele 5,3×, **2,8× era o factură greșită** — token-ii din cache erau taxați
la preț întreg. Restul e muncă reală pe token-i.

```
                    ÎNCEPUT      ACUM
apeluri OpenAI         51         24
prefix             18.304     ~12.400
ture per idee        ~4,25        2,0
ratări de cache          5          2
rată de cache          86%        87%
idei complete        10/10      10/10
```

## Cele șapte commit-uri

```
6693684  Antetul lotului nu mai spune ca e gata ce nu e
9b83126  Descrierea skill-ului acopera si modul UI, titlurile pe mini
cc850ea  Skill-urile devin unelte, sandbox-ul dispare de peste tot
3e8265b  Generarea poate rula si fara sandbox, in spatele unui comutator
85e75d7  Un singur slot incalzeste cache-ul, restul il citesc
eaa7fb2  Agentul nu mai cauta skill-ul, i se spune unde e
8809d43  Token-ii din cache nu mai sunt taxati la pret intreg
```

## Schimbări de arhitectură

**Sandbox-ul E2B a dispărut** — din chat, din generare, din CLI. Fiecare folder
de skill e acum un `FunctionTool`, numit și descris din propriul frontmatter:
`worker.py` → `skill_tools()`, `parse_skill()`. `USE_SANDBOX=1` reactivează
calea veche; ramura se poate șterge când nu mai e nevoie de comparație.

Regula 4 din AGENTS.md descrie încă sandbox-ul — **trebuie rescrisă.** Ce a
supraviețuit din ea, și e important: skill-urile sunt tot foldere pe disc,
descrise de ele însele, iar descrierea e tot ce decide dacă corpul metodei se
plătește vreodată. S-a schimbat doar livrarea.

**Titlurile au trecut de pe nano pe mini.** Costă +$0.0020 pe lot; cache-ul
comun compensează doar o parte. **Mutarea se plătește din calitate, nu din cost.**

## Lecția care merită reținută

**Descrierea skill-ului e cea care decide, nu promptul.**

Ambele descrieri erau scrise pentru conversație — *„folosește-l când Viorela
cere: «vreau un reel despre limite»"*. Dar generarea nu trimite replici, trimite
un formular. Niciun declanșator nu se potrivea, așa că nano n-a chemat niciodată
`propune-postari` și a scris zece titluri din memorie:

```
ÎNAINTE                              DUPĂ
Educație fără oboseală…              Cum începi să spui NU fără să te pierzi
3 pași pentru curiozitate…           Ce ascunde vinovăția când spui NU
De ce rămânem blocate în             3 întrebări care te opresc din a spune
  overhead-ul zilnic                   DA din reflex
```

Remedierea a fost o propoziție în frontmatter: „Îl folosești OBLIGATORIU și în
MOD UI STRUCTURAT D1B". Fără cod.

## Ce s-a mai reparat

- **Profilul** — secțiunea CTA (5 din 6 subsecțiuni erau `⚠️ DE COMPLETAT`) și
  subsolul de changelog, scoase. **Aplicat pe toate cele patru rânduri din
  `clients` în Neon**, nu doar local: la runtime profilul vine din bază, iar
  `content/profile.md` e doar sămânța.
- **Antetul lotului** minea când o idee pica — `readyIdeas` era primit și ignorat.
- **Deploy-ul** — un singur tag `:current`, deployat **pe digest** (altfel
  Container Apps nu face revizie nouă), curățenie locală și în ACR după push.

## Ce am greșit pe parcurs, ca să nu se repete

1. **Am dat 42% economie pentru scoaterea sandbox-ului.** Comparasem cu un lot
   care încă avea un bug reparat între timp. Real: 10–19%.
2. **Era să șterg imaginea din producție.** Scrisesem „șterge manifestele fără
   tag" — dar tag-ul e un **index OCI** care referă doi copii fără tag. Cei „60
   de orfani" erau copiii celor 30 de taguri. Regula corectă: șterge **după tag**.
3. **`group_id` nu devine `session.id` în Phoenix.** Afirmat, verificat, fals.

## Ce rămâne deschis

- **MCP rămâne** — decizia lui Sorin, nu se atinge. Măsurat: 17 ms pe lot, deci
  nu el e problema de latență. `minReplicas: 0` e. Fix de o linie în `main.bicep`.
- **`references/`** (137 KB) nu e citit de nicio rulare. Metoda din ele nu ajunge
  niciodată la model. E o întrebare de calitate, nu de cost.
- **Evals (Decizia 8)** — niciun punct de atașare nu există încă. Sunt singura
  dovadă reală pentru orice atinge textul ei.
- **`gpt-5-nano` pe detalii** — respins explicit, scade calitatea prea mult.
- **AGENTS.md, regula 4** — descrie sandbox-ul care nu mai există.

## Cum verifici un lot

```sql
SELECT model, split_part(kind,'-idea-',1) LIKE '%-titles' AS titluri,
       count(*) AS rulari, sum(input_tokens) AS input,
       sum(cached_input_tokens) AS din_cache,
       round(100.0*sum(cached_input_tokens)/NULLIF(sum(input_tokens),0)) AS pct_cache,
       sum(output_tokens) AS output, sum(cost_micros) AS micro
FROM public.usage_events WHERE created_at > NOW() - INTERVAL '15 minutes'
GROUP BY 1,2;
```

Numărul de ture și apelurile de skill se citesc din `public.traces`, filtrând
`span_data.type` pe `response` și `function`.

## Înainte de commit

```
uv run ruff check .
uv run python -m unittest discover -s tests/unit     # 225 de teste
```

Deploy: `powershell -File infra/deploy.ps1 -LocalBuild` — cere **Docker Desktop
pornit**, fiindcă `az acr build` e refuzat pe Free Trial (`TasksOperationsNotAllowed`).
