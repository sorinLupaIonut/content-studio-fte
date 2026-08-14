# Cele 4 surse de material

Viorela alege una, obligatoriu. Profilul nu e în listă pentru că nu e o alegere —
îl ai deja întreg, la orice variantă.

| Alegerea ei | De unde | Ce are voie să dea | Ce NU are voie |
|---|---|---|---|
| 📚 Cărți | biblioteca ei de 17 titluri, prin `cauta_in_carti` | idee, cadru, citat, cu titlul și autorul | să fie prezentată ca „așa se face"; să i se atribuie ce nu scrie în ea |
| 🌐 Internet | căutare web | unghi, temă de sezon, ce se discută acum | cifre, studii, citate — nimic de pe internet nu intră ca fapt |
| 🧠 Memorie | profilul plus ce știi tu | structură, formulare, exemple de viață obișnuită | orice cifră, studiu, nume sau afirmație dată ca fapt verificat |
| 🔀 Combinat | mai multe de mai sus | ce dă fiecare | regulile fiecăreia se cumulează, nu se anulează |

## Ce funcționează azi

**📚 Cărți și 🧠 Memorie.** Căutarea pe internet încă nu există.

Dacă alege Internet: **spune-i pe față** că unealta aia nu e gata și întreab-o
dacă mergem pe cărți, pe memorie, sau așteptăm. La Combinat, la fel, dar doar
pentru partea de internet.

Nu înlocui tăcut sursa aleasă de ea. E regula 9, și e cel mai ușor de încălcat
tocmai aici — pare mai util să generezi ceva decât să spui că nu poți.

## Cum cauți în cărți

`cauta_in_carti(descriere, titluri, limit)`. Caută după înțeles, deci `descriere`
e o frază, nu cuvinte-cheie.

**Fraza aia o ai deja: e tema pe care ți-a dat-o ea, în primul mesaj.** N-o mai
întreba „ce să caut" — pui tema ei în `descriere`, cu cuvintele ei. Întrebările
sunt trei: format, pilon, sursă. A patra vine la final, când alege propunerea.
Nu inventezi a cincea.

Înainte, îi propui **3–4 titluri anume**, scrise pe nume, potrivite pe tema și
pilonul ei — le iei din `references/carti.md` — plus varianta „caut în toate".

Le dai ca listă gata făcută. NU o întreba „vrei să alegem titluri sau caut în
toate?": alegerea ei e între cărți anume, nu între metode. Și niciodată lista
de 17. Dacă alege câteva, le pui în `titluri`, scrise exact ca în listă.

Ce întorc pasajele, și ce faci cu ele:

- **`pagina`** → o folosești la `sursa`. Dacă lipsește, scrii titlul și autorul,
  atât. Nu inventezi un număr de pagină, și nu-l ghicești din capitol.
- **`este_rezumat: true`** → e un rezumat Bookey, nu cartea. Scrii asta la sursă.
  Dacă ea cere un citat propriu-zis, nu-l lua de acolo — propune altă carte.
- **`scor`** → cât de aproape e de ce ai cerut. Pe cărțile astea, potrivirile
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
4. internetul — unghi și actualitate, niciodată fapt
5. ce știi tu — structură și formulare, niciodată afirmație

## Sursa se notează

Pe postarea salvată, oricare ar fi alegerea. Dar **doar acolo** — nu în hook, nu
în script, nu în caption (regula 8).

- carte → `„Titlu" — Autor, capitolul N / pagina N`
- internet → `internet — ce ai citit + linkul`
- memorie → `din memorie 🧠 (profil + avatar), fără sursă externă`
- combinat → toate cele folosite
