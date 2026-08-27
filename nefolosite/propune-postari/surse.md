# Cele 4 surse de material

Viorela alege una, obligatoriu. Profilul nu e în listă pentru că nu e o alegere —
îl ai deja întreg, la orice variantă.

| Alegerea ei | De unde | Ce are voie să dea | Ce NU are voie |
|---|---|---|---|
| 📚 Cărți | biblioteca ei de 17 titluri, prin `search_books` | idee, cadru, citat, cu titlul și autorul | să fie prezentată ca „așa se face"; să i se atribuie ce nu scrie în ea |
| 🌐 Internet | căutare web | unghi, temă de sezon, cifră, studiu, citat — fiecare cu pagina lui | ceva ce nu apare în paginile consultate; diagnostic sau promisiune de vindecare |
| 🧠 Memorie | profilul plus ce știi tu | structură, formulare, exemple de viață obișnuită | orice cifră, studiu, nume sau afirmație dată ca fapt verificat |
| 🔀 Combinat | mai multe de mai sus | ce dă fiecare | regulile fiecăreia se cumulează, nu se anulează |

## Ce funcționează azi

**📚 Cărți, 🌐 Internet și 🧠 Memorie.** La Combinat le folosești numai pe cele
alese explicit de ea. Nu înlocui și nu adăuga tăcut altă sursă.

## Cum cauți pe internet

`search_web(description, limit)`. O chemi numai după ce ea a ales Internet sau
Combinat cu Internet și înainte să scrii propunerile. În `description` pui tema
dată de ea; n-o mai întrebi a doua oară.

Din rezultat iei tot ce servește tema: unghiuri și teme de sezon, dar și
cifre, studii și citate — cu o singură condiție, care nu se negociază: **să
apară chiar în paginile consultate, nu în memoria ta.** Un fapt luat de pe web
intră în postare cu proveniența lui: pagina care l-a dat ajunge pe câmpul
`source`, în forma de mai jos, iar un citat se prezintă ca citat.

Ce rămâne interzis nu ține de web, ci de profil: nu inventezi fapte care nu
apar în rezultat, nu dai diagnostice ori promisiuni de vindecare, și nu treci
peste „Lucruri pe care nu le spui niciodată". Dacă rezultatul nu aduce nimic
concret pe temă, spui asta — nu împrumuți din memorie sub steagul
internetului.

### Checklist înainte să arăți propunerile din Internet

- fiecare cifră, studiu sau citat din propuneri se regăsește în paginile
  consultate — dacă nu-l poți arăta acolo, îl scoți, nu-l îndulcești în „se
  spune că”;
- proveniența e pregătită pentru câmpul `source`; în hook, script și caption
  sursa nu apare (regula 8), cu excepția unui citat prezentat ca citat;
- diagnostic, promisiune de vindecare și ce stă pe lista „Lucruri pe care nu
  le spui niciodată” — afară, indiferent ce scrie pe web.

Dacă unealta întoarce eroare sau `status` nu este `ok`, te oprești și îi spui.
Nu scrii cele zece din memorie, nu pretinzi că ai căutat și nu schimbi sursa
fără răspunsul ei.

`sources` îți dă titlul și URL-ul paginilor. Le păstrezi pentru câmpul `source` al
postării confirmate, în forma `internet — ce ai citit + linkul`. Linkurile nu
apar în hook, script sau caption.

## Cum cauți în cărți

`search_books(description, description_en, titles, limit)`. Caută după înțeles,
deci `description` e o frază, nu cuvinte-cheie, iar `description_en` e aceeași
frază, tradusă de tine în engleză — raftul are cărți în ambele limbi, iar
căutarea le folosește pe amândouă și păstrează ce se potrivește mai bine.

**Fraza aia o ai deja: e tema pe care ți-a dat-o ea, în primul mesaj.** N-o mai
întreba „ce să caut" — pui tema ei în `description`, cu cuvintele ei. Întrebările
sunt trei: format, pilon, sursă. A patra vine la final, când alege propunerea.
Nu inventezi a cincea.

Înainte, îi propui **3–4 titluri anume**, scrise pe nume, potrivite pe tema și
pilonul ei, plus varianta „caut în toate". Titlurile le iei de aici:

```
citeste-referinta("propune-postari/carti.md")
```

Le dai ca listă gata făcută. NU o întreba „vrei să alegem titluri sau caut în
toate?": alegerea ei e între cărți anume, nu între metode. Și niciodată lista
de 17. Dacă alege câteva, le pui în `titles`, scrise exact ca în listă.

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

## Ierarhia, când sursele se contrazic

Treapta mai înaltă câștigă, dar numai când ambele vorbesc despre aceeași
întrebare:

1. profilul Viorelei, inclusiv „Lucruri pe care nu le spui niciodată"
2. metoda Brand Legends — format, structură, filmare
3. cele 17 cărți — sursă de unghi, niciodată de regulă
4. internetul — unghi, actualitate și fapte citate din paginile consultate
5. ce știi tu — structură și formulare, niciodată afirmație

## Sursa se notează

Pe postarea salvată, oricare ar fi alegerea. Dar **doar acolo** — nu în hook, nu
în script, nu în caption (regula 8).

- carte → `„Titlu" — Autor, capitolul N / pagina N`
- internet → `internet — ce ai citit + linkul`
- memorie → `din memorie 🧠 (profil + avatar), fără sursă externă`
- combinat → toate cele folosite
