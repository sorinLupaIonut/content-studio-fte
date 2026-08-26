"""The other half of the control: text that MUST lose points.

    uv run python -m evals.output.negative

WHY THIS EXISTS. On 2026-08-25 `Hallucination` was repaired against the positive
control - her own published posts - and went 0.72 -> 1.00, ten out of ten. That
number is the shape of two different outcomes. Either the false positives are
gone, or the exceptions were widened until nothing is left to catch. The
positive control cannot tell those apart: it is made entirely of text that
should pass, so a metric that returns 1.00 unconditionally scores perfectly on
it.

So: eight fragments in her voice, each carrying exactly ONE planted violation of
`surse.md`, and four written to sit as close as possible to an exception without
being one. A repair that survives both controls is a repair. One that only
survives the positive one is a metric that stopped measuring.

The pairs are deliberate. "15 minute de mers m-au liniștit" is hers and passes;
"mersul scade cortizolul cu 23%" is a statistic and must not. The distance
between them is the whole definition of the metric, and it is smaller than it
looks.

NOT A GATE either, and for the same reason as `control.py`: it needs a judge,
therefore a key, therefore money. It is run by hand after a rubric is edited.
"""

from __future__ import annotations

import argparse
import sys

from deepeval.test_case import LLMTestCase

from content_studio import enable_utf8_output
from evals.output.control import NO_PASSAGES
from evals.output.judge import judge_or_none
from evals.output.metrics import hallucination

#: Each case is (id, text, must_be_caught). The clean ones are not filler: they
#: are the exceptions stated as text, so a rubric that over-corrects fails here
#: rather than silently in production.
CASES: list[tuple[str, str, bool]] = [
    (
        "statistica-inventata",
        "Nu ești leneșă. Ești epuizată. Studiile arată că 68% dintre femeile "
        "între 25 și 45 de ani trec printr-un episod de burnout nediagnosticat. "
        "Tu în care procent te regăsești?",
        True,
    ),
    (
        "studiu-invocat",
        "O cercetare de la Harvard a demonstrat că oamenii care spun NU de trei "
        "ori pe săptămână au un nivel de cortizol cu o treime mai mic. Deci "
        "refuzul nu e egoism, e fiziologie.",
        True,
    ),
    (
        "citat-atribuit",
        "Gabor Maté scrie în «Când corpul spune NU», la pagina 141: «Boala este "
        "prețul plătit pentru amabilitatea cronică». Îl citesc și mă doare, "
        "pentru că știu exact despre ce vorbește.",
        True,
    ),
    (
        "pret-inventat",
        "Programul meu de 6 săptămâni costă 890 de lei și include patru ședințe "
        "individuale plus un grup de suport. Locurile se închid vineri.",
        True,
    ),
    (
        "cifra-medicala",
        "Cortizolul crescut peste 20 de micrograme îți blochează somnul profund "
        "și de aia te trezești la 3 dimineața. Corpul tău nu e stricat, e doar "
        "în alarmă.",
        True,
    ),
    (
        "curat-numaratoare",
        "5 lucruri care se schimbă când te alegi și pe tine. 1. Diminețile nu "
        "mai încep cu nod în stomac. 2. Nu mai trăiești doar în «trebuie». "
        "3. Spui NU fără să te justifici o oră. 4. Ai timp pentru tine fără să "
        "te simți vinovată. 5. Îți dai voie să fii imperfectă.",
        False,
    ),
    (
        "curat-biografie",
        "Am trecut prin două burnout-uri. Al doilea m-a costat opt luni în care "
        "n-am putut lucra. 15 minute de mers fără căști mi-au liniștit mintea "
        "mai mult decât 3 podcasturi despre calm.",
        False,
    ),
    (
        "curat-exercitiu",
        "Numără azi de câte ori spui «trebuie». Dacă ies peste 10 și niciun "
        "«vreau», ia-ți 10 minute de journaling seara. Chiar și 3 rânduri "
        "contează.",
        False,
    ),
    (
        "curat-ghilimele",
        "Vocea din capul tău spune «mai pot puțin» și tu o crezi de fiecare "
        "dată. Trimite asta unei prietene care face totul pentru toți.",
        False,
    ),
]


def main() -> int:
    enable_utf8_output()
    parser = argparse.ArgumentParser(description="Does the metric still bite?")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    judge = judge_or_none()
    if judge is None:
        print("DEEPSEEK_API_KEY lipsește.", file=sys.stderr)
        return 2

    print(f"MARTOR NEGATIV — {len(CASES)} fragmente cu o singură abatere plantată\n")
    print(f"{'caz':<24}{'trebuie':>10}{'notă':>8}{'verdict':>10}")
    print("-" * 52)

    wrong = 0
    for name, text, must_catch in CASES:
        metric = hallucination(model=judge)
        metric.measure(
            LLMTestCase(name=name, input="", actual_output=text,
                        context=[NO_PASSAGES])
        )
        score = float(metric.score)
        caught = score < metric.threshold
        ok = caught == must_catch
        wrong += not ok
        want = "prins" if must_catch else "curat"
        print(f"{name:<24}{want:>10}{score:>8.2f}{('OK' if ok else 'GREȘIT'):>10}")
        if not ok and not args.quiet:
            print(f"    {(metric.reason or '').strip()[:300]}")

    print()
    if wrong:
        print(f"{wrong} din {len(CASES)} greșite — rubrica nu e bună încă.")
        return 1
    print(f"Toate {len(CASES)} corecte: metrica prinde ce trebuie și iartă restul.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
