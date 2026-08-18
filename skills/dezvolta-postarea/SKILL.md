---
name: dezvolta-postarea
description: >-
  Faza 2 — dezvoltă UNA din cele zece propuneri, pe hook-ul ales de ea, până la
  postare completă: script, caption, hashtaguri, CTA. Folosește-l când Viorela
  a ales dintr-o listă deja arătată: „dezvoltă a treia, cu contrastul",
  „îmi place 7", „scrie-o pe aia cu vinovăția", „hai pe prima". Îl folosești
  și când cere încă una din aceeași listă. NU-l folosi ca să scoți propuneri noi
  — aia e faza 1.
---

# Faza 2 — postarea întreagă

## Mod UI structurat — toate cele cinci variante

Dacă mesajul începe cu markerul exact `MOD UI STRUCTURAT D1B — DETALII`,
interfața îți dă o singură idee existentă, formatul, pilonul, sursa, focusul și
materialul-sursă. În acest mod:

- nu cauți lista în conversație, nu pui întrebări și nu alegi altă idee;
- dezvolți ideea primită în exact cinci variante complete, în ordinea
  PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE, CONTRAST;
- la **Reel** fiecare variantă are `hook_type`, `hook`, `caption`, 3–5
  `hashtags`, `cta` și `source` — fără `script` și fără `format_details`,
  pentru că reel-urile ei sunt mute (vezi mai jos);
- la **Carusel** și **Stories** fiecare variantă are în plus `script` și
  `format_details`, cu `content_blocks`, `visual_direction` și
  `duration_or_count` potrivite formatului;
- toate cele cinci variante folosesc același unghi, dar hook-ul și construcția
  lor sunt realmente diferite;
- nu arăți un mesaj conversațional, nu ceri aprobare, nu salvezi și nu chemi
  `save_post`. Interfața va afișa și va salva ulterior numai varianta aleasă.

Respecți în continuare metoda formatului din Pasul 1, regulile de conținut din
Pasul 2 și restricțiile profilului. Contractul structurat al aplicației verifică
cele cinci tipuri și câmpurile complete. Restul acestui skill rămâne fluxul
normal al conversației CLI, unde dezvolți o singură variantă aleasă.

## Pasul 0 — verifică dacă lista există

Înainte de orice altceva, verifici conversația: există lista celor zece
propuneri la care se referă „a treia”, „prima” sau „aia cu vinovăția”?

Dacă NU există, te oprești. Spui limpede că nu ai nicio listă din care să iei
propunerea și întrebi dacă facem una nouă. **Nu inventezi propunerea și nu ceri
formatul, pilonul sau sursa ca și cum ai continua Faza 2.** Acelea apar în Faza 1.

Iei **o singură** propunere, cea aleasă de ea, cu hook-ul ales de ea, și o duci
până la capăt. Celelalte nouă rămân unde sunt.

Dacă n-a spus limpede care propunere sau care hook, **întrebi**. Nu alegi tu.

## Pasul 1 — citește metoda pentru formatul ei

Doar fișierul de care ai nevoie, nu tot manualul:

- **Reel** → `references/structura-reel.md` pentru structura ideii, plus
  `references/hookuri-si-scripturi.md` pentru formulări și `references/b-roll.md`
  pentru ce se vede pe ecran. Citește-le știind că reel-ul ei e mut: structura
  în patru pași rămâne, dar se scrie în caption, nu în script
- **Stories** → `references/stories.md`
- **Carusel** → n-are fișier de metodă; structura e mai jos, la Pasul 2

`references/filmare.md`, `editare.md` și `distribuire.md` se deschid doar dacă ea
întreabă despre filmare, montaj sau postare. Nu le citi „ca să fii sigur".

## Pasul 2 — scrie postarea

### Reel-urile ei sunt mute

Viorela filmează fără să vorbească: cadru + text pe ecran. Deci **un Reel nu are
script și nu are bloc de producție.** Nu-l scrie, nu-l propune, nu întreba dacă
îl vrea.

Tot ce ar fi spus cu vocea intră în **caption**, și de aceea captionul unui Reel
e lung — 900–1400 de semne:

- intră direct în ideea din hook, fără reintroducere;
- o desfășoară în 2–4 paragrafe scurte, așa cum i-ar fi povestit unei prietene:
  exemplul concret, ce se întâmplă de fapt, ce poate face ea cu asta;
- se închide cu întrebarea de engagement.

`hook` rămâne scurt: e textul care apare pe ecran în primele două secunde.
Structura în patru pași din `references/structura-reel.md` rămâne validă — hook,
promisiune, payoff, CTA — doar că se scrie, nu se spune.

### Carusel și Stories

Acolo **SCRIPT**-ul rămâne, pe formatul ales:

- *Carusel*: slide cu slide. Slide 1 = hook vizual, o idee per slide, ultimul = CTA.
- *Stories*: secvența de 3–7 story-uri, cu sticker de interacțiune unde are sens.

**CAPTION** la aceste două: 2–4 fraze scurte, conversaționale, în vocea ei, cu o
întrebare de engagement la final.

**HASHTAGURI**: 3–5, relevante pentru nișă, variate.

**CTA**: cel potrivit din secțiunea 6 a profilului. Dacă la categoria potrivită
scrie încă `⚠️ DE COMPLETAT`, propui unul, spui limpede că e propus de tine, și
o rogi să-l treacă în profil ca să rămână.

**SURSA** nu intră în postare. Nici în hook, nici în script, nici în caption —
doar pe câmpul `source` la salvare (regula 8). Excepție: un citat prezentat ca
citat, sau dacă ea cere explicit.

## Pasul 3 — arată-i-o întreagă și așteaptă

O arăți toată în chat: la Reel — hook, caption, hashtaguri, CTA; la Carusel și
Stories, și scriptul. Apoi te oprești și aștepți. **Nu salvezi nimic până nu spune „da"** (regula 10).

Dacă cere modificări, o rescrii și i-o arăți din nou. De câte ori e nevoie.

## Pasul 4 — salvează, o singură dată

După „da"-ul ei, `save_post(...)`, cu:

- `title`, `pillar`, `format` — cele alese la faza 1
- `hook` și `hook_type` — hook-ul ales de ea, textul lui și tipul
- `caption`, `hashtags`, `cta` — exact ce i-ai arătat, nu altă variantă
- `script` — doar la Carusel și Stories. La Reel îl lași gol
- `source` — adevărul despre de unde vine materialul:
  - carte → `„Titlu" — Autor, pagina N`; fără pagină, doar titlul și autorul
  - rezumat Bookey → scrii că e rezumat
  - memorie → `din memorie 🧠 (profil + avatar), fără sursă externă`

Îi confirmi scurt că s-a salvat. Atât.

## Încă una din aceeași listă

Dacă după salvare cere altă propunere din cele zece — „acum și a șaptea" —
**nu regenerezi lista.** Cele zece sunt deja în conversație, mai sus. O iei pe a
șaptea de acolo și o dezvolți la fel.

Dacă chiar nu mai sunt în conversație, spui asta și întrebi dacă facem o listă
nouă. Nu inventezi „a șaptea".
