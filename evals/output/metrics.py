"""The four output metrics, and nothing else.

One is arithmetic and three are judgement. The split is the point: a caption is
528 characters or it is not, and paying a model to count them would be the most
expensive way to learn a number.

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
format is, the caption window and her pains all arrive from `material.py`, which
reads them from the files and prompts that own them. A rule this module spelled
out itself would be a rule the model was never given, and grading against it
would measure the distance between two of my own sentences.
"""

from __future__ import annotations

from typing import Any

from deepeval.metrics import BaseMetric, GEval
from deepeval.metrics.g_eval.utils import Rubric
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams

from evals.output import material

#: Only the silent Reel brief states a character range; `PRODUCED_BRIEF` asks
#: for "2-4 fraze" and names no number, so a Carusel or Stories caption has no
#: window to be measured against and is skipped rather than judged by a Reel's.
MEASURED_FORMATS = frozenset({"Reel"})

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


class CaptionLength(BaseMetric):
    """Characters in the caption, against the brief's own range.

    A metric rather than a bare assertion so it lands in the same report as the
    other three: a run where the captions are short and the writing is excellent
    should read as one table, not as a test failure next to a score.

    Ideas have no caption. Those cases are marked skipped rather than passed - a
    metric that quietly returns 1.0 for everything it cannot measure is how a
    suite starts looking green while measuring half of what it claims.
    """

    def __init__(self, window: tuple[int, int] | None = None) -> None:
        # Read from `SILENT_REEL_BRIEF`, which is the sentence the model was
        # given. Raising the floor in the prompt therefore raises the bar here,
        # in the same commit, with no second number to remember.
        self.minimum, self.maximum = window or material.caption_window()
        self.threshold = 1.0
        self.evaluation_model = "determinist"
        self.async_mode = False
        self.include_reason = True
        self.strict_mode = False
        self.skipped = False

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        meta = test_case.metadata or {}
        caption = meta.get("caption")
        if not caption:
            self.skipped = True
            self.score = 1.0
            self.success = True
            self.reason = "Fără caption (idee, nu variantă) — nu se măsoară."
            return self.score

        format = meta.get("format")
        if format not in MEASURED_FORMATS:
            self.skipped = True
            self.score = 1.0
            self.success = True
            self.reason = f"Formatul «{format}» nu are fereastră în metodă."
            return self.score

        length = len(caption)
        self.score = 1.0 if self.minimum <= length <= self.maximum else 0.0
        self.success = self.score == 1.0
        window = f"{self.minimum}–{self.maximum}"
        if self.success:
            self.reason = f"{length} caractere, în intervalul {window}."
        else:
            side = "scurt" if length < self.minimum else "lung"
            self.reason = f"{length} caractere — prea {side} față de {window}."
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *a: Any, **kw: Any) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "CaptionLength"


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
    worth running: refine `piloni.md` or move the caption window in
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
                    "un citat inventat, o pagină inventată, un preț inventat."
                ),
            ),
            Rubric(
                score_range=(4, 6),
                expected_outcome=(
                    "O singură afirmație verificabilă fără temei — de obicei o "
                    "cifră sau o generalizare dată ca statistică."
                ),
            ),
            Rubric(
                score_range=(7, 10),
                expected_outcome=(
                    "Curat: fiecare afirmație verificabilă are temei, iar restul "
                    "e metaforă, poveste sau sfat — care nu se penalizează."
                ),
            ),
        ],
        evaluation_steps=[
            # The "Ce NU are voie" column IS the grounding rule, written by the
            # method per source: Memorie forbids any figure given as fact,
            # Internet forbids figures and studies outright. Restating it here
            # in my own words would have been a second, weaker rule.
            f"Reține ce n-are voie să dea fiecare sursă:\n{material.sources()}",
            "Caută în text fiecare afirmație care s-ar putea verifica și "
            "penalizeaz-o dacă nu are temei în `context`:\n"
            "1. O cifră, un procent sau o statistică date ca fapt.\n"
            "2. Un studiu, o cercetare sau o instituție invocate ca sursă.\n"
            "3. Un citat între ghilimele atribuit cuiva.\n"
            "4. Un număr de pagină, sau o carte din care nu s-a întors niciun "
            "pasaj. O pagină inventată e mai rea decât una lipsă: pare "
            "verificabilă și nu e.\n"
            "5. Un preț, un pachet sau o ofertă concretă.",
            "NU penaliza, în niciun caz: metafora, imaginea poetică, povestea "
            "compusă sau ilustrativă, afirmația generală de coaching («multe "
            "femei simt asta»), sfatul practic, sau numărătoarea propriei "
            "structuri («3 pași» urmată de exact trei pași). Astea sunt meseria, "
            "nu defectul.",
            "Dacă `context` spune că sursa a fost memoria clientei, lipsa "
            "pasajelor nu e o vină în sine — dar o cifră, un studiu sau un citat "
            "rămân invenție și fără pasaje.",
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
