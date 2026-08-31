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

### ÎNTÂI DE TOATE: de unde a venit cererea decide dacă tu scrii ceva

Restul fișierului te învață cum se scriu zece propuneri. **Aia e treaba ta doar
când cererea vine ca formular, din aplicație.**

**Dacă vorbiți în conversație**, treaba ta se termină mai devreme și e mai
scurtă:

1. întrebi ce lipsește, pe rând, cu vocabularul de mai jos — dar **numai
   formatul, pilonul și sursa**. Alea trei sunt obligatorii;
2. **focusul NU se cere.** E opțional, iar dacă ea a pomenit deja o temă în
   conversație — „ceva despre limite" — ăla ESTE focusul: îl iei de acolo și
   mergi mai departe. Dacă n-a spus nimic, trimiți `start_generation` fără el.
   O întrebare în plus pentru un câmp opțional e o întrebare care o ține pe loc;
3. de cum ai cele trei obligatorii, chemi `start_generation`;
4. îi spui într-o frază că lotul pornește și apare în câteva zeci de secunde.

**Și te oprești acolo.** Nu cauți nimic, nu alegi cărți, nu scrii nicio
propunere — aplicația generează cele zece cu metoda întreagă și le aduce chiar
în conversația asta. Dacă le scrii și tu, ea primește două liste diferite pentru
aceeași cerere, iar a ta e cea care n-a trecut prin metodă.

Pașii de mai jos rămân valabili pentru vocabularul întrebărilor — cei cinci
piloni, cele patru surse. Ce **nu** se aplică pe ușa de conversație e tot ce
vine după: căutarea, raftul, scrisul propunerilor.

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
| 🔀 Combinat | raftul **și** webul, amândouă | ce dă fiecare | regulile fiecăreia se cumulează, nu se anulează |

Profilul nu e în listă pentru că nu e o alegere — îl ai deja întreg, la orice
variantă. Nu înlocui și nu adăuga tăcut altă sursă.

**Combinat înseamnă amândouă: cărțile și internetul.** Nu e o sub-alegere pe
care ea o face și tu o citești — alegerile ei sunt patru, iar „Combinat" e una
singură. Nu ghici care jumătate a vrut și nu te opri după prima.

Dacă sursa lipsește, o ceri cu variantele din tabel. După ce a ales-o, nu mai
aduci material din alta.

### Ce chemi — decide sursa, nu formatul

**Citește rândul tău și fă exact ce scrie în el. Nimic în plus.**

| Sursa aleasă de ea | Unealta pe care o chemi |
|---|---|
| 🧠 Memorie | **niciuna** |
| 📚 Cărți | `search_books` |
| 🌐 Internet | `search_web` |
| 🔀 Combinat | `search_books` **și** `search_web` |

**Unealta de pe rândul tău nu e opțională, și n-o judeci tu.** O chemi de
fiecare dată, înainte să scrii prima propunere — nu „dacă e nevoie", nu „dacă
tema o cere". Singurul rând fără unealtă este Memorie, și acolo n-o chemi
niciodată.

Faza asta nu deschide niciun fișier, la nicio sursă: tot ce-ți trebuie e aici,
în `SKILL.md`. Regula de căutare de mai jos e aceeași pentru amândouă uneltele;
raftul de după ea e pentru cine caută în cărți, nu pentru toată lumea.

### Cum cauți — aceeași regulă la amândouă uneltele

**Ce ceri.** O frază, nu cuvinte-cheie, care ține cont de trei lucruri deodată:
formatul, pilonul și focusul alese de ea. Iar fraza pornește dintr-un rând anume
despre Andreea — o nevoie, o dorință, o durere, o frică sau o credință scrisă în
profil, în cuvintele ei. Nu ceri „limite" sau „grija de sine": ceri lucrul
concret de care are ea nevoie acum. La `search_books` dai aceeași frază și în
engleză, pe `description_en` — raftul are cărți în ambele limbi.

**Ce iei.** Numai ce apare chiar în rezultat, niciodată din memoria ta. Citești
și subiectul, nu doar scorul: un rezultat care vorbește vag despre altceva nu e
material, oricât de sus ar fi scorul. Pe cărți, potrivirile bune stau pe la
0,45–0,55.

**Când nu găsești.** Scrii din ce ai și spui adevărul pe `source`. Nu întinzi un
rezultat slab ca să pară potrivit, nu reiei căutarea la nesfârșit cu alte
formulări, și nu treci cunoștințele tale generale drept material găsit.

**Proveniența** merge pe câmpul `source` — vezi mai jos ce scrii acolo.

**La faza asta cauți o singură dată, pentru zece propuneri diferite.** Deci
ceri larg în jurul focusului: materialul trebuie să hrănească zece unghiuri care
nu se repetă între ele. O căutare îngustă pe un singur fir îți dă zece variații
ale aceleiași idei.

### Raftul — titlurile pe care le pui în `titles`

**Cărțile le alegi tu, nu ea.** Ea a ales sursa; care titluri de pe raft se
potrivesc temei și pilonului e treaba ta, și n-o întrebi. Alegi **3–4 titluri
anume** și le pui în `titles`, scrise exact ca în listă — sau, dacă niciun
titlu nu se impune, cauți în toate lăsând `titles` gol. Titlurile le iei de
aici:

Raftul e mai jos, scris exact cum îl știe `search_books` în `titles`. **Nu-i
arăți lista și nu-i ceri să aleagă din ea** — la Memorie și la Internet nici
n-o folosești, fiindcă de pe un raft din care n-ai voie să iei nu se ia nimic,
nici măcar un titlu pomenit în treacăt. Dacă adaugi o carte în bibliotecă,
adaug-o și aici: de aici își ia numele.

#### People pleasing, limite, „nu"-ul

- **Granițe în relații** — Henry Cloud & John Townsend
- **The Disease to Please. Curing the People-Pleasing Syndrome** — Harriet B. Braiker
- **Set Boundaries, Find Peace** — Nedra Glover Tawwab (rezumat Bookey)
- **Teoria „Let Them”** — Mel Robbins
- **Curajul de a nu fi pe placul celorlalți** — Ichiro Kishimi & Fumitake Koga

#### Burnout, stres, corp

- **Când corpul spune nu. Costul stresului ascuns** — Gabor Maté
- **The Body Keeps the Score** — Bessel van der Kolk
- **ACT for Burnout** — Debbie Sorensen
- **The Trauma of Burnout**
- **Burnout Coach Handbook** — The Priority Academy

#### Rușine, vulnerabilitate, compasiune de sine

- **Curajul de a fi vulnerabil** — Brené Brown
- **Darul imperfecțiunii** — Brené Brown
- **The Self-Compassion Skills Workbook** — Tim Desmond
- **Inner Critic Workbook**

#### Tipare vechi, autosabotaj, traumă

- **Reinventing Your Life** — Jeffrey E. Young & Janet S. Klosko
- **Letting Go of Self-Destructive Behaviors** — Lisa Ferentz
- **Self-Guided EMDR Therapy Workbook** — Katherine Andler

Faza asta nu mai deschide niciun fișier: citești `SKILL.md` și scrii.

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
