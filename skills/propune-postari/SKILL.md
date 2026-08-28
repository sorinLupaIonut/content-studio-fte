---
name: propune-postari
description: 'Faza 1 a producției de conținut — zece propuneri de postare, unghiuri diferite pe aceeași temă, din care Viorela alege una singură. Îl folosești OBLIGATORIU ori de câte ori EA cere conținut nou. Cererea vine fie ca formular, cu formatul, pilonul, sursa și focusul deja alese, fie în conversație — atunci întrebi ce lipsește și pornești generarea cu unealta aplicației, nu scrii tu lista. NU-l porni din proprie inițiativă: dacă mesajul ei se referă la o propunere dintr-o listă care nu există în conversație, spui că nu ai lista și aștepți să o ceară — nu o generezi tu în locul ei. NU-l folosi pentru editarea unei postări existente, pentru o întrebare despre profil, sau pentru o cerere de raport.'
---

# Faza 1 — cele zece propuneri

Zece unghiuri diferite pe tema ei, din care alege unul singur pe care să-l
dezvoltăm în Faza 2. Aici nu se scrie nicio postare întreagă.

## Pasul 1 — ce ai deja, și ce faci cu asta

Alegerile fazei sunt patru, oricum ar veni cererea:

- **Formatul** — Reel, Carusel sau Stories
- **Pilonul** — unul din cele cinci
- **Sursa** — de unde ai voie să iei materialul
- **Focusul** — tema, când e dată

Când cererea vine din aplicație, ca formular, sunt deja făcute: **nu le pui la
îndoială și nu ceri confirmare pentru ele** — le-a ales apăsând pe ele. Când
cererea vine în conversație, întrebi doar ce lipsește, pe rând, cu vocabularul
pașilor de mai jos — și nimic în plus.

## Pasul 2 — Formatul

Reel, Carusel sau Stories. În faza asta formatul nu-ți dă metoda de scriere —
aia e în Faza 2 — dar decide **ce fel de idee are sens**: un Reel ține un singur
gând, un Carusel suportă o idee desfășurată în pași, Stories cere ceva la care se
poate răspunde pe loc. Zece idei care ignoră formatul sunt zece idei care nu sunt bune
la dezvoltare.

Dacă formatul lipsește, îl ceri. Nu alegi tu.

## Pasul 3 — Pilonul

Unul din cele cinci de mai jos. Vocabular închis: nu inventa al șaselea, nu-l
redenumi pe niciunul, și nu ghici din nume ce fel de conținut cere — scrie aici.
Nu-i oferi ei o listă de piloni: alegerea e deja făcută.

- **🎯 Poziționare** — cine e Viorela, ce face diferit, de ce contează pentru
  clienta ideală. Postări care așază: ce crede, cum lucrează, pentru cine e și
  pentru cine nu e.
- **📚 Educație** — înveți audiența ceva concret, aplicabil, legat de problema
  pe care o rezolvă ea. Un lucru pe postare, nu cinci. Aplicabil azi, nu „în
  general".
- **🤝 Conexiune** — povești personale, vulnerabilitate, din culise, valori
  comune. Aici intră ce a trăit ea însăși — momentul, nu concluzia despre
  moment.
- **💰 Conversie** — transformări, oferte, rezultate, îndemn direct. Depinde de
  secțiunea de oferte din profil; dacă are ⚠️, propui un CTA, nu inventezi o
  ofertă.
- **✨ Magnetism** — personalitate, stil de viață, ritualuri, lucruri care atrag
  și fidelizează. Nu vinde și nu învață — face să vrei să rămâi.

Cele 26 de postări existente acoperă doar trei dintre ei: Conexiune, Educație și
Magnetism. Poziționare și Conversie n-au precedent scris — nu înseamnă că sunt
interzise, înseamnă că n-ai model din care să te inspiri.

Dacă pilonul lipsește, îl ceri cu vocabularul închis de mai sus, toate cele
cinci variante, fără redenumiri și fără variante inventate.

## Pasul 4 — Sursa, și materialul care vine din ea

De aici iei materialul, și numai de aici. Din sursa aleasă de **ea**, niciodată
din alta, și **înainte** de a scrie orice. Nu scrii din memorie ca apoi doar să
adaugi referința.

| Alegerea ei | De unde | Ce are voie să dea | Ce NU are voie |
|---|---|---|---|
| 📚 Cărți | biblioteca ei de 17 titluri, prin `search_books` | idee, cadru, citat, cu titlul și autorul | să fie prezentată ca „așa se face"; să i se atribuie ce nu scrie în ea |
| 🌐 Internet | căutare web | unghi, temă de sezon, cifră, studiu, citat — fiecare cu pagina lui | ceva ce nu apare în paginile consultate; diagnostic sau promisiune de vindecare |
| 🧠 Memorie | profilul plus ce știi tu | structură, formulare, exemple de viață obișnuită | orice cifră, studiu, nume sau afirmație dată ca fapt verificat |
| 🔀 Combinat | mai multe de mai sus | ce dă fiecare | regulile fiecăreia se cumulează, nu se anulează |

Profilul nu e în listă pentru că nu e o alegere — îl ai deja întreg, la orice
variantă. La Combinat le folosești numai pe cele alese explicit de ea. Nu
înlocui și nu adăuga tăcut altă sursă.

Dacă sursa lipsește, o ceri cu variantele din tabel. După ce a ales-o, nu mai
aduci material din alta.

### Cum cauți pe internet

`search_web(description, limit)`. O chemi numai după ce ea a ales Internet sau
Combinat cu Internet și înainte să scrii propunerile. În `description` pui tema
dată de ea; n-o mai întrebi a doua oară.

Din rezultat iei tot ce servește tema: unghiuri și teme de sezon, dar și
cifre, studii și citate — cu o singură condiție, care nu se negociază: **să
apară chiar în paginile consultate, nu în memoria ta.** Un fapt luat de pe web
intră în postare cu proveniența lui: pagina care l-a dat ajunge pe câmpul
`source`, iar un citat se prezintă ca citat.

Ce rămâne interzis nu ține de web, ci de profil: nu inventezi fapte care nu
apar în rezultat, nu dai diagnostice ori promisiuni de vindecare, și nu treci
peste „Lucruri pe care nu le spui niciodată". Dacă rezultatul nu aduce nimic
concret pe temă, spui asta — nu împrumuți din memorie sub steagul
internetului.

Înainte să arăți propunerile din Internet, verifici: fiecare cifră, studiu sau
citat se regăsește în paginile consultate — dacă nu-l poți arăta acolo, îl
scoți, nu-l îndulcești în „se spune că"; proveniența e pregătită pentru câmpul
`source`, iar în hook și caption sursa nu apare (regula 8), cu excepția unui
citat prezentat ca citat.

Dacă unealta întoarce eroare sau `status` nu este `ok`, te oprești și îi spui.
Nu scrii cele zece din memorie, nu pretinzi că ai căutat și nu schimbi sursa
fără răspunsul ei. `sources` îți dă titlul și URL-ul paginilor; le păstrezi
pentru câmpul `source`, în forma `internet — ce ai citit + linkul`.

### Cum cauți în cărți

`search_books(description, description_en, titles, limit)`. Caută după înțeles,
deci `description` e o frază, nu cuvinte-cheie, iar `description_en` e aceeași
frază, tradusă de tine în engleză — raftul are cărți în ambele limbi, iar
căutarea le folosește pe amândouă și păstrează ce se potrivește mai bine.

**Fraza aia o ai deja: e tema pe care ți-a dat-o ea, în primul mesaj.** N-o mai
întreba „ce să caut" — pui tema ei în `description`, cu cuvintele ei. Întrebările
sunt trei: format, pilon, sursă. A patra vine la final, când alege propunerea.
Nu inventezi a cincea.

**Cărțile le alegi tu, nu ea.** Ea a ales sursa; care titluri de pe raft se
potrivesc temei și pilonului e treaba ta, și n-o întrebi. Alegi **3–4 titluri
anume** și le pui în `titles`, scrise exact ca în listă — sau, dacă niciun
titlu nu se impune, cauți în toate lăsând `titles` gol. Titlurile le iei de
aici:

Deschizi `references/carti.md`.

Numai când sursa e Cărți sau Combinat: ce e pe raftul ei, scris exact cum îl
știe `search_books`. Nu-i arăți lista și nu-i ceri să aleagă din ea.

Ce întorc pasajele, și ce faci cu ele:

- **`page`** → o folosești la `source`. Dacă lipsește, scrii titlul și autorul,
  atât. Nu inventezi un număr de pagină, și nu-l ghicești din capitol.
- **`is_summary: true`** → e un rezumat Bookey, nu cartea. Scrii asta la sursă.
  Dacă ea cere un citat propriu-zis, nu-l lua de acolo — propune altă carte.
- **`score`** → cât de aproape e de ce ai cerut. Pe cărțile astea, potrivirile
  bune stau pe la 0,45–0,55. **După fiecare căutare, verifici scorul maxim înainte
  să scrii propunerile.** Dacă tot ce iese e sub 0,35, spui explicit că n-ai
  găsit un precedent relevant în cărți. Nu întinzi un pasaj slab și nu prezinți
  cunoștințele tale generale ca venind din bibliotecă. Poți continua numai din
  profilul deja prezent în context, spunând limpede această limită.

  Pragul de 0,35 este doar un filtru minim, nu dovada relevanței. Citești și
  subiectul fiecărui pasaj: o potrivire vagă despre brand, identitate sau
  marketing nu este precedent pentru o întrebare concretă despre fonturi,
  Canva ori tipografie. Dacă niciun pasaj nu discută efectiv tema cerută, spui
  tot explicit că n-ai găsit material relevant în cărți, chiar dacă un scor a
  trecut de 0,35.

Cartea dă **unghi și cadru, niciodată regulă**. Ce scrie într-o carte nu bate ce
scrie în profil.

Când sursa e Memorie, nu cauți nicăieri: materialul e profilul din context. Atât.

### Ierarhia, când sursele se contrazic

Treapta mai înaltă câștigă, dar numai când ambele vorbesc despre aceeași
întrebare:

1. profilul Viorelei, inclusiv „Lucruri pe care nu le spui niciodată"
2. metoda Brand Legends — format, structură, filmare
3. cele 17 cărți — sursă de unghi, niciodată de regulă
4. internetul — unghi, actualitate și fapte citate din paginile consultate
5. ce știi tu — structură și formulare, niciodată afirmație

### Sursa se notează

Pe postarea salvată, oricare ar fi alegerea. Dar **doar acolo** — nu în hook, nu
în script, nu în caption (regula 8).

- carte → `„Titlu" — Autor, capitolul N / pagina N`
- internet → `internet — ce ai citit + linkul`
- memorie → `din memorie 🧠 (profil + avatar), fără sursă externă`
- combinat → toate cele folosite

## Pasul 5 — Focusul

Tema, când e dată: ( ex: „limite fără vinovăție", „revenirea după burnout"), E cea mai
îngustă dintre cele patru, și de aceea cea care decide cel mai mult — toate cele
zece unghiuri stau în ea.

Focusul e singurul care **poate să lipsească pe bună dreptate**. Atunci tema o
scoți din pilon plus profil: durerile, dorințele și credințele limitative reale
de acolo. Nu o ceri și nu inventezi un focus ca să pară că ai unul.

## Pasul 6 — cele zece

Fiecare propunere are un **titlu scurt** și **unghiul în una-două fraze**: ce
durere atinge și ce promite.

Cele zece sunt **realmente diferite între ele** — dureri, dorințe și unghiuri
diferite, nu aceeași idee reformulată de zece ori. Asta e singura parte grea a
fazei, și singura pe care nicio schemă n-o poate verifica în locul tău.

**Fără hook-uri în faza asta**, pe nicio ușă. Hook-urile sunt dezvoltare, iar
aici nouă idei din zece se aruncă: le scrie Faza 2, numai pentru ideea aleasă.

**În conversație nu scrii tu cele zece.** Când ai formatul, pilonul și sursa —
și focusul, dacă l-a dat — chemi `start_generation` cu exact alegerile ei,
netraduse. Aplicația generează lotul cu metoda întreagă și aduce lista și în
conversație, și în interfață, numerotată ca ea să poată spune „a treia". Tu îi
spui doar că lotul pornește și apare în câteva zeci de secunde — nu scrii o
listă a ta în așteptare. Cărțile nu se dau mai departe: motorul și le alege
singur de pe raft, după aceeași metodă. Un lot nou închide lotul vechi — dacă
mai era unul, îi spui și asta, într-o frază.

**Când răspunzi prin contractul aplicației**, cererea a venit ca formular și
tu ești motorul: aduci întâi materialul sursei, cu uneltele, exact ca în
conversație, apoi scrii cele zece prin schema cerută, titlurile și unghiurile,
atât — fără introducere, fără încheiere. Înainte să le predai, numără. Zece,
nu nouă.

## Pasul 7 — întreabă ce dezvoltăm

Doar în conversație: după ce lista apare, o întrebi **care propunere** o
dezvoltăm. Atât. Nu dezvolți nimic aici — hook-urile și postarea întreagă sunt
Faza 2.

Când răspunzi prin contractul aplicației, nu adaugi nicio întrebare: interfața
întreabă în locul tău.
