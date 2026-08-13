# Setul de evaluare

Gol până la **Decizia 10**. Aici ajung cele douăsprezece cazuri urâte din
[§5 al planului](../plans/digital-fte-plan.md), fiecare cu răspunsul corect scris lângă el —
pasajul fără marcaje de pagină, rezumatul Bookey, tema care intră în conflict cu „Lucruri pe care
nu le spui niciodată", CTA-ul încă necompletat, cele nouă propuneri respinse, și restul.

Plus evals pe deciziile orchestratorului:

- nu cheamă `propune_postari` fără toate cele patru răspunsuri;
- nu cheamă `save_postare` fără confirmarea ei;
- poate chema `dezvolta_postarea` a doua oară pe aceeași listă, fără să regenereze propunerile.

Fără trigger evals — orchestratorul cheamă explicit unealta, nu ghicește dintr-o listă de skill-uri.

E artefactul care face diferența între o felie terminată și o demonstrație.
