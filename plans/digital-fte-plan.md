# Plan: Content Studio Vio ca Digital FTE

Versiunea Python a aplicației, construită după arhitectura din **Building a Digital FTE: A 4-Hour Crash Course**, Partea 4 — https://agentfactory.panaversity.org/docs/digital-fte-crash-course

Documentul ăsta e planul. Nu se scrie cod până nu e aprobat.

> **Revizia 3** (13 aug 2026) — aliniat la forma de azi a lui `content-studio-vio-2`: fluxul are **două faze** (10 propuneri → se dezvoltă una singură), **patru întrebări obligatorii** (format, pilon, sursă, alegere), **patru surse de material** (cărți / internet / memorie / combinat), **trei skill-uri** în loc de unul, și **două tabele de domeniu** (`client`, `postari`). Cad `surse`, `invarianti`, `exceptii`, `cta` ca tabele. Revizia 2 presupunea un singur Skill care scotea direct 10 postări complete — nu mai e cazul.
>
> **Revizia 4** (14 aug 2026) — două decizii care simplifică arhitectura, nu domeniul:
>
> 1. **Rămâne un singur client, Viorela.** Multi-tenant (izolare, RLS, upload self-service, onboarding din Instagram) e amânat, nu anulat — motivul e o felie completă cap-coadă, nu un SaaS pe jumătate. Singura urmă lăsată azi: `documents.client_id`, o coloană, mereu aceeași valoare, ca ziua în care apare a doua clientă să fie migrare de date, nu de schemă.
> 2. **Fără `SandboxAgent`.** Testul din [Build AI Agents, Conceptul 14](https://agentfactory.panaversity.org/docs/build-agents-crash-course): sandbox se cere doar când agentul are nevoie de shell, pachete, date montate sau **fișiere pe care el însuși le citește/scrie**. Uneltele MCP ale planului lovesc toate un API peste HTTPS — niciun declanșator nu se aprinde. Singurul motiv pentru care Revizia 3 avea sandbox era `metoda/` ca `references/` pe disc și înlănțuirea skill-urilor prin `tmp/*.md`. Ambele dispar: `metoda/` devine unealtă MCP (`get_metoda`), iar înlănțuirea trece prin obiecte Pydantic. Corolar: `Skills()` din SDK (folderele auto-descoperite, cu progressive disclosure pe trei etape) nu se mai folosesc.
> 3. **Un orchestrator, doi sub-agenți chemați ca unelte** (`Agent.as_tool()`), nu trei agenți legați prin `handoffs`. Vezi §1.1 pentru de ce — pe scurt: fluxul se **întoarce** (ea poate cere dezvoltarea încă unei propuneri din aceeași listă), iar un `handoff` transferă controlul definitiv.
>
> **Revizia 5** (14 aug 2026) — **punctele 2 și 3 ale Reviziei 4 se anulează.** Decizia 4 s-a construit întâi cu sub-agenți și `as_tool`, a funcționat, și a fost ștearsă la cerere: forma dorită era cea din Revizia 3, cu sandbox și skill-uri. Ce rămâne valabil din Revizia 4: punctul 1, un singur client.
>
> 1. **`SandboxAgent` cu `Skills(from_=LocalDir("skills"))`.** Fazele sunt foldere `SKILL.md` cu `references/`, nu obiecte `Agent`. Progressive disclosure real: indexul mereu în context, corpul la potrivire, referințele doar dacă `SKILL.md` trimite acolo. Verificat la Decizia 4 — faptul că azi merge doar sursa Memorie a fost pus **numai** în `references/surse.md`, iar agentul l-a găsit. Metoda se editează fără să atingi codul.
> 2. **Un singur agent, nu orchestrator plus sub-agenți.** Un context, deci profilul de 30k caractere nu se mai copiază în promptul fiecărui agent.
> 3. **Prețul, plătit cu ochii deschiși:** un `SKILL.md` e text, deci „exact 10 propuneri × exact 5 hook-uri" nu se mai impune din `output_type`. Devine instrucțiune, verificată **după** (`proba_flux.py`) și judecată la Decizia 10. La fel se pierd uneltele atribuite pe fază: un singur agent le are pe toate.
> 4. **Sandbox-ul e E2B**, nu Docker. Premisa Reviziei 4 („nu Docker, fiind Windows") era greșită — Docker era instalat și a mers, dar pe Windows calea PTY a backendului întoarce output gol, fiindcă `NpipeSocket.shutdown()` din docker-py închide toată conducta în loc de jumătatea de scriere. E2B n-are problema, are tier gratuit, și a fost mai rapid în practică (96s vs 158s pe aceleași cinci ture).
> 5. **`get_metoda` dispare ca unealtă MCP.** Manualul de Reels s-a spart în nouă `references/` lângă skill-ul Fazei 2, deci metoda vine prin același progressive disclosure ca pilonii și hook-urile. Serverul MCP a avut patru unelte la Decizia 6; a cincea adăugată ulterior este `cauta_pe_internet`, nu întoarcerea metodei în MCP.

---

## 0. De unde plecăm

**Fluxul, așa cum e azi.** Două faze, și alegerea ei stă între ele:

1. **Faza 1** — patru întrebări (format → pilon → sursă → alegere) și **10 propuneri**, fiecare cu titlu, ideea în 1–2 fraze și **5 hook-uri, câte unul din fiecare tip**.
2. **Faza 2** — se dezvoltă **doar propunerea aleasă**: script, caption, hashtaguri, CTA. Celelalte nouă rămân în chat și nu se salvează.

*(Transcrierea materialului Brand Legends confirmă fluxul platformei: profil completat o dată, apoi pilon + format, apoi zece idei cu cinci hook-uri fiecare. Revizia 2 sărea peste stadiul de idee; revizia 3 îl pune la loc, pentru că alegerea Viorelei între cele zece e chiar valoarea, iar dezvoltarea tuturor celor zece e muncă aruncată.)*

**Ce există deja și rămâne valabil.** `AGENTS.md` din `content-studio-vio-2` e specificația domeniului: cei 5 piloni, cele 5 tipuri de hook-uri, cele 4 surse, cele 9 reguli obligatorii de generare, cele două faze. Nu se rescrie — se traduce în arhitectura Worker-ului.

**Ce se schimbă.** Azi capabilitatea stă în `AGENTS.md` + `.claude/commands/postare.md`, iar adevărul stă în Markdown sub git. Într-un Worker: capabilitatea se împarte în **skill-uri-foldere montate în sandbox** (Revizia 5), adevărul se mută în **Postgres** (system of record), iar accesul la el trece printr-un **MCP server** propriu. Git rămâne sistemul de record până atunci — asta e ce înlocuiește Postgres, nu „nimic".

**Unde se construiește.** Folder nou, `E:\aplicatii_noi\content-studio-fte`. `content-studio-vio-2` rămâne funcțional pentru Viorela cât timp lucrăm la înlocuitor.

**Stack**: OpenAI Agents SDK, proiect `uv`, Neon Postgres + pgvector, MCP Python SDK, `text-embedding-3-small`. **Sandbox E2B** (Revizia 5) — `SandboxAgent`, cu `skills/` montate din proiect. Modelul, mai jos.

**Modelul: `gpt-5-mini`.** Prețuri din documentația OpenAI:

| Model | Input / 1M | Input din cache / 1M | Output / 1M |
|---|---|---|---|
| `gpt-5-mini` | $0.25 | $0.025 | $2.00 |
| `gpt-5-nano` | $0.05 | $0.005 | $0.40 |

Un ciclu complet: profilul întreg în system prompt plus eventualele pasaje găsite (~12–20k tokeni la intrare), cele 10 propuneri (~3–4k la ieșire) și postarea dezvoltată (~1k). **Sub 2 cenți pe `gpt-5-mini`.** Estimare, nu factură — se măsoară la Decizia 7.

Alegerea e `mini`, nu `nano`, dintr-un singur motiv: sarcina nu e „scrie zece titluri", ci „scrie zece unghiuri diferite în vocea Viorelei, respectând lista de interdicții, cu cinci tipuri distincte de hook fiecare, fără să repeți aceeași idee". Constrângerile astea sunt exact ce se pierde primul la un model mai mic, iar rezultatul care sună a robot e chiar eșecul pe care aplicația trebuie să-l evite.

Embedding-urile rămân `text-embedding-3-small` indiferent de model. Regula din curs se aplică: **același model la stocare și la căutare**, altfel căutarea semantică întoarce gunoi.

---

## 1. Brief-ul Worker-ului

Un **Content Worker** pentru Viorela (life coach — people pleasing, burnout, limite), care:

- E **un singur `SandboxAgent`** cu care vorbește Viorela; cele două faze sunt **skill-uri-foldere**, nu obiecte `Agent` (Revizia 5).
- Primește **profilul întreg în system prompt** la pornirea sesiunii, dintr-un `SELECT` — nu îl caută și nu îl cere ca unealtă.
- Folosește pgvector pentru căutare semantică peste cele 17 cărți, **doar când ea alege sursa „Cărți"**.
- Poate căuta pe internet, **doar când ea alege sursa „Internet"**.
- Citește metoda Brand Legends din `references/`-urile skill-ului Fazei 2, **doar când formatul ales o cere**.
- Ajunge la date doar prin MCP server-ul **`content-data`** — niciodată SQL brut din worker.
- Scrie un rând de audit pentru fiecare acțiune, pe conexiune directă proprie, în afara graniței MCP.

### 1.1 Forma: un agent, două skill-uri

```
Content Worker  ·  SandboxAgent  ·  singurul cu care vorbește Viorela
  system prompt : profil_md întreg + cele 10 reguli obligatorii
  capabilities  : Filesystem, Shell, Compaction + Skills(from_=LocalDir("skills"))
  skills:
    propune-postari    faza 1 — references/: piloni, hook-uri, surse
    dezvolta-postarea  faza 2 — references/: metoda Brand Legends
  tools:
    cauta_in_carti     ← MCP
    listeaza_postari   ← MCP
    save_postare       ← MCP, cu poartă de aprobare
    update_profil      ← MCP, cu poartă de aprobare
```

**De ce skill-uri și nu obiecte `Agent`.** Munca din Faza 1 e *„scrie zece unghiuri diferite în vocea Viorelei, respectând lista de interdicții"* — aia nu e cod, e model. Un skill e exact asta: instrucțiuni pe care le încarcă același model, nu o funcție și nu un al doilea agent. Se editează fără să atingi codul.

**De ce un singur agent și nu doi.** Un context unic. Profilul de 30k caractere și cele 10 reguli intră o dată, nu în promptul fiecărui agent. Iar fluxul se întoarce — ea vede zece propuneri, cere dezvoltarea celei de-a treia, apoi poate cere și a șaptea: lista stă în aceeași conversație, deci a doua cerere nu regenerează nimic.

**De ce nu există un agent de salvare.** `save_postare` e cod, nu model: arată postarea, așteaptă „da", scrie un rând. Iar regula 10 nu depinde de structura de agenți — poarta stă pe **înregistrarea serverului MCP** (§6), deci apără scrierea indiferent cine o cheamă.

**Ce costă forma asta** (Revizia 5, punctul 3): uneltele nu se mai pot atribui pe fază — agentul le are pe toate, tot timpul — iar „exact 10 × exact 5" nu se mai impune din schemă. Ambele devin instrucțiuni în `SKILL.md`, verificate după: `proba_flux.py` acum, setul de evaluare la Decizia 10.

**Testul de verificare la final:** Viorela cere *„vreau ceva despre vinovăția de a spune nu"*. Worker-ul o întreabă formatul, pilonul și sursa; adună materialul din sursa aleasă; scoate zece propuneri cu câte cinci hook-uri; o întreabă pe care o dezvoltă; scrie postarea; i-o arată întreagă; cere aprobare; salvează una singură; și lasă o urmă de audit care poate fi rejucată în SQL — inclusiv cele nouă propuneri refuzate.

---

## 2. Cele două skill-uri

**Revizia 5:** foldere `SKILL.md` cu `references/`, montate în sandbox și descoperite din frontmatter (§1.1). Fiecare skill are corpul lui de instrucțiuni și referințele lui, deschise doar când `SKILL.md` trimite acolo. Declanșarea se face din descriere — deci descrierea contează, și se verifică la evaluare.

**De ce două și nu unul** (Conceptul 5): separarea câștigă peste doi-trei pași. Faza 1 și Faza 2 au material diferit — pilonii și hook-urile pentru prima, metoda Brand Legends pentru a doua. Ținute separat, în context intră doar ce trebuie, iar fiecare se editează singur.

**Se înlănțuie prin conversație, nu prin fișiere.** Cele zece propuneri rămân în contextul agentului; când ea alege, se încarcă `dezvolta-postarea` peste ce e deja acolo. Deci **poate cere dezvoltarea încă unei propuneri din aceeași listă** fără să se regenereze nimic. Cele zece intră și în urma de audit (payload-ul din `audit_log`, §7).

### 2.1 `propune-postari` — Faza 1

**Intrare.** Opțional, tema, așa cum a scris-o ea.

**Cele patru întrebări, toate obligatorii**, pe rând, ca întrebări separate — fără variantă implicită, fără nimic dedus din temă. Excepție unică: dacă a spus deja limpede răspunsul în mesaj („vreau un reel despre…"), ăla e răspunsul ei, se confirmă scurt și se merge mai departe.

1. **Format** — Reel / Carusel / Stories
2. **Pilon** — Poziționare / Educație / Conexiune / Conversie / Magnetism
3. **Sursă** — Cărți / Internet / Memorie / Combinat (vezi 2.4)
4. **Alegerea** — care propunere și cu care hook (după ce vede cele zece)

**Ieșire.** Zece propuneri, fiecare cu:

- **titlu scurt** și **ideea în 1–2 fraze**
- **5 hook-uri, câte unul din fiecare tip**, în ordinea PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE, CONTRAST

Cele zece sunt diferite între ele — unghiuri, dureri și dorințe diferite, nu aceeași idee reformulată.

**Pornește la:** „vreau un reel despre limite", „dă-mi conținut pe Conexiune", „zece propuneri pe Educație", „ceva despre vinovăția de a spune nu", „conținut pentru săptămâna asta".
**NU pornește la:** editarea unei postări existente, o întrebare despre profil, o cerere de raport.

### 2.2 `dezvolta-postarea` — Faza 2

Ia propunerea aleasă și hook-ul ales și scrie: **script** (pe format — Reel: text pe ecran + ce spune în cadru + b-roll; Carusel: slide cu slide; Stories: secvența de 3–7), **caption** (2–4 fraze + întrebare de engagement), **3–5 hashtaguri**, **CTA** din secțiunea 6 a profilului.

Deschide din `references/` doar fișierul cerut de formatul ales — `structura-reel.md` pentru Reel, `stories.md` pentru Stories — nu tot manualul.

**Pornește la:** „dezvoltă a treia, cu hook-ul de contrast", „îmi place 7", „scrie-o pe aia cu vinovăția".

### 2.3 Salvarea — acțiune, nu agent

Nu există un skill de salvare. Salvarea e cod, nu model: agentul arată postarea completă în chat, așteaptă confirmarea ei, apoi cheamă `save_postare(...)` prin MCP — un rând în `postari` plus rândul de audit, în aceeași tranzacție. Dacă ea cere modificări, o rescrie și i-o arată din nou.

Celelalte nouă propuneri **nu** se salvează ca postări; intră în `audit_log` (vezi §7).

Regula 10 („nimic nu se salvează fără confirmarea ei") nu depinde de structura de agenți: poarta de aprobare stă pe **înregistrarea serverului MCP** (§6), deci apără scrierea indiferent cine cheamă unealta.

Distincția din curs: *un agent care întoarce doar text în conversație e o ciornă; ce scrie în sistemul de record e o acțiune.* Doar `save_postare` și `update_profil` sunt acțiuni, și de aia doar ele au poartă.

### 2.4b Metoda Brand Legends — `references/`, nu unealtă

Manualul (`manual-creare-reels.md`, 96 KB) nu intră în context întreg. Stă spart pe subiecte, ca `references/` lângă skill-ul Fazei 2, și se deschide fișier cu fișier, doar când `SKILL.md` trimite acolo:

```
skills/dezvolta-postarea/references/
  filmare.md  editare.md  structura-reel.md  distribuire.md
  hookuri-si-scripturi.md  tipuri-de-reels.md  idei.md
  piloni-si-cont.md  intrebari-frecvente.md
  b-roll.md  stories.md
```

Ăsta e progressive disclosure întreg, nu doar execuția: indexul de skill-uri costă ~100 de tokeni ca să existe, corpul se deschide la potrivire, referința doar dacă e cerută. O unealtă MCP, în schimb, își încarcă schema la fiecare tură, indiferent dacă e folosită — de aia metoda nu e unealtă (Revizia 5, punctul 5).

### 2.4 Cele patru surse de material

Viorela alege una, obligatoriu. `profil.md` nu e în listă pentru că nu e o alegere — intră în system prompt la orice variantă.

| Alegerea ei | De unde | Ce are voie să dea | Ce NU are voie |
|---|---|---|---|
| **📚 Cărți** | `documents` + `embeddings` | idee, cadru, citat — cu titlul, autorul, pagina | să fie prezentată ca „așa se face"; să i se atribuie ce nu scrie în ea |
| **🌐 Internet** | căutare web | unghi, temă de sezon, ce se discută acum | cifre, studii, citate — nimic de pe internet nu intră ca fapt în postare |
| **🧠 Memorie** | profilul + ce știe modelul | structură, formulare, exemple de viață obișnuită | orice cifră, studiu, nume sau afirmație dată ca fapt verificat |
| **🔀 Combinat** | mai multe de mai sus | ce dă fiecare | regulile fiecăreia se cumulează |

Dacă alege **Cărți**, i se propun 3–4 titluri potrivite pe temă și pilon, plus „caută tu în toate" — niciodată lista de 17.

**Materialul se adună ÎNAINTE de a scrie propunerile.** Nu se scrie din memorie ca apoi doar să se adauge referința.

**Sursa se alege, nu se presupune:** dacă a zis „memorie", nu se deschide o carte și nu se caută pe internet, oricât ar părea că cere tema.

### 2.5 Forma ieșirii — instrucțiune, nu schemă

Un `SKILL.md` e text, deci forma se **cere**, nu se impune. `SKILL.md` scrie exact tiparul, ca ea să poată spune „a treia, cu contrastul":

```
3. Titlul scurt
   Ideea, în una-două fraze.
   - PROVOCARE: …
   - CIFRĂ: …
   - SECRET: …
   - ÎNTREBARE: …
   - CONTRAST: …
```

Verificat **după**, nu înainte: `proba_flux.py` numără la fiecare rulare numerotarea 1–10, cele cinci tipuri de hook, cifrele inventate și variantele implicite oferite. Ce e judecată, nu numărătoare, intră în setul de evaluare (Decizia 10).

Ce se scrie în `postari` are, în schimb, formă fixă — dar acolo e cod: `save_postare(...)` cu parametri, nu proză parsată.

**Regulile obligatorii** din `AGENTS.md` (vocea Viorelei, „Lucruri pe care nu le spui niciodată", specific nu generic, română cu diacritice, fără cifre sau testimoniale inventate, sursa rămâne în culise) trec integral în `instructions`-ul agentului — în system prompt, nu într-un skill, fiindcă sunt în vigoare tot timpul. Nu sunt stil, sunt contractul de ieșire.

---

## 3. Schema — cinci tabele de bază + două de domeniu

**Nucleul din Concept 7 (nu se modifică):**
`conversations`, `documents`, `embeddings`, `audit_log`, `capability_invocations`

Plus tabelele Session-ului SDK-ului — `agent_sessions` și `agent_messages` — pe care `SQLAlchemySession` le creează singur pe aceeași bază, legate prin `session_id`. Nu se proiectează și nu se scriu de mână.

**Coloana vertebrală rămâne întreagă** (decis 13 aug 2026). `conversations` și `capability_invocations` sunt marcate *opționale* în carte, iar un tool de tracing acoperă o parte din ce fac — s-a cântărit scoaterea lor și s-a decis să rămână. Patru lucruri pe care tracing-ul **nu** le acoperă, și de aia `audit_log` nu e negociabil:

- trace-ul stă la alt furnizor, deci nu poate fi unit prin JOIN cu `postari` sau `documents` — „arată-mi postările care au folosit un pasaj dintr-un rezumat Bookey" e o interogare imposibilă între două servicii;
- trace-urile expiră, auditul nu;
- `save_postare` scrie postarea **și** rândul de audit în aceeași tranzacție; trace-ul se scrie pe lângă, best-effort — un audit care poate lipsi în timp ce fapta există nu e audit;
- trace-ul vede **apeluri**, nu **decizii**: că din zece propuneri nouă au fost refuzate, și care anume, nu e un apel de unealtă și nu-l înregistrează nimeni dacă nu te hotărăști tu.

**Domeniul, doar ce servește fluxul ăsta:**

| Tabel | Ce ține | Vine din |
|---|---|---|
| `client` | un rând per clientă, o singură coloană de conținut: `profil_md` — profilul întreg, exact ca fișierul de azi (brand, nișă, audiență, avatar, voce, oferte, credințe, dovezi, CTA-uri, „Lucruri pe care nu le spui niciodată") | `profil.md` |
| `postari` | `client_id`, `conversation_id`, dată, pilon, format, titlu, hook ales + tipul lui, script, caption, hashtaguri, cta folosit, sursă, status | `postari/` |

Deci **două tabele de domeniu**, atât. Ies din scop deocamdată: `provocari`, `progres` (se adaugă când reintră `/provocare`), `dovezi` ca tabel separat (stă în `profil_md` până sunt mai mult de câteva), și indexarea postărilor în `embeddings` (vezi mai jos).

**Fără `surse`, `invarianti`, `exceptii`, `cta`** (decis 13 aug 2026). Conținutul lor nu dispare, își schimbă doar locul:

- **Proveniența** — clasa de autoritate, versiunea, `temei_drepturi`, proprietarul, rangul din ierarhie, `are_marcaje_pagina`, `este_rezumat` — trece în `documents.metadata` JSONB, pe fiecare rând. La 17 cărți raportul e aproape 1-la-1, deci un tabel separat ar plăti un JOIN degeaba. Regula de la pasul 5 rămâne neatinsă: metadatele astea călătoresc cu **fiecare chunk returnat**, nu doar cu textul.
- **Invarianții** trec în corpul `SKILL.md`-urilor, iar cei numărabili se verifică în `proba_flux.py`. Tabelul din §3b, Pasul 6 rămâne valabil ca listă de decizii — doar că e scris în skill, nu într-un tabel.
- **Excepțiile** rămân în §5 a planului ăstuia și în corpul skill-urilor, ca comportamente scrise.
- **CTA-urile** stau în `profil_md`, secțiunea 6.

Textul cărților intră în `documents` cu `source='biblioteca'`, cu proveniența în `metadata`. `audit_log` și `capability_invocations` se construiesc **exact** cum le tipărește Concept 7, ca replay-ul de la Decizia 7 să meargă.

Cele două steaguri `are_marcaje_pagina` și `este_rezumat` nu sunt decorative — sunt cazurile urâte 1 și 2 din secțiunea 5.

### Patru decizii de plasare (13 aug 2026)

**`client` are o singură coloană de conținut: `profil_md`.** CTA-urile stau înăuntru, în secțiunea 6, exact ca în fișierul de azi — nu tabel separat, nu coloană separată. Motivul: profilul intră întreg în system prompt la fiecare rulare, deci modelul *vede* secțiunea 6 și marcajele `⚠️` direct în text. Regula 11 (alege CTA-ul potrivit) și regula 6 (semnalează ce lipsește) funcționează fără nicio interogare. O coloană structurată ar servi ceva din afara modelului — un dashboard, un raport — și așa ceva nu e în plan.

**Profilul stă în `client`, nu în `documents` + `embeddings`.** Nu pentru că e mai important, ci pentru că e singurul dintre cele trei feluri de material în care **se scrie**: Viorela îi poate cere agentului să-l modifice în timpul unei sesiuni (varianta A, decisă azi). Un vector nu se face `UPDATE`; și căutarea întoarce ce e mai *asemănător*, nu ce e *corect*, deci un câmp obligatoriu poate lipsi tăcut, fără ca cineva să vadă. În sandbox **nu există niciun `profil.md`**. La pornirea sesiunii se face `SELECT profil_md FROM client WHERE id = ?` și textul intră direct în system prompt, ca șir — nu ca fișier și nu ca unealtă pe care modelul o cheamă dacă vrea. Modificările cerute de Viorela se scriu înapoi prin MCP (`update_profil`), nu prin editarea unui fișier, și lasă `profil_actualizat` în `audit_log`.

**`metoda/` nu intră deloc în bază.** Nimeni nu scrie în ea și încape în context. E **capabilitate, nu date**: călătorește cu skill-ul, nu cu clienta — dacă mâine aplicația ajunge la altă coach, metoda pleacă neschimbată, profilul nu pleacă deloc. Stă ca `references/` tăiate pe subiecte, iar `manual-creare-reels.md` (96 KB, ~28k tokeni) se sparge în structuri / filmare / editare, ca Stage 3 să încarce doar bucata cerută. Nu în `embeddings`: când formatul e Reel știi dinainte că-ți trebuie secțiunea de structuri, iar determinist bate semantic ori de câte ori știi deja ce vrei.

**Postările NU se indexează în `embeddings` deocamdată.** La 26 de postări, „am mai scris despre asta?" se răspunde cu un `WHERE` pe titlu, pilon și dată. Indexarea semantică începe să merite pe la câteva sute — atunci intră în `documents` cu `source='postare'`.

---

## 3b. Unde stă fiecare fișier `.md` — maparea completă

### Pasul 1: sortează sursele în cele patru clase, înainte de orice cod

[Context Layer, Conceptul 2](https://agentfactory.panaversity.org/docs/context-layer-crash-course) spune că **cea mai scumpă greșeală din construcția asta e să tratezi toate sursele ca pe o grămadă nediferențiată.** Clasa decide două lucruri: cum ajunge conținutul înăuntru și ce are voie Worker-ul să facă cu el.

| Clasă | La noi | Cum ajunge | Are voie s-o citeze? |
|---|---|---|---|
| **Metoda partajată** | metoda Brand Legends: manualul de Reels, b-roll, „cum vinzi pe Story" | **`references/` lângă skill**, încărcate la nevoie | da, ca metodă de format |
| **Vertical System of Record** | poziționarea și regulile brandului Viorela: USP, promisiune, misiune-viziune-valori, valori, „Lucruri pe care nu le spui niciodată" — toate **absorbite în `profil.md`** | system prompt, întreg, la fiecare rulare | da, ca **regula care guvernează** |
| **Înregistrări operaționale** | profilul, CTA-urile, postările salvate | **interogare live, niciodată indexate** | da, pentru starea lor, cu dată |
| **Context de lucru** | cele 17 cărți, avatarul clientei (absorbit în profil, secțiunea 2) | indexare | **doar ca dovadă / inspirație, niciodată ca regulă** |

Cele 17 cărți sunt clasa a patra, și asta e decizia de design cea mai importantă din tot planul. Gabor Maté are autoritate asupra a ce a scris Gabor Maté. Nu are nicio autoritate asupra a ce postează Viorela. Un corpus în care cartea și „Lucruri pe care nu le spui niciodată" stau în același tabel, cu aceeași greutate, produce exact ce descrie cartea: răspunsuri fluente, cu citări perfecte, care încalcă regula brandului.

### Pasul 2: testul de plasare — corpus, hartă sau reflex

[Layer 3](https://agentfactory.panaversity.org/docs/ecosystem/fde-af-model#layer-3-vertical-ecosystems):

- trebuie **găsit și citat** → **corpus**;
- trebuie **încărcat și urmat** ca să iasă treaba corect → **skill**;
- ambele → textul integral în corpus, skill-ul spune când și cum.

Peste corpus stau **harta** (skill mic, mereu prezent: ce există și ce nu se încalcă) și **reflexul** (procedura care se încarcă întreagă).

**Testul mai scurt, derivat azi și suficient în practică — două întrebări, în ordine:**

1. **Sistemul scrie în el în timp ce rulează?** Da → tabel de business, ca scrierea să supraviețuiască.
2. Dacă nu: **încape în context?** Da → călătorește cu skill-ul, ca `references/`. Nu → corpus, `documents` + `embeddings`.

### Pasul 3: maparea fișier → clasă → unde ajunge

Structura de azi a lui `content-studio-vio-2`, după restructurarea din 13 aug 2026.

| Fișier azi | Clasă | Unde ajunge | Citabil? |
|---|---|---|---|
| `profil.md` (33 KB — brand, nișă, **avatarul**, voce, oferte, credințe, dovezi, **CTA-uri**, „Lucruri pe care nu le spui niciodată") | operațional + Vertical SoR | `client.profil_md` → **system prompt, întreg, la fiecare rulare** | da, ca regulă care guvernează |
| `carti/md/` (17 cărți, 7,4 MB) | context de lucru | `documents` + `embeddings`, ~4–5.000 de chunk-uri | ca sursă de unghi, la „Sursa" — nu ca regulă |
| `metoda/manual-creare-reels.md` (96 KB) | metoda partajată | **spart în 9**, ca `references/` lângă skill-ul Fazei 2 (§2.4b, Revizia 5) | da, ca metodă |
| `metoda/b-roll-reels.md` (12 KB) | metoda partajată | `skills/dezvolta-postarea/references/b-roll.md` | da, ca metodă |
| `metoda/cum-vinzi-pe-story.md` (17 KB) | metoda partajată | `skills/dezvolta-postarea/references/stories.md` | da, ca metodă |
| `postari/` (26 postări) | operațional | `postari` — interogare live, **fără embeddings deocamdată** | da, pentru starea lor, cu dată |
| `AGENTS.md` § reguli, § piloni, § hook-uri, § surse | Vertical SoR | system prompt (regulile) + corpul și `references/` ale `SKILL.md`-urilor | da, ca regulă |
| `AGENTS.md` § „Adaptarea la platformă", § „Stil de lucru" | — | dispar — sunt despre Claude Code / ChatGPT, nu despre brand | nu |
| `.claude/commands/postare.md` | — | dispare — pașii ei devin corpul celor două `SKILL.md` | — |
| `README.md`, `plans/` | — | nu ajung la agent deloc | — |
| `carti/pdf/`, `carti/txt/`, `metoda/cum-vinzi-pe-story.pdf` | — | arhivă pe disc, doar local | nu |

**Absorbite în `profil.md` la restructurarea din 13 aug, nu mai există ca fișiere:** `usp.md`, `promisiunea-brandului.md`, `misiune-viziune-valori.md`, `valorile-brandului.md`, `avatar-client-perfect.md`. Șterse: `arhiva/`, `comenzi/`, `provocarea-legendara-reels-story.md`. Toate recuperabile din istoricul git și din proiectul original.

Deci **cinci feluri de conținut**, și fiecare depozit aparține unuia singur:

1. **Corpus** — `documents` + `embeddings`
2. **Înregistrări operaționale** — `client`, `postari`
3. **Capabilitate** — `SKILL.md` + `references/`
4. **Stare** — `conversations` (+ `agent_sessions`, `agent_messages`)
5. **Urmă** — `audit_log`, `capability_invocations`

### Pasul 4: proveniența, în `documents.metadata`

Cartea dă câmpurile ([Designing the Vertical SoR → The templates](https://agentfactory.panaversity.org/docs/ecosystem/designing-the-vertical-sor)); noi le punem în JSONB pe fiecare rând din `documents`, nu într-un tabel separat.

| Câmp | La noi |
|---|---|
| `nume` | titlul cărții |
| `editor` | autorul / editura |
| `clasa_autoritate` | *metodologie de expert* / *ghid* / *exemplu* — plus *authority* / *orientation* |
| `domeniu_acoperit` | despre ce e autoritară (ex. „people pleasing", „traumă") |
| `versiune` | ediția |
| `temei_drepturi` | *domeniu public* / *licență deschisă* / *licență comercială* / *permisiune directă* / *plan de înlocuire* |
| `proprietar` | cine răspunde de intrare (Viorela / Sorin) |
| `id_stabil` | slug-ul fișierului |
| `rang` | treapta din ierarhia de mai jos, 1 = câștigă |
| `are_marcaje_pagina` | fals la `cand-corpul-spune-nu.md` |
| `este_rezumat` | adevărat la `set-boundaries-find-peace-rezumat.md` |

**De ce nu tabel separat** (schimbat față de revizia 2): un rând din `surse` ar fi o *lucrare*, un rând din `documents` e *text*, și în principiu sunt lucruri diferite. În practică, la 17 cărți raportul e aproape 1-la-1, iar câmpurile trebuie oricum lipite pe fiecare chunk returnat. Un JOIN care se face de fiecare dată și nu grupează nimic nu-și plătește locul. Se sparge într-un tabel propriu în ziua în care o carte se indexează pe capitole sau apar zeci de lucrări.

**Ierarhia surselor** — se scrie înainte de primul reflex, pentru că sursele se contrazic ([The source hierarchy](https://agentfactory.panaversity.org/docs/ecosystem/designing-the-vertical-sor)). Treapta mai înaltă câștigă doar când ambele surse vorbesc despre aceeași întrebare:

1. profilul Viorelei, inclusiv „Lucruri pe care nu le spui niciodată" și poziționarea absorbită în el
2. metoda Brand Legends (format, structură, filmare)
3. cele 17 cărți — sursă de unghi, nu de regulă
4. internetul — unghi și actualitate, niciodată fapt
5. memoria modelului — structură și formulare, niciodată afirmație

**`temei_drepturi` ne privește direct.** Cele 17 cărți sunt opere protejate. Câmpul trebuie să existe și să spună adevărul pentru fiecare titlu, chiar dacă răspunsul e „uz personal, nedistribuibil". E prima întrebare a unui cumpărător serios și e mai ieftin să ai răspunsul acum decât în ședință. Cele două cărți care nu trec (rezumatul Bookey, cartea fără marcaje de pagină) primesc *plan de înlocuire*, nu se ascund. **⚠️ Neconpletat încă — datorie deschisă.**

### Pasul 5: cele douăsprezece controale care se pierd la chunking

Conceptul 6 din Context Layer: o intrare guvernată cară douăsprezece lucruri cu ea, iar un pipeline generic de indexare păstrează propoziția și pierde toate cele douăsprezece — **și nimic din textul returnat nu anunță lipsa lor**.

Concret la noi: chunk-ul din carte ajunge la model fără să spună că sursa e un rezumat Bookey, fără număr de pagină, fără temei de drepturi și fără clasa ei. Modelul îl citează liniștit ca și cum ar fi cartea.

De aceea `documents.metadata` cară pe fiecare rând, iar `cauta_in_carti` le returnează **în fiecare rezultat**, nu doar textul:

`titlu`, `autor`, `clasa`, `versiune`, `pagina`, `este_rezumat`, `temei_drepturi`, `proprietar`.

Asta e regula 5 din cele opt: **proveniența călătorește cu fiecare element, iar compresia nu o dezbracă niciodată.**

**Chunking-ul, concret:** marcajele `<!-- pagina N -->` din cărți sunt chiar rupturile naturale, și în același timp dau numărul de pagină pentru `metadata`. Câteva sute de cuvinte per chunk, cu puțină suprapunere. Excepție: `cand-corpul-spune-nu.md` nu are marcaje — se taie pe paragrafe și pierde citarea pe pagină (excepția 1).

### Pasul 6: ce impune regulile — nu cuvintele

Definiția de „gata" cere ca regulile cu risc mare să fie impuse de permisiuni de unelte, porți de aprobare sau verificări de politică, **nu doar de cuvinte în prompt**. Nu mai există tabel `invarianti`; lista rămâne, ca decizii scrise în skill-uri și în cod:

| Invariant | Sursă | Impus de |
|---|---|---|
| nimic din „Lucruri pe care nu le spui niciodată" | profil | verificare de politică pe rezultat, înainte de `save_postare` |
| exact 10 propuneri, fiecare cu exact 5 hook-uri, câte unul din fiecare tip | AGENTS.md | corpul skill-ului, numărat după în `proba_flux.py` |
| sursa nu apare în hook / script / caption, doar la „Sursa" | AGENTS.md regula 8 | corpul skill-ului + verificare de politică |
| cifre și testimoniale doar dacă există în profil | AGENTS.md regula 7 | verificare de politică |
| nimic de pe internet nu intră ca fapt | AGENTS.md §surse | verificare de politică |
| română cu diacritice, persoana a II-a | AGENTS.md regula 4 | verificare de politică |
| conținut de Conversie fără oferte în profil | AGENTS.md regula 6 | escaladare (excepția 4) |
| cele patru întrebări se pun toate, nu se presupun | AGENTS.md regula 9 | corpul skill-ului + verificare la intrarea în Faza 2 |
| nimic nu se salvează fără confirmarea ei | AGENTS.md regula 10 | poarta de aprobare pe `save_postare` |

### Pasul 7: cele opt reguli, aplicate la noi

Din [tabelul final al cursului](https://agentfactory.panaversity.org/docs/context-layer-crash-course):

| # | Regula | Ce înseamnă aici |
|---|---|---|
| 1 | autoritatea nu se mută | indexul găsește cartea; citarea trimite la titlu + pagină |
| 2 | relevanța nu e autoritate | un pasaj potrivit din carte nu bate o regulă de brand — și de aia profilul se încarcă, nu se caută |
| 3 | permisiunea se moștenește | un singur utilizator azi — poarta rămâne notată ca datorie |
| 4 | prospețimea se decide pe câmp | cărțile se indexează o dată; profilul se citește live la fiecare pornire |
| 5 | proveniența călătorește cu fiecare element | pasul 5 de mai sus |
| 6 | conflictul se păstrează și se escaladează | excepția 3: tema cerută vs. „nu spui niciodată" |
| 7 | contextul de lucru nu devine tăcut autoritate | o idee dintr-o carte nu devine regulă de brand |
| 8 | descoperirea nu e confirmare | `cauta_in_carti` întoarce indicii; profilul din system prompt e confirmarea |

### Ce e și ce nu e Vertical SoR aici

Distincția pe care o face [System of Context](https://agentfactory.panaversity.org/docs/ecosystem/system-of-context): Vertical SoR **deține profesia** — corpusul, harta, reflexele, invarianții, ierarhia, verificările, evaluările — și e al tău, portabil la orice client din profesia aia. Înregistrarea unui client deține **situația clientului** și nu pleacă nicăieri.

Aplicat pe materialul de azi:

| Material | Cui aparține |
|---|---|
| `profil.md` întreg (brand, avatar, USP, promisiune, misiune, valori, CTA-uri), `postari/` | **înregistrarea Viorelei** — o clientă, un brand; nu se mută la al doilea coach |
| metoda Brand Legends (Reels, Story, b-roll) | metoda altcuiva — o folosim la ea, nu o licențiem |
| cele 17 cărți | opere publicate ale altor autori |
| structura: clasele de surse, ierarhia, invarianții, excepțiile, setul de evaluare | **asta e partea de vertical** — metoda de construcție, nu conținutul |

Deci nu, materialul `.md` nu constituie un Vertical SoR. Constituie **System of Record al unei singure cliente**, care e exact lucrul corect de construit primul.

Legea promovării, dacă apare vreodată al doilea client: un tipar se repetă la trei sau mai mulți clienți, se de-identifică, trece printr-o revizie și **e rescris de expert cu vocea ei**. Asta e autorat, nu copiere. Regula scurtă în timp ce construiești: **lumea clientului intră; nimic nu iese.**

Are o consecință practică pentru ședința cu angajatorul: nu prezenta asta ca „un Vertical SoR pentru coaching". Prezintă-l ca o felie completă pentru o clientă, construită cu disciplina care se mută la orice profesie — și fii pregătit să arăți exact tabelul de mai sus dacă te întreabă. `client_id` există din prima zi tocmai ca răspunsul la „merge și pentru al doilea client?" să fie da, nu „ar trebui să refac".

### System of Context: nu

Pagina [System of Context](https://agentfactory.panaversity.org/docs/ecosystem/system-of-context) pune o poartă care ne scutește de un trimestru: nu se construiește stratul de conectare până când felia nu e terminată și un Worker nu citează din ea. E necesar când răspunsul la *de ce s-a făcut așa* stă în afara oricărui sistem guvernat — douăzeci de ani de dosare, fire de discuție, prezentări.

Aici nu e cazul. Profilul, biblioteca și postările acoperă tot ce cere rezultatul. **Nu construim System of Context.**

---

## 4. MCP server `content-data` — cinci unelte, fără SQL general

Transport: streamable HTTP, varianta stateless, pe `127.0.0.1:8765`. Construit la Decizia 6, într-un singur fișier — `mcp_server/server.py`. Se pornește separat de worker, în alt terminal.

Uneltele de scriere își pun rândul de audit în **aceeași tranzacție** cu scrierea (regula 2). `capability_invocations` și restul urmei rămân pe partea worker-ului, la Decizia 8.

**Citire (rulează liber):**

- `cauta_in_carti(descriere, titluri?, limit)` → căutare semantică peste `documents` unde `source='biblioteca'`; întoarce pasajul **plus toată proveniența din `metadata`** (titlu, autor, pagină, `are_marcaje_pagina`, `este_rezumat`, `temei_drepturi`, clasă). Filtrarea pe `titluri` servește cazul „a ales trei cărți din cele patru propuse".
- `cauta_pe_internet(descriere, limit)` → Responses API cu unealta OpenAI `web_search`; întoarce numai unghiuri de inspirație și linkurile citate. Cifrele, studiile și citatele găsite nu devin fapte în postare.
- `listeaza_postari(pilon?, format?, de_la?, limit)` → postările deja făcute, pentru „am mai scris despre asta?" și pentru rapoarte simple.
**Scriere (poartă de aprobare):**

- `save_postare(...)` → inserează **o** postare, cea confirmată, **și** rândul de audit, într-o singură tranzacție.
- `update_profil(sectiune, text_nou)` → scrie în `client.profil_md` și lasă `profil_actualizat` în `audit_log`. Există pentru că varianta A e decisă: Viorela poate cere modificări în profil din conversație.

**Ce NU mai există față de revizia 2:**

- `get_brand_profile()` — profilul intră în system prompt la pornire, nu se cere ca unealtă. O unealtă pe care modelul o cheamă *dacă vrea* e o unealtă pe care poate să n-o cheme.
- `list_cta()` — CTA-urile sunt în `profil_md`, deci deja în context.
- `get_metoda(format)` — propus la Revizia 4, anulat de Revizia 5. Metoda stă ca `references/` lângă skill (§2.4b), deci nu mai are nevoie de unealtă.

**Ce NU există deloc:** nicio unealtă de tip `run_sql`, niciun DDL, niciun parametru de text liber din care se construiește SQL.

**Căutarea pe internet trece prin același MCP**, ca agentul să aibă un singur contract de capabilități și audit. În interior, serverul folosește Responses API cu `web_search`; nu scrie nimic în baza de date.

**Neon, două capcane:** endpoint-ul pooled sparge prepared statements în asyncpg, deci `statement_cache_size=0` pe pool-ul serverului și pe cel de audit; pgvector se înregistrează pe conexiune, altfel vectorii se scriu aiurea. Iar pentru Session: extra-ul `[sqlalchemy]` **nu** trage `greenlet`, și URL-ul trebuie în forma `postgresql+asyncpg://`, nu `postgresql://`.

---

## 5. Excepțiile — se proiectează ÎNAINTE de drumul normal

Partea care lipsește azi din `content-studio-vio-2`. Fiecare caz primește un comportament scris, nu o improvizație a modelului.

| # | Cazul urât | Comportament decis |
|---|---|---|
| 1 | Pasajul vine din `cand-corpul-spune-nu.md`, fără marcaje `<!-- pagina N -->` | `are_marcaje_pagina=false`; postarea se generează, la „Sursa" se scrie titlul fără pagină și motivul. Nu se inventează un număr de pagină. |
| 2 | Pasajul vine din `set-boundaries-find-peace-rezumat.md`, rezumat Bookey | `este_rezumat=true`; la „Sursa" scrie explicit „rezumat Bookey". Dacă se cere un citat propriu-zis, se refuză și se propune altă sursă. |
| 3 | Tema cerută intră în conflict cu „Lucruri pe care nu le spui niciodată" | Nu se generează propunerile afectate. Se spune care e conflictul și se cere decizia omului. |
| 4 | Pilonul Conversie, dar secțiunea Oferte din profil are ⚠️ | Se semnalează scurt și se generează ce se poate (regula 6), cu `capability_invocations` marcat parțial. |
| 5 | Se cere un testimonial sau o cifră care nu există în profil | Se refuză, se propune înlocuitor. Regula 7: nu se inventează niciodată rezultate. |
| 6 | Căutarea semantică întoarce doar potriviri slabe | „nu există precedent puternic" — se spune, nu se maschează; propunerile se fac din profil, nu din bibliotecă. **Pragul din revizia asta era greșit:** scria „distanță > ~0.3", adică asemănare sub 0,7, ceea ce ar respinge tot. Măsurat la Decizia 6, pe întrebarea din §7, potrivirile bune stau la 0,45–0,55. Pragul scris azi în `references/surse.md` e 0,35, și se recalibrează la Decizia 10, cu setul de evaluare. |
| 7 | CTA-ul potrivit e încă `⚠️ DE COMPLETAT` în profil | Se propune unul, se spune că e propus, și se cere să fie trecut în profil ca să rămână. Postarea nu se salvează fără CTA. |
| 8 | Modelul întoarce nouă propuneri, sau una cu patru hook-uri, sau două de același tip | Nu se mai poate impune din schemă (Revizia 5). `SKILL.md` cere forma, `proba_flux.py` o numără după, iar cazul intră în setul de evaluare. |
| 9 | Mesaj dictat, fără diacritice, cu greșeli de transcriere | Se interpretează cu bunăvoință, fără a corecta utilizatoarea; răspunsul are diacritice. |
| 10 | A ales sursa „Internet", dar apelul web nu este disponibil temporar | Se spune pe loc și se întreabă dacă mergem pe cărți sau pe memorie. **Nu** se înlocuiește tăcut cu ce știe modelul (regula 9). |
| 11 | Căutarea pe internet întoarce cifre, studii sau citate | Intră doar ca unghi. Nicio cifră și niciun citat de pe internet nu ajunge în postare. Linkul, doar la „Sursa". |
| 12 | Ea sare peste o întrebare sau răspunde ambiguu la format / pilon / sursă | Se reîntreabă. Nu se alege în locul ei, nu se pornește „pe o variantă până răspunde". |

**Setul de evaluare.** Fiecare rând devine un caz de test cu răspunsul corect scris lângă el, în `evals/`. Cu trigger evals (Revizia 5 — skill-ul pornește din descriere, deci descrierea se testează), plus evals pe deciziile agentului: că nu scoate propuneri fără toate cele patru răspunsuri, că nu cheamă `save_postare` fără confirmare, și că poate dezvolta a doua propunere din aceeași listă fără să regenereze. Ăsta e artefactul care face diferența între o felie terminată și o demonstrație — și e singurul lucru din tot planul pe care un angajator nu îl vede în alte portofolii.

---

## 6. Poarta de aprobare

În exemplul lucrat, acțiunea gardată e cea care mișcă bani. Aici, echivalentul e acțiunea care iese sub numele Viorelei: **`save_postare`**, plus **`update_profil`**. Citirile rămân libere.

Poarta stă pe **înregistrarea serverului**, nu în interiorul uneltei. Se construiește ultima, după ce Worker-ul merge cap-coadă — o poartă adăugată înainte nu se poate testa: nu poți deosebi una care funcționează de una stricată dacă nu curge nimic prin ea.

Se probează în ambele sensuri: aprobat → postarea apare în `postari`, auditul scrie `postare_salvata`; respins → niciun rând scris, auditul arată refuzul.

Peste poartă stă regula 10 din `AGENTS.md`, care e mai strictă: postarea se arată **întreagă în chat** și se așteaptă „da"-ul ei înainte ca uneltele de scriere să fie chemate măcar.

---

## 7. Ordinea de construcție

| # | Decizia | Se termină când |
|---|---|---|
| 0 | Agent minimal de chat (uv, Agents SDK, `Agent` simplu) | răspunde la „hi" |
| 1 | `AGENTS.md` nou, cu cele trei reguli de arhitectură | regulile apar în diff |
| 2 | Planul schemei și al fluxului, în Plan Mode | acest document, aprobat |
| 3 | Neon + pgvector + schema pe branch, apoi `SQLAlchemySession` | tabelele există; worker-ul își amintește două ture, și le vezi în `agent_messages` |
| 4 | `propune-postari` ca skill în sandbox (Revizia 5) | la „vreau ceva despre limite" pune cele trei întrebări pe rând, apoi scoate 10 propuneri × 5 hook-uri și respectă sursa aleasă |
| 5 | Import + embedding: cele 17 cărți; `metoda/` spartă în `references/` lângă skill-ul Fazei 2 (Revizia 5) | o căutare după „vinovăția de a spune nu" întoarce pasaje ordonate, cu pagină |
| 6 | MCP server `content-data`, cinci unelte (`cauta_in_carti`, `cauta_pe_internet`, `listeaza_postari`, `save_postare`, `update_profil`) | ✅ căutările în cărți și pe internet sunt probate cu proveniență |
| 7 | `dezvolta-postarea` ca al doilea skill + salvarea | un ciclu complet: 10 propuneri → una aleasă → dezvoltată → arătată → salvată; apoi **încă una din aceeași listă**, fără regenerare |
| 8 | Audit la fiecare graniță + verificare cap-coadă + replay | poți reconstrui ce a făcut, fără să rulezi modelul |
| 9 | Poarta de aprobare pe `save_postare` și `update_profil` | aprobat trece, respins nu scrie nimic |
| 10 | Setul de evaluare din secțiunea 5, rulat | toate cele douăsprezece cazuri au răspunsul decis, nu improvizat |

**Vocabularul închis al lui `audit_log.action`** — e un `CHECK`, deci lista asta e o decizie de design, nu o formalitate: ce nu e în ea nu se poate scrie, iar adăugarea ulterioară e migrare. **⚠️ De confirmat:**

`message_received`, `skill_activated`, `capability_invoked`, `propuneri_generate`, `postare_salvata`, `profil_actualizat`, `guardrail_tripped`, `corpus_seeded`, `message_sent`.

**`propuneri_generate` e cel care merită atenție.** Payload-ul lui ține toate cele zece propuneri cu hook-urile lor, plus care a fost aleasă. Asta înseamnă că **cele nouă refuzate se păstrează** — și ele sunt cel mai bun semnal despre gustul Viorelei din tot sistemul. Azi se pierd la fiecare rulare.

**Auditul**, pe conexiune separată: `message_received` (aici se scrie și rândul din `conversations`, înainte ca vreun audit să-l refere), `skill_activated` (prin `on_tool_start`/`on_tool_end` unde `tool.name == "load_skill"` — nu există hook de skill), `capability_invoked` după fiecare apel MCP, `guardrail_tripped` prins din `try/except` în jurul `Runner.run`, `postare_salvata` scris de MCP server în tranzacție, `message_sent`. Corpul fiecărui hook stă în `try/except`: o eroare de audit nu are voie să omoare tura Viorelei.

Pasul 5 e singurul cu volum real de date: 17 cărți întregi, ~4–5.000 de chunk-uri. Se face ca script de seed rulat de mână, pe conexiune directă — nu prin MCP. Granița MCP e pentru ce face agentul singur; seed-ul e ceva ce faci tu.

---

## 8. Ce NU acoperă planul ăsta

- Un agent și două skill-uri, atât. `/provocare`, `/trend` rămân în afara scopului.
- **Un singur client.** Multi-tenant, auth, upload self-service, onboarding din Instagram — amânate (Revizia 4).
- **Sandbox E2B** (Revizia 5), montând doar `skills/`. Nimic altceva din proiect nu ajunge acolo: `.env` are parola bazei, iar agentul are shell.
- **Profilul se editează din Worker** (varianta A), dar numai prin `update_profil`, cu poartă. Nu există editare liberă de fișiere.
- Nu e always-on și nu e proactiv. Rulează când e chemat.
- Aprobarea e sincronă: dacă răspunsul vine peste o oră, din alt proces, e nevoie de `run_states` (Decizia 10 opțională din curs). Cazul concret care ar declanșa asta: Viorela confirmă postarea de pe telefon a doua zi.
- Postările nu se indexează semantic până nu sunt câteva sute.
- Interfața pentru Viorela rămâne de decis la deployment; până atunci, terminal.
- Design-ul de carusel în Canva, care apare în platforma Brand Legends, nu intră aici.

---

## 9. Ce trebuie aprobat înainte de cod

1. Folder nou `content-studio-fte`, cu `content-studio-vio-2` rămas funcțional.
2. `gpt-5-mini` pentru generare, `text-embedding-3-small` pentru căutare.
3. **Un singur client, Viorela** — fără multi-tenant, fără RLS, fără auth (Revizia 4). `documents.client_id` există ca o coloană, ca migrarea viitoare să fie de date, nu de schemă.
4. **`SandboxAgent` pe E2B**, cu cele două faze ca skill-uri-foldere montate din `skills/` (Revizia 5, §1.1). Forma cerută — 10 propuneri × 5 hook-uri — e instrucțiune în `SKILL.md`, numărată după, nu impusă din schemă.
5. **Două** tabele de domeniu: `client` (cu `profil_md` ca unică coloană de conținut) și `postari`.
6. **Patru** unelte MCP — `cauta_in_carti`, `listeaza_postari`, `save_postare`, `update_profil` — cu `run_sql` exclus.
7. Poarta de aprobare pe `save_postare` și `update_profil`.
8. Cele douăsprezece cazuri urâte din secțiunea 5, cu comportamentele decise acolo.
9. Vocabularul închis al lui `audit_log.action` din §7.
10. `temei_drepturi` completat pentru fiecare din cele 17 cărți — mizele sunt mici cu o singură clientă și repo privat, dar câmpul tot trebuie să spună adevărul. **Încă necompletat.**
