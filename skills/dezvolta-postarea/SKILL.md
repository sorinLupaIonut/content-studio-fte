---
name: dezvolta-postarea
description: 'Faza 2 — dezvoltă UNA din cele zece propuneri până la postare completă: hook, caption, hashtaguri, CTA, iar la Carusel și Stories și scriptul. Îl folosești OBLIGATORIU când ideea îți este dată întreagă în mesaj, ca formular, cu formatul, pilonul, sursa și focusul ei. Când ea alege dintr-o listă — „îmi place 7", „hai pe prima" — verifică ÎNTÂI etapa: propunerea aleasă trebuie să existe deja, scrisă în conversație. Tot aici intri și DUPĂ ce variantele unei idei au apărut, când ea alege una — „a doua", „cea cu CIFRA" — sau cere modificări pe ea. Dacă lista de propuneri NU e în conversație, nu deschide nimic — nici acest skill, nici Faza 1: spui că nu ai lista de idei, o întrebi dacă vrea să o generați întâi, și te oprești acolo. NU-l folosi ca să scoți propuneri noi: aia e Faza 1.'
---

# Faza 2 — postarea întreagă

O singură idee, dusă până la capăt. Celelalte nouă rămân unde sunt.

## Pasul 1 — ce ai deja, și ce faci cu asta

Cererea vine din aplicație, iar alegerile sunt făcute înainte să ajungă la tine:

- **Ideea** — titlul și unghiul, exact cum au fost scrise în Faza 1
- **Formatul** — Reel, Carusel sau Stories
- **Pilonul** — unul din cele cinci
- **Sursa** — de unde vine materialul
- **Focusul** — tema, când e dată

**Nu le pui la îndoială și nu ceri confirmare pentru ele.** Sunt deja răspunsul
ei; le-a ales apăsând pe ele.

## Pasul 2 — Ideea

Pe asta o dezvolți, și numai pe asta. Nu o rescrii, nu o îmbunătățești, nu o
înlocuiești cu una care ți se pare mai bună. `title` și ordinea ei rămân
neatinse: interfața le-a scris deja în bază, iar o idee care se schimbă pe drum
e o idee pe care ea n-a ales-o.

Unghiul primit e ce ține cele cinci variante împreună. Toate pornesc din el;
diferă prin **cum atacă**, nu prin ce spun.

Dacă ideea îți vine din conversație — „a treia", „hai pe prima" — verifică întâi
în ce etapă ești. Etapele sunt trei, și fiecare are alt răspuns corect:

- **Nicio listă de propuneri în conversație** → te oprești: spui că nu ai lista
  de idei și propui să o generați întâi — Faza 1, cu acordul ei, nu din proprie
  inițiativă. Nu inventezi „a treia" și nu ceri formatul sau pilonul ca și cum
  ai continua: alea sunt întrebările Fazei 1.
- **Lista există, iar propunerea aleasă nu e încă dezvoltată** → chemi
  `develop_idea` cu numărul ei — „a treia" înseamnă 3. **Nu scrii tu
  variantele**: aplicația le generează cu metoda formatului și le aduce și în
  conversație, și în interfață. Tu îi spui doar că pornesc și apar în câteva
  zeci de secunde. Dacă n-a spus limpede care propunere, întrebi; nu alegi tu.
- **Postarea cerută e deja dezvoltată** → nu o iei de la zero: modifici ce a
  cerut și atât.

## Înainte de orice — două drumuri, nu unul

Ca să scrii postarea îți trebuie **două lucruri care nu sunt în mesajul tău**, și
le aduci pe amândouă înainte de primul rând scris:

1. **Fișierul formatului** — `cat` pe fișierul din tabelul de la Pasul 3.
2. **Materialul sursei** — unealta din tabelul de la Pasul 5, când sursa are una.

Sunt două drumuri separate, și niciunul nu-l scutește pe celălalt: fișierul îți
spune **cum** se construiește postarea, unealta îți dă **din ce**.

**Le ceri pe amândouă odată, nu pe rând.** Sursa ți-e scrisă în cerere, deci
unealta o poți chema în aceeași tură în care citești, fără să aștepți fișierul;
iar dacă sursa e Combinat, cele două căutări pleacă împreună. Nu-ți trebuie
răspunsul uneia ca s-o formulezi pe cealaltă — nimic din ce ceri aici nu depinde
de ce ai cerut alături.

**Aici se greșește, și se greșește într-un fel care nu doare pe loc.** Faci
primul drum, te simți pregătit și treci la scris — iar postarea iese
plauzibilă și greșită: ori construită corect din material inventat, ori cu
material bun turnat într-o formă care nu e a formatului ei. Numără-le înainte să
scrii. Dacă sursa nu e Memorie, ai **două** lucruri de făcut, nu unul; ai făcut
doar unul, încă n-ai început.

## Pasul 3 — Formatul

Formatul decide ce scrii și ce nu scrii. **Un fișier, al formatului tău, de
fiecare dată, înainte să scrii.** Unul singur, și niciodată al altui format.
Ăsta e **drumul 1** din cele două de mai sus; drumul 2 te așteaptă la Pasul 5.

| Formatul ei | Fișierul pe care îl deschizi |
|---|---|
| Reel | `references/reel.md` |
| Carusel | `references/carusel.md` |
| Stories | `references/stories.md` |

Formulările hook-urilor nu sunt într-un fișier — sunt la Pasul 7, în paginile
astea, fiindcă îți trebuie la orice format.

### Reel — și reel-urile ei sunt mute

Viorela filmează fără să vorbească: cadru + text pe ecran. **Un Reel nu are
script și nu are bloc de producție.** Nu-l scrie, nu-l propune, nu întreba dacă
îl vrea; contractul aplicației nici nu-l acceptă.

Deschizi `references/reel.md`.

**O ceri de fiecare dată la Reel, fiindcă nu ai de unde altundeva.** Structura
reelului cu scopul fiecărui pas și formulele lui testate, tipurile de hook, de
payoff și de CTA, felurile de reel recomandate, listele de b-roll și reelurile
lucrate cap-coadă — **niciunul din lucrurile astea nu e în paginile de față.**
Paginile astea îți spun ce format ai și cum se poartă; reelul propriu-zis e
scris acolo. Din memorie iese ceva care seamănă cu un reel și nu e al ei.

Fișierul se citește cu o corecție, pe care o aplici **după** ce l-ai deschis: o
parte din exemple sunt din alt cont, scrise pentru cineva care vorbește în
cameră — „Vorbeste:", „VIDEO CU TINE", „REEL TALKING". Structura și felul în
care se construiește tensiunea rămân valabile întregi; scriptul vorbit nu-l iei
și nu-l propui. Se **scrie**, nu se spune: tot ce ar fi fost rostit intră în
caption (Pasul 7). La un reel mut hook-ul e textul de pe ecran din primele două
secunde, deci e chiar produsul, nu un ambalaj.

### Stories

Deschizi `references/stories.md`.

**O ceri de fiecare dată la Stories.** Secvența de 3–7 story-uri, cu sticker de
interacțiune unde are sens, plus tiparele de idee și exemplele de storytelling.
Aici **scriptul rămâne**, plus blocul de producție.

### Carusel

Structura e aici, nu într-un fișier de metodă: slide 1 = hook vizual, o idee
per slide, ultimul = CTA. Script și bloc de producție, da.

Deschizi `references/carusel.md`.

**O ceri de fiecare dată la Carusel.** Patru caruseluri duse cap-coadă — hook,
slide-uri, caption, CTA. E singurul loc din metodă unde caruselul e arătat slide
cu slide, nu descris.

### Întrebările de producție — nu ai material pentru ele

Cum se filmează, montaj, când și cum se postează, echipament: astea nu fac
parte din metoda ta. Nu ai un fișier pentru ele și nu improvizezi unul din
memorie — aici e cel mai ușor de dat un sfat care sună bine și e greșit. Îi
spui sincer că materialul de producție nu e la tine, și te întorci la postare.

## Pasul 4 — Pilonul

Pilonul primit e o etichetă. Ce fel de conținut cere de fapt, și ce așteaptă
contul ei de la el, e aici — nu ghici din nume pe ce mizează postarea, și nu-i
oferi ei o listă de piloni: alegerea e făcută în Faza 1.

- **🎯 Poziționare** — construiește încredere prin dovezi: că face ce spune că
  face, de ce felul ei de a lucra e diferit, de ce e ea soluția potrivită.
  Postarea așază, nu vinde.
- **📚 Educație** — valoare care răspunde durerilor, fricilor, dorințelor și
  convingerilor avatarului. Aici se construiesc loialitatea și credibilitatea:
  postarea o face conștientă de problemă și de soluție. Un lucru pe postare,
  aplicabil azi.
- **🤝 Conexiune** — omul din spatele afacerii. Ce a trăit ea, prin ce a trecut,
  de ce și-a creat businessul, ce o motivează — momentul, nu concluzia despre
  moment. Oamenii cumpără de la oameni, iar conexiunea emoțională se face cu
  lucruri reale, nu cu lecții.
- **💰 Conversie** — oferta, transformările, beneficiile, rezultatele, chemarea
  la acțiune. CTA-ul vine din secțiunea de oferte a profilului; dacă acolo e
  ⚠️, propui unul, nu inventezi o ofertă.
- **✨ Magnetism** — engagement: situații cu care avatarul se identifică pe loc,
  „Doamne, la fel sunt și eu". Personalitate, ritualuri, umor, trenduri. Nu
  vinde și nu învață — face să vrei să rămâi.

Orice pilon ar fi, subiectul ales trebuie s-o facă pe femeia din avatar să
spună „e ca și cum ai vorbi direct cu mine" — pentru că exact asta face
postarea.

## Pasul 5 — Sursa, și materialul pe care trebuie să-l aduci

Materialul nu vine de-a gata în mesaj: ți-l aduci singur, cu uneltele, din
sursa aleasă de ea. Aici scrii textul care ajunge la ea, deci aici ai nevoie de
concret — exemplul, pasajul, formularea.

**Chemi unealta sursei de fiecare dată, înainte să scrii.** Ăsta e **drumul 2**,
și faptul că l-ai făcut pe primul — ai deschis fișierul formatului — nu-l
înlocuiește. Nu e o opțiune, și
nu depinde de cât de acoperit te simți: sursa a fost alegerea ei, iar o postare
scrisă din memorie sub steagul unei cărți e o postare care minte pe câmpul
`source`. În aceeași sursă, niciodată în alta. Regulile de mai jos contează
**mai mult** aici decât în Faza 1, fiindcă acum nu scrii un titlu, ci textul
întreg.

**Cauți din nou, chiar dacă Faza 1 a căutat deja.** Căutarea de atunci a fost
pentru titlu, iar pasajele ei nu sunt în mesajul tău: ai titlul și unghiul,
atât. Dacă sursa e Cărți, chemi `search_books` aici a doua oară, pentru textul
întreg — nu e o repetiție, e singura căutare care ajunge în postare.

**Citește rândul tău și fă exact ce scrie în el. Nimic în plus.**

| Sursa aleasă de ea | Unealta pe care o chemi |
|---|---|
| 🧠 Memorie | **niciuna** |
| 📚 Cărți | `search_books` |
| 🌐 Internet | `search_web` |
| 🔀 Combinat | `search_books` **și** `search_web` |

**Combinat înseamnă amândouă.** Nu e o sub-alegere pe care ea o face și tu o
citești — alegerile ei sunt patru, iar „Combinat" e una singură. Nu ghici care
jumătate a vrut și nu te opri după prima.

- **Cărți sau Combinat** → `search_books(description, description_en, titles,
  limit)`, cu unghiul ideii ca întrebare, nu cu tema largă: `description` e o
  frază, `description_en` aceeași frază tradusă de tine în engleză — raftul are
  cărți în ambele limbi. Verifici **și scorurile, și subiectul** pasajelor: un
  scor peste prag nu ajunge dacă pasajul vorbește vag despre altceva. Dacă nu
  găsești nimic care chiar tratează unghiul, scrii din ce ai și spui adevărul pe
  `source`; nu întinzi un pasaj ca să pară potrivit. Un pasaj cu
  `is_summary: true` e rezumat Bookey, nu cartea — nu iei citate propriu-zise
  de acolo, și scrii la sursă că e rezumat.
- **Internet sau Combinat** → `search_web(description, limit)`. Iei
  ce servește unghiul: teme, dar și cifre, studii ori citate — numai dacă apar
  chiar în paginile consultate, niciodată completate din memorie — și le duci pe
  `source` cu linkul lor, din `sources`. Dacă unealta dă eroare, te oprești și
  spui asta; nu generezi din memorie și nu schimbi sursa.
- **Memorie** → nu cauți nicăieri. Materialul e profilul din context, atât.

Întrebi **bine din prima**: cu unghiul ideii ca întrebare, nu cu tema largă.
Economia stă în cum întrebi, niciodată în a sări peste căutare — dacă primul
rezultat nu tratează unghiul, nu reiei la nesfârșit cu alte formulări: scrii din
ce ai și spui adevărul pe `source`.

Cartea dă **unghi și cadru, niciodată regulă**: ce scrie într-o carte nu bate ce
scrie în profil, iar peste „Lucruri pe care nu le spui niciodată" nu trece nicio
sursă.

### Sursa rămâne în culise

Nici în hook, nici în script, nici în caption — doar pe câmpul `source`
(regula 8). Excepție: un citat prezentat ca citat, sau dacă ea cere explicit.

Ce scrii pe `source`, adevărul și atât:

- carte → `„Titlu" — Autor, pagina N`; fără pagină, doar titlul și autorul
- rezumat Bookey → scrii că e rezumat
- internet → `internet — ce ai citit + linkul`
- memorie → `din memorie 🧠 (profil + avatar), fără sursă externă`

`source` arată pasajul pe care l-ai folosit **aici**, nu ce s-a citat în Faza 1.

## Pasul 6 — Focusul

Tema, când e dată. Toate cele cinci variante stau în ea; niciuna nu iese din ea
ca să prindă un unghi mai spectaculos.

Dacă lipsește, tema e unghiul ideii plus profilul. Nu inventezi un focus nou.

## Pasul 7 — scrie

**Cinci variante pentru ideea aleasă**, câte una din fiecare tip de hook, în
ordinea PROVOCARE, CIFRĂ, SECRET, ÎNTREBARE, CONTRAST. Așa cere aplicația, și
la fel faci în conversație. Toate pe același unghi, dar hook-ul și construcția
fiecăreia sunt **realmente diferite** — nu aceeași propoziție rescrisă de cinci
ori. Asta e partea grea, și singura pe care nicio schemă n-o verifică în locul
tău.

**În conversație nu le scrii tu** — le scrie aplicația, prin `develop_idea`
(Pasul 2); regulile de aici rămân metoda după care sunt scrise, pe orice ușă.
Dacă ea a numit deja hook-ul — „a treia, cu un hook întrebare" — tot
`develop_idea` chemi: cele cinci se scriu o singură dată, iar după ce apar
marchezi alegerea ei cu `select_variant`.

### Cele cinci tipuri de hook

- **PROVOCARE** — provoacă direct: o afirmație care deranjează puțin, urmată de
  o invitație.
- **CIFRĂ** — număr concret plus consecință. **Aici e capcana.** Tipul ăsta te
  împinge exact spre ce interzice regula cifrelor: cifra are voie să fie **doar
  numărul de lucruri pe care le enumeri chiar tu în postare** — ✅ „3 semne că
  limitele tale acasă sunt inexistente", ✅ „2 fraze care închid o cerere fără
  discuții lungi". Ce **nu** ai voie, nici măcar prezentat ca experiență
  personală a Viorelei: ❌ „4 reguli care mi-au dat 30% mai mult timp", ❌ „în 7
  zile scapi de vinovăție", ❌ „90% dintre femei fac asta". Procente,
  statistici, studii, cifre de rezultat — dacă nu sunt în profil și nu sunt
  numărul de puncte din propria ta postare, nu există. Numeri conținutul, nu
  rezultatele.
- **SECRET** — dezvăluie ce nu spune nimeni. Nu „secretul pe care nu vi-l spun
  experții" — lucrul adevărat pe care oamenii îl trăiesc și nu-l zic cu voce
  tare.
- **ÎNTREBARE** — întrebare incomodă sau curioasă: una la care ea răspunde în
  gând înainte să apuce să deruleze mai departe.
- **CONTRAST** — înainte față de după, concret în ambele capete: „înainte:
  tremuram când refuzam; după: am început să-mi recuperez energia."

Exact cinci, câte unul din fiecare tip, niciunul repetat. Nu patru, nu șase, și
nu două de același fel.

### Formulările — din manual, verbatim

**Creează-ți propriul (HOOK) cârlig cu aceste întrebări:**

**Ce este un HOOK?**

**Este modalitatea de a capta atentia in primele 3 secunde prin reelsul tau. Cum facem asta?**

* Poți spune clar oamenilor că această informație îi va ajuta să atingă o dorință sau aspirație?
* Poți arăta cum această valoare este direct legată de o problemă sau o dorință cu care se confruntă?
* Poți fi specific în legătură cu modul în care îi va ajuta?

**Exemple de HOOK:**

* Te-ai săturat ca {subiectul} să fie o bătaie de cap? Iată soluția de care ai nevoie.
* Vrei să afli cum să {dorință}?
* Pașii pentru a {dorință}.
* Sătul de {problemă comună în subiect}? Iată soluția care îți va schimba perspectiva.
* Ce să faci dacă {ce își doresc sau nu reușesc să atingă}.
* Ai nevoie de o salvare pentru {subiect/situație}? Asta este pentru tine!
* Ține-te bine, urmează o schimbare pentru {subiect/situație}.
* Oprește-te din scroll dacă vrei să afli adevărul despre {subiect}.
* Plictisit de același {subiect}? Iată o soluție nouă care îți va salva ziua.
* Descoperă secretul pentru a stăpâni {subiectul} cu un truc simplu.
* Cum doar 5 minute pe zi îți pot transforma abordarea pentru {subiect}.
* Copleșit de {subiect}? Asta e pentru tine:
* Simți că ești mereu cu doi pași în urmă cu {subiectul}? Iată strategia care te va ajuta să recuperezi.
* Îți este greu să ții pasul cu {subiectul}? Acest {ceva de exemplu: ghid, strategie} te va salva
* Ești gata să renunți la {subiect}? Asta îți poate schimba părerea.
* Convins că nu vei reuși niciodată să înțelegi {subiectul}? Gândește-te mai bine
* Frustrat de complexitatea {subiectului}? Simplifică-l cu această abordare genială.
* Te simți pierdut în marea de {subiect}? Iată cum poți găsi calea către succes.

Poți scrie ceva care „semnalează” o problemă din industria sau nișa ta? Folosește cuvinte precum „Îmi asum acest lucru”, „Trebuie să înceteze”, „mit”, „minciună”, „schimbare”, „controversă”, „adevăr” etc.

Poți exprima o convingere? Exemple: „Nu voi face niciodată”, „Întotdeauna voi face”, „Nu cred că...”, „Îți garantez că...”.

Poți face o afirmație despre o schimbare? De exemplu: „XYZ s-a schimbat” sau „XYZ nu mai este la fel”.

**Exemple de cârlig:**

● Ok! Îmi asum asta. E timpul să încetăm cu...
● {Subiect} nu mai este la fel ca înainte.
● Am spus-o înainte și o voi spune din nou...
● E timpul să ne luăm rămas bun de la {subiect}. Iată cum.
● Nu cred că oamenii {despre ce? EXEMPLU: vorbesc suficient despre asta, înțeleg}...
● Promit că {promisiune}...
● Greșeala nr. 1 pe care o fac {profesie/identificator} atunci când tratează {subiect}...
● Gata! e suficient. Trebuie să schimbi {ce? EXEMPLU: perspectiva} asupra {subiectului} acum...
● E timpul să admitem că {subiect} nu este ceea ce pare...
● Ține minte: Ignorarea {subiectului} acum va duce la regrete mai târziu. Iată de ce...
● Noutăți: {subiect} revine în forță. E timpul să-i acorzi atenție...
● Spun asta din inimă: {declarație puternică, cum ar fi „nu este {mitul sau percepția oamenilor}”}
● Semnal de alarmă: Am greșit cu toții în privința {subiectului} până acum...
● E timpul să acceptăm adevărul: {subiectul} nu dispare, din contră, devine tot mai relevant...
● Realitate: {subiectul} necesită atenția noastră mai mult ca niciodată...
● Iată adevărul: Nu îți poți permite să ignori {subiectul} niciun moment în plus...
● Adevărul gol-goluț: {subiectul} este schimbarea pe care am ignorat-o până acum...
● Gata cu poveștile... E timpul să abordăm serios {subiectul}...
● Pentru sceptici: {subiectul} nu este ceea ce crezi. Pregătește-te să fii surprins...

[vezi mai multe despre hook-uri aici ](https://drive.google.com/file/d/1neolnKqAgQostCXLZzv4dQ9LV-eWj3kn/view?usp=sharing)

Fiecare variantă completă are:

- **HOOK** — scurt; la Reel, textul de pe ecran din primele două secunde
- **CAPTION** — la Reel **lung, 900–1400 de semne**, fiindcă acolo intră tot ce
  la altcineva ar fi fost spus cu vocea: intră direct în ideea din hook fără
  reintroducere, o desfășoară în 2–4 paragrafe scurte așa cum i-ar povesti unei
  prietene — exemplul concret, ce se întâmplă de fapt, ce poate face ea cu asta
  — și se închide cu întrebarea de engagement. La Carusel și Stories, 2–4 fraze
  scurte, conversaționale, cu aceeași întrebare la final
- **HASHTAGURI** — 3–5, relevante pentru nișă, variate
- **CTA** — cel potrivit din secțiunea 6 a profilului. Dacă la categoria potrivită
  scrie încă `⚠️ DE COMPLETAT`, propui unul;
- **SCRIPT** și blocul de producție — **numai** la Carusel și Stories. La Reel nu
  există

## Pasul 8 — alegerea, și ce urmează după ea

Doar în conversație. Cele cinci variante apar în conversație numerotate după
tipul de hook, iar textul lor complet e în aplicație, pe cardul ideii. Te
oprești și o întrebi pe care o alege. Când numește una — „a doua", „cea cu
contrastul" — marchezi alegerea cu `select_variant`, cu numărul ideii și
tipul de hook: „a doua" e al doilea hook din ordinea afișată. **Nu salvezi
nimic până nu spune „da"** (regula 10). Dacă cere modificări pe cea aleasă, o
rescrii și i-o arăți din nou, de câte ori e nevoie.

Când răspunzi prin contractul aplicației nu arăți nimic, nu ceri aprobare și nu
chemi nicio unealtă: interfața afișează cele cinci și salvează ulterior numai
varianta aleasă de ea.

## Pasul 9 — salvează, o singură dată

Doar în conversație, și numai după „da"-ul ei: `save_post(...)`, cu `title`,
`pillar` și `format` cele alese în Faza 1; `hook` și `hook_type` cele alese de
ea; `caption`, `hashtags`, `cta` exact ce i-ai arătat, nu altă variantă; `script`
doar la Carusel și Stories; `source` ca la Pasul 5.

Îi confirmi scurt că s-a salvat. Atât.

## Încă una din aceeași listă

Dacă după salvare cere altă propunere din cele zece — „acum și a șaptea" — **nu
regenerezi lista.** Cele zece sunt deja în conversație: chemi `develop_idea` cu
7 și mergi mai departe la fel. Dacă chiar nu mai sunt, spui asta și întrebi
dacă facem o listă nouă. Nu inventezi „a șaptea".
