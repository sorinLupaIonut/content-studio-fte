---
name: propune-postari
description: >-
  Faza 1 a producției de conținut — scoate zece propuneri de postare, fiecare cu
  cinci hook-uri, după ce afli formatul, pilonul și sursa. Folosește-l când
  Viorela cere conținut nou: „vreau un reel despre limite", „dă-mi conținut pe
  Conexiune", „zece propuneri pe Educație", „ceva despre vinovăția de a spune
  nu", „conținut pentru săptămâna asta". Îl folosești OBLIGATORIU și în MOD UI
  STRUCTURAT D1B — TITLURI, unde cererea nu vine în cuvintele ei, ci ca formular:
  format, pilon, sursă. Acolo e singura sursă a metodei; fără el scrii titluri
  din memorie. NU-l folosi pentru editarea unei postări existente, pentru o
  întrebare despre profil, sau pentru o cerere de raport.
---

# Faza 1 — cele zece propuneri

Scopul: îi dai Viorelei zece unghiuri diferite pe tema ei, fiecare cu cinci
hook-uri, ca să aleagă una singură pe care s-o dezvoltăm.

## Mod UI structurat — numai titlurile

Dacă mesajul începe cu markerul exact `MOD UI STRUCTURAT D1B — TITLURI`, interfața
a adunat deja formatul, pilonul, sursa, focusul și materialul-sursă. În acest mod:

- nu pui întrebările din Pasul 1 și nu alegi alte valori;
- folosești numai materialul-sursă inclus în mesaj și regulile profilului;
- întorci exact zece obiecte, ordonate de la 1 la 10, fiecare numai cu `ordinal`,
  `title` și `angle`;
- nu scrii hook-uri, script, caption, hashtaguri sau CTA în această execuție;
- nu adaugi introducere, încheiere ori întrebare și nu chemi nicio unealtă de
  scriere.

Titlurile și unghiurile respectă toate verificările din Pasul 2, Pasul 3 și
„Când te oprești”. Contractul structurat al aplicației verifică numărul și
ordinea. Restul acestui skill rămâne fluxul normal al conversației CLI.

## Pasul 1 — cele trei răspunsuri, obligatorii

Nu scrii nimic până nu ai toate trei. Le ceri **pe rând, ca întrebări separate**,
nu toate într-un mesaj.

1. **Formatul** — Reel, Carusel sau Stories
2. **Pilonul** — înainte să întrebi, deschizi `references/piloni.md`; oferi exact
   vocabularul închis de acolo, toate cele cinci variante, fără redenumiri
3. **Sursa** — înainte să întrebi, deschizi `references/surse.md`; oferi exact
   cele patru variante de acolo și spui scurt dacă una nu funcționează azi

Excepție unică: dacă a spus deja limpede răspunsul în mesaj („vreau un **reel**
despre limite"), ăla e răspunsul ei — confirmi scurt și treci mai departe.

Dacă răspunde ambiguu sau sare peste una, **reîntrebi**. Nu alegi în locul ei și
nu pornești „pe o variantă până răspunde".

Trei întrebări, nu patru. **Nu inventezi întrebări în plus** — tema o ai din
mesajul ei, nu i-o mai ceri o dată sub altă formă.

## Pasul 2 — adună materialul

Din sursa pe care a ales-o **ea**, nu din alta. Citește `references/surse.md`:
spune ce are voie să dea fiecare sursă și ce nu, cum se cheamă
`search_books` dacă a ales Cărți și `search_web` dacă a ales Internet.

Materialul se adună **înainte** de a scrie propunerile. Nu scrii din memorie ca
apoi doar să adaugi referința.

Dacă ai căutat în cărți, verifici înainte de generare și scorurile, și subiectul
pasajelor. Un scor peste prag nu ajunge dacă pasajul vorbește doar vag despre
brand, identitate sau marketing, iar tema cerută este una concretă precum
fonturile în Canva. Dacă niciun pasaj nu tratează tema, spui explicit că n-ai
găsit material relevant în cărți; nu îl întinzi ca să pară potrivit.

## Pasul 3 — scrie cele zece

Fiecare propunere are:

- **titlu scurt**
- **ideea în una-două fraze**
- **cinci hook-uri: câte unul din fiecare tip**, în ordinea PROVOCARE, CIFRĂ,
  SECRET, ÎNTREBARE, CONTRAST — vezi `references/hookuri.md`

Numerotează propunerile de la 1 la 10, ca ea să poată spune „a treia", și scrie
tipul în fața fiecărui hook, ca să poată spune „a treia, cu contrastul":

```
3. Titlul scurt
   Ideea, în una-două fraze.
   - PROVOCARE: …
   - CIFRĂ: …
   - SECRET: …
   - ÎNTREBARE: …
   - CONTRAST: …
```

Cele zece sunt **diferite între ele**: unghiuri, dureri și dorințe diferite, nu
aceeași idee reformulată de zece ori.

Înainte să i le arăți, numără. Zece propuneri. Cinci hook-uri la fiecare, câte
unul din fiecare tip, niciunul repetat. Dacă îți ies nouă, mai scrii una; nu-i
arăta o listă incompletă.

## Pasul 4 — întreabă ce dezvoltăm

După ce i-ai arătat lista, o întrebi **care propunere și cu care hook**. Atât.
Nu dezvolți nimic în faza asta.

## Când te oprești, nu doar încetinești

- **Tema intră în conflict cu „Lucruri pe care nu le spui niciodată"** din
  profil → nu scrii propunerile afectate. Spui care e conflictul și ceri decizia
  ei.
- **Pilonul e Conversie, dar secțiunea de oferte din profil are ⚠️**, ori CTA-ul
  potrivit e încă necompletat → generezi ce se poate și semnalezi scurt ce
  lipsește. Nu inventezi oferta.
- **Ți se cere o cifră sau un testimonial care nu e în profil** → refuzi și
  propui un înlocuitor.
