# Setul de evaluare

Gol până la **Decizia 10**. Aici ajung cele douăsprezece cazuri urâte din
[§5 al planului](../plans/digital-fte-plan.md), fiecare cu răspunsul corect scris lângă el —
pasajul fără marcaje de pagină, rezumatul Bookey, tema care intră în conflict cu „Lucruri pe care
nu le spui niciodată", CTA-ul încă necompletat, cele nouă propuneri respinse, și restul.

Plus evals pe deciziile agentului:

- nu scoate propunerile fără toate cele patru răspunsuri;
- nu cheamă `save_postare` fără confirmarea ei;
- poate dezvolta a doua propunere din aceeași listă, fără să regenereze lista.

Plus **trigger evals**: skill-ul pornește din descrierea lui, deci descrierea se testează —
`propune-postari` la „vreau un reel despre limite", `dezvolta-postarea` la „dezvoltă a treia".

E artefactul care face diferența între o felie terminată și o demonstrație.
