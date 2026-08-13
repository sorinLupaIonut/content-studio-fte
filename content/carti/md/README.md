# Bibliotecă — cărți în Markdown

17 cărți convertite în Markdown curat, pentru folosire cu AI (RAG, căutare, citare).

> **Fișierele nu sunt în git.** Sunt volume publicate, sub drept de autor; `.gitignore`
> lasă urmărit doar README-ul ăsta, ca inventarul să fie vizibil fără textul propriu-zis.
> Ele stau local, în `content-studio-vio-2/carti/md/`. Copiază-le aici înainte de Decizia 5
> (spargere în chunk-uri → `documents` + `embeddings` în Neon). După indexare, sursa de
> adevăr pentru căutare e baza de date, nu fișierele — vezi §7, Decizia 5 din plan.

## Convenții

- Fiecare fișier începe cu `# Titlu`, urmat de un bloc `>` cu proveniența și avertismentele.
- `<!-- pagina N -->` marchează începutul paginii N din sursă — folosește-l pentru citări.
- Textul e curățat: anteturi/subsoluri repetate eliminate, numere de pagină scoase,
  cuvinte despărțite în silabe reunite, rândurile hard-wrap unite înapoi în paragrafe.
- Cratimele reale din cuvinte compuse (`self-compassion`) sunt păstrate; cele de despărțire
  în silabe sunt eliminate, arbitrate prin vocabularul propriu al fiecărei cărți.

## Cărți

| Fișier | Titlu | Pagini | Cuvinte | Observații |
|---|---|---:|---:|---|
| [act-for-burnout.md](act-for-burnout.md) | ACT for Burnout — Debbie Sorensen | 311 | 82,084 | PDF cu strat de text |
| [burnout-coach-handbook.md](burnout-coach-handbook.md) | Burnout Coach Handbook — The Priority Academy | 41 | 4,292 | PDF cu strat de text |
| [cand-corpul-spune-nu.md](cand-corpul-spune-nu.md) | Când corpul spune nu. Costul stresului ascuns — Gabor Maté | — | 102,028 | PDF scanat → transcriere OCR-vizuală (AI); fără marcaje de pagină |
| [curajul-de-a-fi-vulnerabil.md](curajul-de-a-fi-vulnerabil.md) | Curajul de a fi vulnerabil — Brené Brown | 152 | 89,754 | PDF scanat → OCR local Tesseract 5.4 (ron, 250 dpi) |
| [curajul-de-a-nu-fi-pe-placul-celorlalti.md](curajul-de-a-nu-fi-pe-placul-celorlalti.md) | Curajul de a nu fi pe placul celorlalți — Ichiro Kishimi & Fumitake Koga | 266 | 58,199 | PDF cu strat de text |
| [darul-imperfectiunii.md](darul-imperfectiunii.md) | Darul imperfecțiunii — Brené Brown | 64 | 43,480 | PDF cu strat de text |
| [granite-in-relatii.md](granite-in-relatii.md) | Granițe în relații — Henry Cloud & John Townsend | 309 | 113,890 | PDF cu strat de text — 9 pagini recuperate față de vechiul extras |
| [inner-critic-workbook.md](inner-critic-workbook.md) | Inner Critic Workbook | 16 | 2,140 | PDF cu strat de text |
| [letting-go-of-self-destructive-behaviors.md](letting-go-of-self-destructive-behaviors.md) | Letting Go of Self-Destructive Behaviors — Lisa Ferentz | 289 | 76,985 | PDF cu strat de text |
| [reinventing-your-life.md](reinventing-your-life.md) | Reinventing Your Life — Jeffrey E. Young & Janet S. Klosko | 381 | 132,529 | PDF scanat → OCR local Tesseract 5.4 (eng, 300 dpi) |
| [self-compassion-skills-workbook.md](self-compassion-skills-workbook.md) | The Self-Compassion Skills Workbook — Tim Desmond | 155 | 34,568 | PDF cu strat de text |
| [self-guided-emdr-workbook.md](self-guided-emdr-workbook.md) | Self-Guided EMDR Therapy Workbook — Katherine Andler | 53 | 9,430 | PDF cu strat de text |
| [set-boundaries-find-peace-rezumat.md](set-boundaries-find-peace-rezumat.md) | Set Boundaries, Find Peace — Nedra Glover Tawwab (rezumat Bookey) | 163 | 17,939 | PDF cu strat de text; ⚠️ **rezumat Bookey, nu cartea integrală** |
| [teoria-let-them.md](teoria-let-them.md) | Teoria „Let Them” — Mel Robbins | 203 | 93,609 | PDF scanat → OCR local Tesseract 5.4 (ron, 300 dpi) |
| [the-body-keeps-the-score.md](the-body-keeps-the-score.md) | The Body Keeps the Score — Bessel van der Kolk | 487 | 171,358 | PDF cu strat de text |
| [the-disease-to-please.md](the-disease-to-please.md) | The Disease to Please. Curing the People-Pleasing Syndrome — Harriet B. Braiker | 313 | 100,542 | PDF cu strat de text — pagini recuperate față de vechiul extras |
| [the-trauma-of-burnout.md](the-trauma-of-burnout.md) | The Trauma of Burnout | 229 | 75,322 | PDF cu strat de text |

**Total: 17 cărți, 1,208,149 cuvinte.**
