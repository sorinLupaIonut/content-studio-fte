# Content Studio FTE — Content Worker pentru Viorela

Versiunea Python a laboratorului de conținut, construită ca **Digital FTE** după
[Building a Digital FTE](https://agentfactory.panaversity.org/docs/digital-fte-crash-course), Partea 4.

Fișierul ăsta e **specificația domeniului și contractul de arhitectură**. Planul complet, cu
motivele fiecărei decizii, e în [plans/digital-fte-plan.md](plans/digital-fte-plan.md).
Predecesorul, `content-studio-vio-2`, rămâne funcțional pentru Viorela până când ăsta îl înlocuiește.

**Pentru cine.** Viorela — life coach pentru femei care vor să iasă din people pleasing, burnout
și autosabotaj. Nu e programatoare: răspunsurile către ea sunt în română, simple, fără termeni tehnici.

---

## Reguli de arhitectură

Cele șase reguli pe care o sesiune nouă trebuie să le respecte fără să le mai întrebe.
Primele trei sunt regulile Deciziei 1 din curs; ultimele trei s-au stabilit la Decizia 4.

1. **Datele de business se citesc și se scriu doar prin serverul MCP `content-data`** — niciodată
   SQL brut din worker-ul care rulează. Nu există unealtă `run_sql`, nici DDL, nici parametru de
   text liber din care se construiește SQL.
2. **Auditul are conexiune directă proprie la bază**, în afara graniței MCP, iar fiecare acțiune
   și rândul ei de audit se comit **împreună**, în aceeași tranzacție.
3. **Embedding-urile folosesc același model la stocare și la căutare** — `text-embedding-3-small`.
   Modele diferite la cei doi capeți înseamnă căutare care întoarce gunoi.
4. **Sandbox cu skill-uri-foldere.** `SandboxAgent`, nu `Agent` simplu. Metoda stă în
   `skills/<nume>/SKILL.md` plus `references/`, montate în sandbox și deschise progresiv:
   indexul (nume + descriere + cale) e mereu în context, corpul se deschide când sarcina se
   potrivește descrierii, iar `references/` doar dacă `SKILL.md` trimite acolo. Se editează
   fără să atingi codul. Sandbox-ul e E2B.
5. **Un singur agent.** Cele două faze sunt skill-uri, nu agenți separați. Un context unic,
   deci profilul de 30k caractere și regulile nu se copiază de două ori.
   Costul, asumat cu ochii deschiși: un `SKILL.md` e text, nu schemă. Nu poate impune „exact
   zece propuneri cu exact cinci hook-uri" — se cere, se numără după, și se judecă la evaluare.
6. **Nimic nu se salvează fără confirmarea Viorelei.** Poarta de aprobare stă pe înregistrarea
   serverului MCP, deci apără scrierea indiferent cine cheamă unealta.

## Forma

```
Content Worker  ·  SandboxAgent  ·  singurul cu care vorbește Viorela
  bootstrap     : profil_md citit live prin resursa MCP internă `content-data://…/profil`
  system prompt : profil_md întreg + cele 10 reguli obligatorii
  capabilities  : Filesystem, Shell, Compaction (implicite) + Skills(from_=LocalDir("skills"))
  skills:
    propune-postari    faza 1 — cele 3 întrebări, apoi 10 propuneri × 5 hook-uri
                         references/: piloni.md, hookuri.md, surse.md, carti.md
    dezvolta-postarea  faza 2 — script, caption, hashtaguri, CTA          (Decizia 7)
                         references/: metoda Brand Legends, 11 fișiere
  tools:
    cauta_in_carti     ← MCP
    cauta_pe_internet  ← MCP
    listeaza_postari   ← MCP
    save_postare       ← MCP, cu poartă de aprobare
    update_profil      ← MCP, cu poartă de aprobare
```

Cu un singur agent, uneltele nu se mai pot atribui pe fază: le are pe toate, tot timpul.
Limita — `cauta_in_carti` doar la sursa Cărți — e scrisă în `SKILL.md`, deci e o
instrucțiune, nu un zid. E o pierdere reală, și se prinde la evaluare.

---

## Fluxul: două faze, patru întrebări

**Prima fază produce 10 propuneri; a doua dezvoltă doar ce alege ea.** Nu se sare peste alegere
și nu se dezvoltă toate cele 10.

**Cele patru întrebări sunt OBLIGATORII** — formatul, pilonul, sursa și alegerea propunerii.
Se pun toate, pe rând, ca întrebări separate, și se așteaptă răspunsul la fiecare. Niciuna nu are
variantă implicită, niciuna nu se deduce din temă, niciuna nu se sare pentru că „e evident din
context". Singura excepție: dacă ea a spus deja limpede răspunsul în mesaj („vreau un reel
despre…"), ăla **e** răspunsul ei — se confirmă scurt și se trece mai departe.

### Faza 1 — cele 10 propuneri (skill `propune-postari`)

1. **Profilul e deja în system prompt**, întreg, la orice variantă de sursă. Nu se caută și nu se
   cere ca unealtă.
2. **Formatul** (obligatoriu): Reel, Carusel sau Stories.
3. **Pilonul** (obligatoriu), din cei 5 de mai jos.
4. **Sursa materialului** (obligatoriu), una din cele 4 de mai jos. Dacă alege **Cărți**, i se
   propun 3–4 titluri potrivite pe temă și pilon plus „caută tu în toate" — niciodată lista de 17.
   Dacă alege **Combinat**, se întreabă pe care le combină.
5. **Materialul se adună ÎNAINTE de a scrie propunerile.** Nu se scrie din memorie ca apoi doar
   să se adauge referința.
6. **Zece propuneri**, toate pe formatul, pilonul și sursa alese. Fiecare are:
   - **titlu scurt** și **ideea în 1–2 fraze**;
   - **5 hook-uri, câte unul din fiecare tip**, în ordinea PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE,
     CONTRAST — fiecare max. 1–2 fraze, apăsând pe o durere sau o dorință reală din secțiunea 2
     a profilului, în vocea ei.

   Cele 10 sunt **diferite între ele** — unghiuri, dureri și dorințe diferite, nu aceeași idee
   reformulată. Numerotate 1–10.
7. **Care se dezvoltă și cu care hook** (obligatoriu). Poate alege mai multe. Nu se alege în locul ei.

### Faza 2 — dezvoltarea celei alese (skill `dezvolta-postarea`)

8. **SCRIPT / STRUCTURĂ**, pe formatul ales:
   - *Reel:* hook pe ecran → punctele scriptului (text pe ecran + ce spune/face în cadru +
     sugestie de b-roll) → încheiere cu CTA. Se precizează dacă e reel vorbit, text pe ecran cu
     b-roll, sau POV.
   - *Carusel:* slide cu slide. Slide 1 = hook vizual, o idee per slide, ultimul = CTA.
   - *Stories:* secvența de 3–7 story-uri, cu sticker de interacțiune unde are sens.
9. **CAPTION:** 2–4 fraze scurte, conversaționale, în vocea ei, cu o întrebare de engagement la final.
10. **HASHTAGURI:** 3–5, relevante pentru nișă, variate.
11. **CTA:** cel potrivit din secțiunea 6 a profilului. Dacă la categoria potrivită e încă
    `⚠️ DE COMPLETAT`, se propune unul, se spune că e propus, și se cere să fie trecut în profil.
12. **Postarea completă se arată în chat și se așteaptă confirmarea.** Nimic nu se salvează
    înainte. Dacă cere modificări, se refac și i se arată din nou.
13. **Se salvează una singură**, cea confirmată, prin `save_postare`. Celelalte nouă propuneri
    rămân în `audit_log` (`propuneri_generate`), nu în tabelul `postari`.

### Forma ieșirii: instrucțiune, nu schemă

Un `SKILL.md` e text, deci „exact 10 propuneri, exact 5 hook-uri, câte unul din fiecare tip"
e ceva ce modelul respectă de obicei, nu un contract care oprește răspunsul greșit.

Forma cerută în `SKILL.md`, ca ea să poată spune „a treia, cu contrastul":

```
3. Titlul scurt
   Ideea, în una-două fraze.
   - PROVOCARE: …
   - CIFRĂ: …
   - SECRET: …
   - ÎNTREBARE: …
   - CONTRAST: …
```

Se numără **după**: `proba_flux.py` verifică la fiecare rulare numerotarea 1–10, cele cinci
tipuri, cifrele inventate și variantele implicite oferite. Judecata pe cazurile grele e
treaba setului de evaluare, Decizia 10.

---

## Cei 5 piloni de conținut

1. **Poziționare** 🎯 — cine ești, ce faci diferit, de ce contează pentru clienta ideală
2. **Educație** 📚 — înveți audiența ceva concret, aplicabil, legat de problema pe care o rezolvi
3. **Conexiune** 🤝 — povești personale, vulnerabilitate, behind-the-scenes, valori comune
4. **Conversie** 💰 — transformări, oferte, rezultate, call-to-action direct
5. **Magnetism** ✨ — personalitate, lifestyle, ritualuri, lucruri care atrag și fidelizează

## Cele 5 tipuri de hook-uri

Fiecare propunere primește **exact 5 hook-uri: câte unul din fiecare tip, niciunul repetat.**
Nu patru, nu șase, și nu două de același fel.

- **PROVOCARE** — provoacă direct („3 greșeli care țin pe loc 90% din… Faci cel puțin una?")
- **CIFRĂ** — număr concret + consecință
- **SECRET** — dezvăluie ce nu spune nimeni
- **ÎNTREBARE** — întrebare incomodă sau curioasă
- **CONTRAST** — înainte vs. după

## Cele 4 surse de material

Viorela alege una, obligatoriu. Profilul nu e în listă pentru că nu e o alegere — intră întreg
în system prompt la orice variantă.

| Alegerea ei | De unde | Ce are voie să dea | Ce NU are voie |
|---|---|---|---|
| **📚 Cărți** | `documents` + `embeddings`, prin `cauta_in_carti` | idee, cadru, citat — cu titlul, autorul, pagina | să fie prezentată ca „așa se face"; să i se atribuie ce nu scrie în ea |
| **🌐 Internet** | `cauta_pe_internet`, prin Responses API | unghi, temă de sezon, ce se discută acum | cifre, studii, citate — nimic de pe internet nu intră ca fapt |
| **🧠 Memorie** | profilul + ce știe modelul | structură, formulare, exemple de viață obișnuită | orice cifră, studiu, nume sau afirmație dată ca fapt verificat |
| **🔀 Combinat** | mai multe de mai sus | ce dă fiecare | regulile fiecăreia se cumulează, nu se anulează |

**Ierarhia surselor, când se contrazic** — treapta mai înaltă câștigă, dar numai când ambele
vorbesc despre aceeași întrebare:

1. profilul Viorelei, inclusiv „Lucruri pe care nu le spui niciodată"
2. metoda Brand Legends (format, structură, filmare)
3. cele 17 cărți — sursă de unghi, niciodată de regulă
4. internetul — unghi și actualitate, niciodată fapt
5. memoria modelului — structură și formulare, niciodată afirmație

**Sursa se notează obligatoriu** pe postarea salvată, oricare ar fi alegerea:

- carte → `„Titlu" — Autor, capitolul N / pagina N`
- internet → `internet — ce ai citit + linkul`
- memorie → `din memorie 🧠 (profil + avatar), fără sursă externă`
- combinat → toate cele folosite

---

## Reguli de generare — OBLIGATORII

Nu sunt stil. Sunt contractul de ieșire, și trec integral în `instructions`-ul agentului —
în system prompt, nu într-un skill, fiindcă sunt în vigoare tot timpul.

1. **Vocea Viorelei, nu vocea unui robot.** Tonul și expresiile din „Vocea ta", „Expresii pe care
   le folosești des" și „Tonul tău". Cald, blând, empatic, vulnerabil dar ferm, cu perspectivă
   creștină autentică. FĂRĂ empowerment agresiv, FĂRĂ jargon de marketing, FĂRĂ fraze generice de
   AI („în lumea agitată de azi", „haide să descoperim").
2. **Respectă „Lucruri pe care nu le spui niciodată"** din profil — cuvinte și abordări interzise.
3. **Specific, nu generic.** Durerile, dorințele, fricile și credințele limitative REALE din
   secțiunea 2 a profilului. O postare bună pentru oricine e o postare bună pentru nimeni.
4. **Română cu diacritice**, persoana a II-a singular, către „Andreea" (avatarul), femeie 25–45 ani.
5. **Fiecare postare completă include:** hook ales, script, caption, 3–5 hashtaguri, CTA din profil.
6. **Dacă profilul are ⚠️ în ceva de care depinde sarcina**, se semnalează scurt și se generează
   totuși ce se poate.
7. **Testimonialele și cifrele** se folosesc DOAR dacă există în profil — nu se inventează niciodată
   rezultate, cifre sau dovezi. O cifră dintr-o carte cere pagina. O cifră de pe internet nu intră deloc.
8. **Sursa de inspirație rămâne în culise.** Cartea, autorul, pagina sau linkul se notează DOAR pe
   câmpul `sursa` al postării salvate — NU în hook, în script sau în caption. E conținut de social
   media, nu lucrare cu bibliografie. Excepții: citat prezentat ca citat, sau ea cere explicit.
9. **Întrebările se pun, răspunsurile nu se presupun.** Toate cele patru sunt obligatorii. Fără
   răspunsul ei nu se trece mai departe. Iar după ce a ales sursa, nu se aduce material din alta —
   dacă a zis „memorie", nu se deschide o carte și nu se caută pe internet.
10. **Nimic nu se salvează fără confirmarea ei.** Postarea se arată întâi întreagă în chat. Abia
    după „da"-ul ei se cheamă uneltele de scriere. La fel pentru modificările din profil.

---

## Unde stă fiecare lucru

| Ce | Unde ajunge | Clasă |
|---|---|---|
| profilul Viorelei | `client.profil_md` → **system prompt, întreg, la fiecare rulare** | Vertical SoR + operațional |
| cele 17 cărți | `documents` + `embeddings`, prin `cauta_in_carti` | context de lucru — inspirație, niciodată regulă |
| metoda Brand Legends | `skills/dezvolta-postarea/references/`, deschise la nevoie | metodă partajată |
| postările salvate | tabelul `postari` — interogare live, fără embeddings deocamdată | operațional |
| starea conversației | `conversations` + `agent_sessions` / `agent_messages` | stare |
| urma acțiunilor | `audit_log`, `capability_invocations` | urmă |

**Proveniența călătorește cu fiecare pasaj returnat**, nu doar cu textul: `titlu`, `autor`,
`clasa`, `versiune`, `pagina`, `este_rezumat`, `temei_drepturi`, `proprietar`. Un chunk care ajunge
la model fără ele e citat liniștit ca și cum ar fi cartea integrală.

Materialul brut, până când intră în bază:

```
content/profil.md               → client.profil_md            (Decizia 3)
content/carti/md/               → documents + embeddings      (Decizia 5)
content/postari/                → tabelul postari             (Decizia 3)
```

Metoda Brand Legends **nu** trece prin bază. E capabilitate, nu date: stă spartă pe subiecte
în `skills/dezvolta-postarea/references/` și se deschide când `SKILL.md` trimite acolo.

## Ordinea de construcție

Deciziile 0–10 din [§7 al planului](plans/digital-fte-plan.md). Fiecare Decizie adaugă o piesă și
se rulează worker-ul din nou, ca piesa nouă să se vadă funcționând înainte de următoarea.
Starea de azi e în [README.md](README.md).
