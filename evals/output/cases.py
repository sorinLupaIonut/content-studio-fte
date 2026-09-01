"""What the two output metrics are graded on, and the controls that check them.

Three kinds of row, and the third is the reason to believe the first two:

  · `generated` — real variants, read out of `generation_variants` and frozen
    into `cases.json`. The measurement. No expected score: this is the thing
    under test.
  · `her own` — hooks and captions out of `content/posts/`, which she wrote and
    published. **Expected 1.0.** A metric that fails her own work is measuring
    its own taste, not hers.
  · `planted` — fragments written here, each breaking one named rule from her
    profile. **Expected 0.0.** Nine cases that all come out `hers` look the same
    whether the metric works or the judge says yes to anything.

THE CONTROLS ARE NOT DECORATION, and this file has already been paid for once.
The first draft of `voice.py` carried a word list — the „Lucruri pe care nu le
spui niciodată” section of her profile says in as many words that she does not
use „trebuie”. Measured against her own 27 published posts before it shipped:

    trebuie       11/27 of her posts     UNUSABLE
    problemă       2/27                  UNUSABLE
    peste noapte   2/27                  UNUSABLE
    percentages    3/27                  UNUSABLE
    pacient        0/27                  safe
    diagnostic     0/27                  safe
    boală          0/27                  safe
    garantez       0/27                  safe
    promit         0/27                  safe
    rețetă         0/27                  safe

One of her posts is titled „trebuie vs vreau”. Four of the five generated uses
were `nu trebuie` — permissive, the opposite of the obligation she avoids. A
banned-word list built by reading her profile and not measuring it would have
flagged her best work and called that a finding. What survived that measurement
is `BANNED` below; everything else is a question for a judge, which is why there
is a judge.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from content_studio.config import CONTENT_DIR

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parent / "reports"
FROZEN = HERE / "cases.json"
POSTS = CONTENT_DIR / "posts"

#: The two fields the client's wife named, and the two this group grades.
FIELDS = ("hook", "caption")

#: Words her profile forbids AND her own published posts never use. The second
#: half of that sentence is what makes the list usable — see the module
#: docstring for the ten that were tested and the four that did not survive.
#: She is a coach, not a doctor, and she promises no outcomes.
BANNED: dict[str, str] = {
    r"\bpacien[tț]": "„pacient” — she is a coach, not a clinician",
    r"\bdiagnostic": "„diagnostic” — outside her expertise, by her own rule",
    r"\bboal[ăa]\b|\bboli\b": "„boală” — medical framing she never uses",
    r"\bgarant(ez|ăm|ez[- ]|ia|ie)": "a guarantee — she promises no outcomes",
    r"\bpromit\b": "„promit” — she promises nothing she cannot honour",
    r"\bre[țt]et[ăa]\b": "a „rețetă” — she refuses quick recipes explicitly",
}

#: Romanian written with the LEGACY cedilla letters instead of the comma-below
#: ones. Objective, not a matter of taste: `ţ` (U+0163) and `ş` (U+015F) are the
#: Turkish letters, kept in old Romanian codepages; correct Romanian is `ț`
#: (U+021B) and `ș` (U+0219). Nobody typing Romanian produces both in one
#: paragraph.
#:
#: Measured 2026-09-01 over the 60 ready variants in the database and her 27
#: published posts: 3 generated variants mix the two — one of them 8 cedilla
#: against 9 comma inside a single caption — and NONE of her own posts do. All
#: three were hers, and they are the ones her wife was reading.
CEDILLA = "ţŢşŞ"
COMMA_BELOW = "țȚșȘ"


@dataclass
class Case:
    """One piece of text to grade, with what is known about it."""

    case_id: str
    kind: str
    field: str
    text: str
    expected: float | None = None
    plants: str = ""
    meta: dict[str, Any] = dataclass_field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "field": self.field,
            "text": self.text,
            "expected": self.expected,
            "plants": self.plants,
            "chars": len(self.text),
            **{
                key: self.meta.get(key, "")
                for key in (
                    "format", "pillar", "source", "hook_type", "model", "title", "tag"
                )
            },
        }


# ---- the measurement ---------------------------------------------------------


def generated() -> list[Case]:
    """The frozen variants. Re-seed with `seed.py`; never edited by hand."""
    if not FROZEN.exists():
        return []
    payload = json.loads(FROZEN.read_text(encoding="utf-8"))
    cases: list[Case] = []
    for item in payload["variants"]:
        for field_name in FIELDS:
            text = (item.get(field_name) or "").strip()
            if not text:
                continue
            cases.append(
                Case(
                    case_id=f"{item['id']}-{field_name}",
                    kind="generated",
                    field=field_name,
                    text=text,
                    meta=item,
                )
            )
    return cases


# ---- control 1: her own published writing ------------------------------------

#: The caption block of one of her posts: `## Caption` to the next heading.
OWN_CAPTION = re.compile(r"^##\s+Caption\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)

#: A hook line in one of her posts. She writes them under the hook type, quoted,
#: and TWO details of the real files each cost a silent miss before this matched
#: anything:
#:
#:   · the colon is INSIDE the bold — `**PROVOCARE:** „…`, 62 of them across the
#:     27 files, never `**PROVOCARE**:`
#:   · the quote OPENS with „ (U+201E) and CLOSES with a plain ASCII `"`. She
#:     types the Romanian opener and lets the editor close it.
#:
#: Both versions returned zero hooks and printed a clean report over it, which
#: is the same failure this whole group exists to catch: the hook half of both
#: metrics had no positive control, so nothing would have objected if the judge
#: called every hook she ever wrote generic.
OWN_HOOK = re.compile(
    r"\*\*(?:PROVOCARE|CIFR[ĂA]|SECRET|[ÎI]NTREBARE|CONTRAST)[:\s]*\*\*"
    r"[^„]{0,40}„([^”\"]+)[”\"]"
)

#: Below this a caption is a fragment, not a caption. Her shortest published one
#: runs 261 characters; 200 keeps that and drops the stray one-line blocks.
OWN_CAPTION_FLOOR = 200


def her_own(limit: int = 8) -> list[Case]:
    """Positive controls: text she wrote and published. Expected 1.0.

    Read from disk rather than from `posts` in Neon, so the controls need no
    database and no server — and so they are the same files a reader can open
    next to a verdict they doubt.
    """
    cases: list[Case] = []
    for path in sorted(POSTS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        caption = OWN_CAPTION.search(text)
        if caption:
            body = caption.group(1).strip()
            if len(body) > OWN_CAPTION_FLOOR:
                cases.append(
                    Case(
                        case_id=f"own-{path.stem}-caption",
                        kind="her own",
                        field="caption",
                        text=body,
                        expected=1.0,
                        meta={"title": path.stem},
                    )
                )
        hook = OWN_HOOK.search(text)
        if hook:
            cases.append(
                Case(
                    case_id=f"own-{path.stem}-hook",
                    kind="her own",
                    field="hook",
                    text=hook.group(1).strip(),
                    expected=1.0,
                    meta={"title": path.stem},
                )
            )
    by_field: dict[str, list[Case]] = {"hook": [], "caption": []}
    for case in cases:
        by_field[case.field].append(case)
    return by_field["hook"][:limit] + by_field["caption"][:limit]


# ---- control 2: planted violations -------------------------------------------

#: Each fragment breaks ONE named rule, and the rule is written next to it. They
#: are deliberately fluent: a negative control that is obviously broken tests
#: nothing, because a judge that only catches gibberish would pass it too.
#:
#: The voice half plants rules from her profile's „Lucruri pe care nu le spui
#: niciodată” and „Tonul tău”. The human half plants what a machine translating
#: into Romanian does: calques, agreement slips, and the cedilla mix measured on
#: real output.
PLANTED_VOICE: list[tuple[str, str, str]] = [
    (
        "hook",
        "Îți garantez că în 7 zile scapi complet de vinovăție. Fără efort.",
        "a guaranteed outcome on a deadline — she promises nothing she cannot honour",
    ),
    (
        "hook",
        "90% dintre femei fac aceeași greșeală. Tu ești una dintre ele.",
        "an invented statistic, plus blaming the reader — her tone is never accusing",
    ),
    (
        "caption",
        "Hai să fim serioase: dacă tot amâni, e vina ta și atât. Nimeni nu vine "
        "să te salveze. Am construit un sistem care funcționează pentru oricine "
        "are curajul să-l aplice, iar rezultatele apar peste noapte dacă te ții "
        "de el. Cine nu reușește, pur și simplu nu a vrut destul. Eu am reușit, "
        "deci poți și tu — fără scuze. Intră în programul meu și hai să "
        "terminăm cu poveștile. Locurile sunt limitate și prețul crește vineri.",
        "aggressive empowerment, blame, scarcity selling and overnight results — "
        "four tones her profile rules out by name",
    ),
    (
        "caption",
        "Din experiența mea clinică, majoritatea pacientelor cu acest diagnostic "
        "răspund bine la protocolul standard. Boala se manifestă prin oboseală "
        "cronică, iar tratamentul recomandat durează între patru și șase "
        "săptămâni. Îți recomand să urmezi rețeta de mai jos exact cum e "
        "scrisă, fără abateri, și să revii la control după prima lună.",
        "clinical register — pacientă, diagnostic, boală, rețetă — all outside her "
        "expertise by her own rule",
    ),
]

PLANTED_HUMAN: list[tuple[str, str, str]] = [
    (
        "hook",
        "Eşti obosită de a fi mereu persoana care rezolvă totul pentru toţi?",
        "cedilla mix (ş/ţ), plus „de a fi” — an English gerund carried straight across",
    ),
    (
        "hook",
        "Ia-ți înapoi puterea ta și fă diferența în viața ta astăzi!",
        "a stack of calques — take back your power, make a difference, today",
    ),
    (
        "caption",
        "În acest articol vom explora trei moduri cheie în care poţi să îţi "
        "îmbunătăţeşti graniţele. Primul, este important să realizezi că "
        "granițele sunt despre tine. Al doilea, nu uita să comunici nevoile "
        "tale în mod clar și consistent. Al treilea, fii sigură că îți iei "
        "timpul de care ai nevoie. La sfârșitul zilei, mai puțin stres și mai "
        "multă claritate este ceea ce contează. Sper că ai găsit acest conținut "
        "valoros!",
        "translationese — moduri cheie, a realiza for to realize, fii sigură for "
        "make sure, la sfârșitul zilei — plus the cedilla mix and an agreement slip",
    ),
    (
        "caption",
        "Rezultatul: mai puțin oboseală, mai multă claritate, proiecte care mă "
        "umplu. Diferența nu e doar stare — e sens. Un exercițiu simplu: "
        "notează azi 3 lucruri pentru tine. Observă cum se schimbă starea ta "
        "când îți acorzi acel spațiu — relaxare, claritate, speranță. Apoi "
        "practică a refuza o cerere mică cu o frază scurtă. Îți promit: replica "
        "scurtă nu distruge relațiile. Le redefinește, în bine.",
        "the real shape, kept from a run on 2026-09-01: „mai puțin oboseală” for "
        "„mai puțină”, „practică a refuza” for „exersează să refuzi”, telegraphic "
        "colon-lists, and an aphorism bolted on after the closing question",
    ),
]


def planted(which: str) -> list[Case]:
    """Negative controls for one metric. Expected 0.0."""
    source = PLANTED_VOICE if which == "voice" else PLANTED_HUMAN
    return [
        Case(
            case_id=f"planted-{which}-{index}",
            kind="planted",
            field=field_name,
            text=text,
            expected=0.0,
            plants=why,
        )
        for index, (field_name, text, why) in enumerate(source, start=1)
    ]


def frame_for(
    which: str, controls: bool = True, only: str | None = None
) -> pd.DataFrame:
    """Every row one metric grades, measurement and controls together."""
    cases = generated()
    if controls:
        cases = cases + her_own() + planted(which)
    if only:
        cases = [case for case in cases if case.field == only]
    return pd.DataFrame([case.row() for case in cases])


# ---- the deterministic layer -------------------------------------------------


def banned_hits(text: str) -> list[str]:
    """Which of her never-words this text uses. Free, and never a judgement."""
    return [why for pattern, why in BANNED.items() if re.search(pattern, text, re.I)]


def cedilla_mix(text: str) -> tuple[int, int]:
    """(legacy cedilla letters, correct comma-below letters) in this text."""
    return (
        sum(text.count(char) for char in CEDILLA),
        sum(text.count(char) for char in COMMA_BELOW),
    )


# ---- shared plumbing ---------------------------------------------------------


def unpack(frame: pd.DataFrame, graded: pd.DataFrame, metric: str) -> pd.DataFrame:
    """The judge's verdicts, off the column `evaluate_dataframe` writes.

    That column holds a JSON-serialized `Score`, not a float — comparing it to
    1.0 is False on every row, which reads as a clean zero and is not one. Same
    trap `skill/relevance.py` documents; the unpacking is the same shape.
    """
    verdicts = graded.get(f"{metric}_score")
    labels: list[str | None] = []
    scores: list[float | None] = []
    why: list[str] = []
    for raw in verdicts if verdicts is not None else [None] * len(frame):
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict):
            labels.append(None)
            scores.append(None)
            why.append("")
            continue
        labels.append(payload.get("label"))
        scores.append(payload.get("score"))
        why.append(payload.get("explanation") or "")
    out = frame.copy()
    out["label"] = labels
    out["score"] = scores
    out["explanation"] = why
    return out


#: How much of her own published writing a metric must accept before its
#: verdicts on unlabelled text can be read at all.
#:
#: NOT 100%, AND THE REASON IS EVIDENCE RATHER THAN CONVENIENCE. The bar was
#: every control, and `voice` met it at 14 of 16 on 2026-09-01 with all four
#: planted violations caught. The two it refused were both reasoned correctly:
#:
#:   · „Nu-ți mai spune nimeni asta: dacă rădăcina e people pleasing…” — an
#:     insider/guru opening, and „people pleasing” is exactly the jargon her
#:     profile says she avoids.
#:   · „…am crezut că problema era că nu mă organizez…” — her profile says in as
#:     many words: „Cuvinte pe care le înlocuiesc: spun «situație» în loc de
#:     «problemă».”
#:
#: Her stated voice and her published corpus DIVERGE, and this is the second
#: time measuring found it — the first was „trebuie”, forbidden in the profile
#: and used 21 times in her posts. A control set drawn from real writing carries
#: real exceptions, so a metric tuned until it accepts every one of them is a
#: metric tuned to stop objecting.
#:
#: The asymmetry is the load-bearing part, not the number. A planted violation
#: that passes means the metric is blind to the thing it exists to catch, and
#: one is enough to void the run. A piece of hers that fails means the judge is
#: stricter than her practice, which is a difference of degree.
#:
#: READ THE RATE, NOT THE VERDICT. 0.80 is a floor under obvious breakage; the
#: signal is a DROP from whatever the last run recorded, which the report keeps.
OWN_CONTROL_FLOOR = 0.80


def controls_verdict(frame: pd.DataFrame) -> tuple[bool, str]:
    """Whether the metric may be believed at all, and why not when it may not.

    A metric is only as good as its controls: if a planted violation passes, or
    her own writing fails wholesale, the numbers on the generated rows mean
    nothing and must not be read as a result.
    """
    known = frame[frame["expected"].notna() & frame["score"].notna()]
    if not len(known):
        return False, "no control was scored — nothing validates this metric"

    plants = known[known["kind"] == "planted"]
    hers = known[known["kind"] == "her own"]
    caught = int((plants["score"] == plants["expected"]).sum())
    accepted = int((hers["score"] == hers["expected"]).sum())
    rate = accepted / len(hers) if len(hers) else 1.0
    summary = (
        f"planted {caught}/{len(plants)} caught, "
        f"her own {accepted}/{len(hers)} accepted ({rate:.0%})"
    )

    if len(plants) and caught < len(plants):
        return False, f"{summary} — a planted violation passed, so the metric is blind"
    if rate < OWN_CONTROL_FLOOR:
        return False, f"{summary} — below the {OWN_CONTROL_FLOOR:.0%} floor on her own work"
    return True, summary


def report(name: str, frame: pd.DataFrame, judge: str | None) -> Path:
    """The evidence of one moment, next to every other group's."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    out = REPORTS / f"{name}-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "judge": judge,
                "cases": len(frame),
                "findings": json.loads(frame.to_json(orient="records")),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out
