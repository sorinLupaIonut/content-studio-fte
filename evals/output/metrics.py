"""The three output metrics, and nothing else.

ALL THREE ARE JUDGEMENT. There was a fourth, `CaptionLength`, and removing it on
2026-08-25 is the point of this paragraph. It counted characters against the
window in `SILENT_REEL_BRIEF` and it was never wrong about the count - it was
wrong about being a metric. The caption length is already enforced where it can
actually be enforced: `SILENT_REEL_CAPTION_FLOOR` is a schema `minLength`, and
OpenAI holds it WHILE the model writes. Measured the same day, the first batch
under a floor of 650 produced 650, 658, 661, 665, 679 - five out of five inside
the window, with no judge involved and no retry spent.

A gate that re-checks a constraint the decoder already satisfied has one
possible verdict, and it spent a line of the report and a row of the baseline to
reach it. Worse, it went red on frozen cases generated under an older floor -
history, not regression. What remains here is the part no schema can hold.

THE MATERIAL LIVES IN `evaluation_steps`, NOT IN `criteria`, and that is not a
style choice. `GEval` uses `criteria` ONLY to generate steps when none are
given; supply both and the criteria are dropped in silence. Measured on
2026-08-25 with the profile in `criteria`: AvatarResonance scored exactly 0.00
on all fifteen cases, because the judge was asked to find a line in a profile it
had never been shown. Every reference the judge needs is therefore a step.

EVERY JUDGED METRIC MUST QUOTE. Each rubric ends by demanding the offending
fragment verbatim, and says an unquotable penalty does not count. That is what
turns "0.62" from a verdict into evidence - you read the fragment the judge
pulled out instead of trusting the number.

HIGHER IS ALWAYS BETTER, including for `Hallucination`. GEval's own template
tells the judge that a high score means the output MEETS the rubric, so an
"amount of invention" score with a low ceiling would fight the framework.

WHY GEval AND NOT THE BUILT-IN METRICS. `HallucinationMetric` and
`AnswerRelevancyMetric` carry English rubrics written for factual Q&A. Her posts
are Romanian creative prose against a form, so the built-ins would score the
genre rather than the work: a metaphor is not a false claim, and a brief is not
a question. `GEval` takes her own words from the method and the profile.

NOT ONE WORD OF THE METHOD IS RESTATED HERE. The pillars, the sources, what a
format is and her pains all arrive from `material.py`, which reads them from
the files and prompts that own them. A rule this module spelled
out itself would be a rule the model was never given, and grading against it
would measure the distance between two of my own sentences.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.metrics.g_eval.utils import Rubric
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

from evals.output import material

# THE SCALE IS GEval's, NOT OURS, and writing our own cost a whole run. Without
# a `rubric` the score range is (0, 10) and the returned number is divided by ten
# before it reaches `metric.score`. Rubrics that said "notează de la 0 la 1"
# therefore produced 0.1 for a verdict the judge's own reason called "a specific
# match" - measured 2026-08-25, AvatarResonance mean 0.04 with the reasoning
# entirely correct underneath. Every `Rubric` band below is on GEval's own scale,
# and no rubric text names a scale of its own.

#: The step every judged metric ends with. Written once so the three cannot
#: drift apart on the one rule that makes them auditable.
QUOTE_RULE = (
    "OBLIGATORIU: pentru fiecare penalizare, citează textual fragmentul vinovat "
    "din text, între ghilimele, în motivare. O penalizare pe care nu o poți "
    "susține cu un citat nu se aplică — în lipsa citatului, nu scădea nota."
)

#: The judge answers in whatever language the surrounding template is written in
#: unless told otherwise, so half a report arrives in English and half in
#: Romanian. A report read by the person who owns the method should be in one
#: language, and this is the cheapest place to decide which.
ROMANIAN_REASON = "Scrie motivarea în română, cu diacritice."


def brief_compliance(
    pillars: str | None = None, *, model: DeepEvalBaseLLM | str
) -> GEval:
    """Did the brief SHAPE the text, or merely appear in it?

    The distinction is the whole metric, and the client's own words for it: a
    post that says "în acest reel despre focus" has mentioned the brief and
    obeyed none of it. So the rubric is counterfactual - would this text look
    different if the pillar, the format or the source had been another? If not,
    the brief was decoration.

    All three definitions - pillar, format, source - are read from the files and
    prompts that own them, never restated here. That is what makes the metric
    worth running: refine `piloni.md` or rewrite what a Reel is in
    `SILENT_REEL_BRIEF` and the judge grades against the new rule on the next
    run, while `ruler.py` notices and forces the baseline to be re-recorded.
    """
    pillars = material.pillars() if pillars is None else pillars
    return GEval(
        name="BriefCompliance",
        model=model,
        threshold=0.7,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(
                score_range=(0, 3),
                expected_outcome=(
                    "Briefingul a fost decor. Același text ar merge la fel de "
                    "bine sub oricare alt pilon, format sau sursă."
                ),
            ),
            Rubric(
                score_range=(4, 6),
                expected_outcome=(
                    "Unul dintre cele trei se vede în text; celelalte două nu. "
                    "Sau focusul e pomenit, dar nu e subiectul."
                ),
            ),
            Rubric(
                score_range=(7, 10),
                expected_outcome=(
                    "Pilonul, formatul și sursa se văd toate trei în cum e scris "
                    "textul, iar focusul e subiectul lui propriu-zis."
                ),
            ),
        ],
        evaluation_steps=[
            "Citește briefingul din `input`: pilonul, formatul, sursa, focusul.",
            "Reține definițiile pilonilor — vocabular închis, nu inventa al "
            f"șaselea:\n{pillars}",
            f"Reține ce înseamnă formatul — exact ce i s-a spus și "
            f"scriitorului:\n{material.formats()}",
            f"Reține ce înseamnă sursa, din metoda ei:\n{material.sources()}",
            "ÎNTREBAREA CENTRALĂ NU e dacă acele cuvinte apar în text. E dacă "
            "textul ar fi arătat ALTFEL cu alt pilon, alt format sau altă sursă. "
            "Pune-ți-o pe rând pentru fiecare dintre cele trei.",
            "Verifică focusul: e subiectul propriu-zis al textului, sau doar un "
            "cuvânt pomenit în treacăt? Pomenit în treacăt e o penalizare.",
            "Nu nota lungimea, gramatica sau cât de frumos sună — alea se "
            "măsoară în altă parte.",
            QUOTE_RULE,
            ROMANIAN_REASON,
        ],
    )


def hallucination(*, model: DeepEvalBaseLLM | str) -> GEval:
    """Facts asserted as verifiable, with nothing behind them.

    Deliberately narrow. Coaching prose invents by design - a metaphor, a
    composite story, a general claim about people are the craft, not a defect.
    What is a defect is the shape that LOOKS checkable and is not: a figure, a
    study, a quotation, a page, a price. The built-in `HallucinationMetric`
    cannot make that distinction and would flag the genre.

    THE EXEMPTIONS COME FIRST, and that ordering was bought with a measurement.
    On 2026-08-25 the positive control - the same judge over ten posts the client
    wrote and published herself - scored her 0.72 against the model's 0.78. A
    metric that ranks the author of the method below the machine imitating her is
    not strict, it is wrong. Three of her four penalties were the same mistake
    in three costumes:

        "6 lucruri care NU te scot din burnout"  -> read as an invented figure,
            though the post then lists six. The exemption existed, as the second
            half of the fourth step, below a numbered list of five ways to lose
            points. It was outvoted by its own position.
        "două burnout-uri"                       -> read as an unverifiable
            statistic, about her own life, which she is the witness to. `surse.md`
            grants Memorie "exemple de viață obișnuită" in as many words.
        "Trimite asta unei prietene…"            -> the CTA, in quotation marks
            because it is CTA text, read as a quote attributed to the friend.
            Nobody was named. Quotation marks are not an attribution.

    So the exceptions are a step of their own, placed BEFORE the penalty list -
    GEval walks the steps in order - and each is stated as the shape it forgives
    rather than as an aside. They also appear in the top band, because the band
    is what the judge reads at the moment it picks a number.

    WHAT WAS NOT SOFTENED. Her two Gabor Maté posts quote the book verbatim and
    still score low. That is the metric working: the control assumes `Memorie`,
    and under Memorie the method forbids exactly that - "orice cifră, studiu,
    nume sau afirmație dată ca fapt verificat". She had read the book; the run
    had not. Under `Cărți`, with the passage in `context`, the same text passes.
    """
    return GEval(
        name="Hallucination",
        model=model,
        threshold=0.7,
        evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.CONTEXT],
        rubric=[
            Rubric(
                score_range=(0, 3),
                expected_outcome=(
                    "Mai multe afirmații verificabile fără temei, sau una gravă: "
                    "vorbe puse în gura unei surse NUMITE, o pagină inventată, "
                    "un preț inventat."
                ),
            ),
            Rubric(
                score_range=(4, 6),
                expected_outcome=(
                    "O singură afirmație verificabilă fără temei — de obicei o "
                    "cifră despre lume sau despre alți oameni, dată ca statistică."
                ),
            ),
            Rubric(
                score_range=(7, 10),
                expected_outcome=(
                    "Curat: fiecare afirmație verificabilă are temei, iar restul "
                    "e metaforă, poveste sau sfat — care nu se penalizează. Tot "
                    "aici stau, fără excepție: numărătoarea propriei structuri, "
                    "biografia autoarei la persoana întâi și ghilimelele fără "
                    "sursă numită."
                ),
            ),
        ],
        evaluation_steps=[
            # The "Ce NU are voie" column IS the grounding rule, written by the
            # method per source: Memorie forbids any figure given as fact,
            # Internet forbids figures and studies outright. Restating it here
            # in my own words would have been a second, weaker rule.
            f"Reține ce n-are voie să dea fiecare sursă:\n{material.sources()}",
            # Before the list, not after it. See the docstring: as the tail of a
            # later step, this lost to the numbered list three times out of four
            # on text the client wrote herself.
            "ÎNAINTE de orice penalizare, treci fragmentul prin cele cinci "
            "excepții. Dacă intră într-una, NU e halucinație și nu scade nota. "
            "MAJORITATEA CIFRELOR dintr-o postare intră aici — nu orice cifră e "
            "o statistică:\n"
            "A. NUMĂRĂTOAREA PROPRIEI STRUCTURI. O cifră care spune câte lucruri "
            "urmează chiar în textul ăsta — «6 lucruri care nu te ajută», «5 "
            "lucruri care se schimbă», «3 pași» — se verifică NUMĂRÂND ÎN TEXT, "
            "nu în lume. Numără efectiv: dacă textul livrează atâtea, cifra e "
            "adevărată prin construcție și nu se penalizează. Lista poate fi mai "
            "jos, în caption sau în slide-uri — caut-o înainte să penalizezi.\n"
            "B. AUTOAREA E MARTORA, CIFRELE EI CU TOT. O afirmație la persoana "
            "întâi despre viața ei are drept temei chiar faptul că ea o scrie: "
            "«am trecut prin două burnout-uri», «15 minute de mers m-au liniștit "
            "mai mult decât 3 podcasturi», «anul trecut am renunțat». Cifra din "
            "propria experiență nu devine statistică fiindcă e cifră. Metoda îi "
            "dă voie, din Memorie, la «exemple de viață obișnuită».\n"
            "C. GHILIMELELE NU ÎNSEAMNĂ ATRIBUIRE. Un citat se penalizează numai "
            "când textul NUMEȘTE sursa — un om, o carte, o instituție — și îi "
            "pune vorbele în gură. Ghilimelele puse pe un îndemn sau pe textul de "
            "CTA, pe vocea interioară, pe o replică ilustrativă sau pe un titlu "
            "nu atribuie nimănui nimic. Fără nume, fără penalizare.\n"
            "D. EXERCIȚIUL DAT CITITOAREI. O cifră dintr-o instrucțiune, un prag "
            "sau o ipoteză adresată ei — «numără de câte ori spui azi trebuie; "
            "dacă ies peste 10, citește caption-ul», «ia-ți 5 minute» — nu "
            "afirmă nimic despre lume. E o sarcină, nu o măsurătoare. Tot aici "
            "intră DOZA dintr-un sfat: «10 minute de journaling», «o plimbare de "
            "un sfert de oră», «chiar și 3 rânduri contează». Cifra spune cât se "
            "propune, nu ce s-a măsurat.\n"
            "E. MESERIA. Metafora, imaginea poetică, povestea compusă sau "
            "ilustrativă, afirmația generală de coaching («multe femei simt "
            "asta») și sfatul practic.",
            "Abia acum caută ce se penalizează — afirmații verificabile fără "
            "temei în `context`:\n"
            "1. O cifră, un procent sau o statistică despre lume sau despre alți "
            "oameni, date ca fapt — și care nu a trecut prin A, B sau D.\n"
            "2. Un studiu, o cercetare sau o instituție invocate ca sursă.\n"
            "3. Vorbe puse în gura unei surse numite — un om, o carte, un "
            "specialist — fără pasaj în `context`.\n"
            "4. Un număr de pagină, sau o carte din care nu s-a întors niciun "
            "pasaj. O pagină inventată e mai rea decât una lipsă: pare "
            "verificabilă și nu e.\n"
            "5. Un preț, un pachet sau o ofertă concretă.",
            "Dacă `context` spune că sursa a fost memoria clientei, lipsa "
            "pasajelor nu e o vină în sine — dar o cifră despre lume, un studiu "
            "sau vorbele unei surse numite rămân invenție și fără pasaje.",
            QUOTE_RULE,
            ROMANIAN_REASON,
        ],
    )


def avatar_resonance(
    avatar: str | None = None, *, model: DeepEvalBaseLLM | str
) -> GEval:
    """Did it land on one of Andreea's actual pains, or on nobody's?

    The failure this exists to catch is generic coaching content: warm, true,
    plausible, and interchangeable with any other coach's post. No schema
    catches it, and it is the likeliest thing a model produces when it has a
    pillar and a format and no one in particular in mind.

    The profile makes it gradable rather than vague, because the pains are
    enumerated there - fourteen fears, twenty-three beliefs in her own words. So
    the judge is not asked "is this relevant", it is asked to NAME the line.
    """
    avatar = material.avatar() if avatar is None else avatar
    return GEval(
        name="AvatarResonance",
        model=model,
        threshold=0.7,
        evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(
                score_range=(0, 3),
                expected_outcome="Nu atinge lumea Andreei deloc.",
            ),
            Rubric(
                score_range=(4, 6),
                expected_outcome=(
                    "Adevărat pentru orice femeie, deci pentru niciuna: «ai grijă "
                    "de tine», «pune-ți limite», «meriți mai mult». Cald, "
                    "plauzibil și interschimbabil cu postarea oricărui alt coach. "
                    "Aici stă și orice text pentru care nu poți numi rândul din "
                    "profil, oricât de bine e scris."
                ),
            ),
            Rubric(
                score_range=(7, 10),
                expected_outcome=(
                    "Atinge o frică, o credință sau o durere ANUME din profil, în "
                    "situația ei concretă. Poți numi rândul și citezi ambele "
                    "fragmente — fraza din text și rândul din profil."
                ),
            ),
        ],
        evaluation_steps=[
            "Andreea e avatarul pentru care se scriu postările: femeie de 25–45 "
            "de ani. Mai jos sunt durerile, fricile și credințele ei limitative, "
            "scrise de clientă. Citește-le înainte de orice.\n\n"
            f"{avatar}",
            "Citește textul și întreabă-te: despre cine e, concret?",
            "Caută efectiv în profilul de mai sus rândul — frica, credința sau "
            "durerea — pe care textul îl atinge. Caută-l, nu presupune că există.",
            "Ca să treci în banda de sus trebuie să poți NUMI rândul din profil. "
            "Dacă nu-l poți numi, textul e generic, oricât de bine e scris.",
            "Nu nota lungimea, formatul, gramatica sau cât de frumos sună.",
            "OBLIGATORIU: citează în motivare DOUĂ fragmente — fraza din text și "
            "rândul din profil pe care îl atinge.",
            ROMANIAN_REASON,
        ],
    )
