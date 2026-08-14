# Cum funcționează și cum testezi

Ghidul acesta pornește cu probele care nu modifică nimic și ajunge treptat la
fluxul complet. Nu trebuie să rulezi din nou importul bazei ca să testezi un
proiect deja instalat.

## Harta proiectului

```text
Viorela
  │
  ▼
worker.py ── profilul complet + cele 10 reguli ──► un singur SandboxAgent
  │                                                   │
  │                                                   ├─ skill propune-postari
  │                                                   └─ skill dezvolta-postarea
  │
  └─ server MCP content-data
       ├─ resursă internă: profilul live (nu este unealtă a modelului)
       ├─ cauta_in_carti       ─► OpenAI embedding + Neon pgvector
       ├─ cauta_pe_internet    ─► OpenAI web search
       ├─ listeaza_postari     ─► Neon
       ├─ save_postare         ─► Neon, numai după aprobare
       └─ update_profil        ─► Neon, numai după aprobare

Audit separat ─► mesaje, skill-uri, apeluri, aprobări și rezultate
```

Worker-ul folosește direct baza numai pentru starea tehnică a conversației și
pentru audit, așa cum cere arhitectura. Profilul, cărțile și postările — datele
de business — trec prin MCP.

## Ce s-a construit, pe scurt

- Deciziile 0–3: proiectul Python, memoria conversației și cele șapte tabele.
- Decizia 4: skill-ul care pune separat cele trei întrebări și apoi produce 10
  propuneri cu câte 5 hook-uri.
- Decizia 5: cele 17 cărți împărțite în 4.778 de pasaje, căutate semantic cu
  `text-embedding-3-small`; fiecare rezultat își poartă proveniența.
- Decizia 6: serverul MCP cu exact cinci unelte și fără `run_sql`.
- Decizia 7: dezvoltarea unei singure propuneri și salvarea ei.
- Decizia 8: audit și `replay.py`, ca să vezi ulterior ce a făcut sistemul.
- Decizia 9: poarta „da / nu” pentru orice salvare sau schimbare de profil.
- Decizia 10: 15 evaluări, inclusiv cazurile dificile și activarea skill-urilor.
- Internet: căutarea web întoarce unghiuri și linkuri. Nu are voie să transforme
  cifre, studii sau citate web în fapte pentru postare.

## Pregătire

Ai nevoie de `.env` cu:

```text
OPENAI_API_KEY=...
DATABASE_URL=...
E2B_API_KEY=...
```

Opționale: `MODEL`, `WEB_SEARCH_MODEL`, `MCP_HOST`, `MCP_PORT`, `MCP_URL` și
`MCP_TIMEOUT`. Valorile sunt explicate în `.env.example`.

Dacă proiectul este proaspăt clonat:

```powershell
uv sync
uv run python -m db.apply
uv run python -m db.seed
```

`db.seed` este pentru instalare sau actualizarea materialului brut. Nu este
necesar la fiecare test.

## 1. Pornește serverul

În primul terminal PowerShell:

```powershell
uv run python -m mcp_server.server
```

Lasă terminalul deschis. Mesajul bun conține:

```text
content-data · cinci unelte · http://127.0.0.1:8765/mcp
```

În toate probele următoare folosești un al doilea terminal.

## 2. Proba sigură de pornire

```powershell
uv run python proba_bootstrap.py
```

Aceasta nu cheamă modelul și nu scrie nimic. Citește profilul prin MCP fără să-i
afișeze conținutul. Trebuie să vezi patru bife: exact cinci unelte, nicio unealtă
SQL, numele clientei și aproximativ 30.000 de caractere de profil.

## 3. Proba izolată pentru internet

```powershell
uv run python proba_internet.py
```

Trimite la OpenAI numai tema generică scrisă în fișier. Nu citește profilul,
cărțile sau postările din Neon. Trebuie să vezi bife pentru status, unghiuri,
surse, titlu + URL și regula anti-fapte. Costă un apel web mic.

## 4. Proba porții, scrierii și auditului

```powershell
uv run python proba_scriere.py
```

Nu cheamă modelul. Creează o conversație de test, simulează o scriere respinsă,
salvează o singură postare dummy, verifică auditul tranzacțional și șterge toate
rândurile probei în `finally`. Ultima linie trebuie să fie:

```text
✓ rândurile de probă au fost șterse
```

## 5. Proba completă a celor cinci unelte

```powershell
uv run python proba_mcp.py
```

Aceasta nu scrie nimic, dar:

- trimite o temă generică la OpenAI pentru embedding;
- citește local pasajele găsite în biblioteca din Neon;
- face o căutare web generică;
- citește titlurile ultimelor trei postări.

Trebuie să se termine cu `TRECUT`. Pentru fiecare pasaj verifică titlul, reperul,
clasa, versiunea, drepturile, proprietarul și modelul embedding.

## 6. Testul manual, exact ca Viorela

Cu serverul încă pornit:

```powershell
uv run worker.py --nou
```

Exemplu de conversație:

```text
tu> Vreau conținut despre vinovăția de a spune nu
```

Comportamentul corect este:

1. întreabă formatul;
2. după răspuns întreabă pilonul;
3. după răspuns întreabă sursa;
4. adună material numai din sursa aleasă;
5. arată 10 propuneri × 5 hook-uri;
6. întreabă ce propunere și ce hook dezvoltă;
7. arată postarea completă;
8. numai după confirmare cere în terminal permisiunea de a salva.

Răspunde `nu` la poartă ca să verifici refuzul. Postarea nu trebuie să apară în
bază. Repetă cu `da` numai dacă vrei intenționat să păstrezi postarea.

Scrie `iesire` sau apasă `Ctrl+C` pentru oprire.

## 7. Vezi urma fără să rulezi modelul

```powershell
uv run python replay.py --lista
uv run python replay.py ID-UL-CONVERSATIEI
```

Vei vedea mesajele, skill-urile deschise, uneltele chemate, cererile de aprobare,
refuzurile și salvările. `replay.py` citește numai auditul.

## 8. Evaluările automate

Un singur caz:

```powershell
uv run python evals/ruleaza.py --id 10
```

Toate cazurile automate:

```powershell
uv run python evals/ruleaza.py --doar-automat
```

Toate cele 15 cazuri:

```powershell
uv run python evals/ruleaza.py
```

Evaluările pornesc E2B și cheamă modelul, deci durează și consumă API. Orice
încercare de scriere este respinsă automat. Raportul ajunge în
`evals/raport-latest.json` și nu este urcat pe Git.

## 9. Fluxul automat cap-coadă

```powershell
uv run python proba_flux.py
```

Este testul cel mai scump și mai lent: nouă ture reale, profil în system prompt,
E2B, căutare în cărți, dezvoltare, poartă și audit. Postarea de probă este
ștearsă, dar auditul conversației rămâne intenționat pentru replay.

## Ce date ies și unde

| Probă | OpenAI | E2B | Neon | Scrie? |
|---|---|---|---|---|
| `proba_bootstrap.py` | nu | nu | citește profilul | nu |
| `proba_internet.py` | temă generică web | nu | nu | nu |
| `proba_scriere.py` | nu | nu | dummy temporar | da, apoi șterge |
| `proba_mcp.py` | teme generice | nu | cărți + titluri postări | nu |
| `evals/ruleaza.py` | profil + mesaje + pasaje folosite | da | citește | refuză scrierile |
| `proba_flux.py` | profil + conversație + pasaje folosite | da | citește și dummy | șterge postarea |

## Limite cunoscute

- „Exact 10 × 5” este o instrucțiune pentru model, nu o schemă rigidă. Probele
  numără rezultatul după generare.
- Regula anti-fapte pentru Internet este întărită în prompt și verificată
  mecanic, dar cazul calitativ 11 rămâne marcat `cu_ochiul`: o persoană trebuie
  să citească dacă o formulare sună totuși ca o afirmație nesusținută.
- Poarta este aplicată pe înregistrarea MCP folosită de worker și protejează
  apelurile agentului. Serverul ascultă numai pe `127.0.0.1`; un script local de
  dezvoltare poate chema intenționat unealta direct, cum face `proba_scriere.py`.
- Interfața actuală este terminalul. O interfață pentru telefon nu face parte
  încă din această etapă.

## Dacă ceva nu merge

- `Nu răspunde nimic la ...8765` → pornește serverul în primul terminal.
- `Lipsește OPENAI_API_KEY / E2B_API_KEY / DATABASE_URL` → verifică `.env`.
- `TimeoutError` la web → păstrează `MCP_TIMEOUT=90` sau mărește-l temporar.
- Serverul pornește pe alt port → `MCP_PORT` și portul din `MCP_URL` trebuie să
  fie aceleași.
- O evaluare este `CU_OCHIUL` → nu este eșec automat; citește `raspuns_final`
  din raport și dă verdictul de conținut.

La final, oprește serverul cu `Ctrl+C`.
