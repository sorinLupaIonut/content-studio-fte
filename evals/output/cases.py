"""What the two output metrics are graded on, and the controls that check them.

Three kinds of row, and the third is the reason to believe the first two:

  · `generated` — real variants, read out of `generation_variants` and frozen
    into `cases.json`. The measurement. No expected score: this is the thing
    under test.
  · `her own` — hooks and captions out of `content/corpus/`, which she wrote and
    published. **Expected 1.0.** A metric that fails her own work is measuring
    its own taste, not hers. They were read out of `content/posts/` until
    2026-09-01, when those turned out to be the studio's own output — see
    `CORPUS` below for what that cost.
  · `planted` — fragments written here, each breaking one named rule from her
    profile. **Expected 0.0.** Nine cases that all come out `hers` look the same
    whether the metric works or the judge says yes to anything.

BOTH METRICS ARE ONE QUESTION EACH, PUT TO A JUDGE. There is no rule layer
beside them and there is not going to be one — Sorin's call, 2026-09-01, and the
afternoon before it is the argument. A word list was tried first, built by
reading the „Lucruri pe care nu le spui niciodată” section of her profile, which
says in as many words that she does not use „trebuie”. Measured against her own
published writing before it shipped, and the count held when the real corpus
replaced the fake one: 13 of her 56 captions use „trebuie”, 24 times in all —
„Trăiești o viață
întreagă din «trebuie»” is her subject, not her fault. Four of the five
generated uses were `nu trebuie` — permissive, the opposite of the obligation
she avoids.
Six candidates did survive that measurement, and they were still deleted: six
words is a rule that catches almost nothing while looking like a safety net, and
the judge already catches every one of them with the reason attached. Voice and
idiom are judgements. Ask a judge, and check the judge with controls.
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
from phoenix.evals import LLM

from content_studio.config import (
    CONTENT_DIR,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    EVAL_JUDGE_MODEL,
)

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parent / "reports"
FROZEN = HERE / "cases.json"

#: The two fields the client's wife named, and the two this group grades.
FIELDS = ("hook", "caption")

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

#: Below this a caption is a fragment, not a caption. In her real corpus the two
#: shortest run 117 and 233 characters, so 200 keeps everything she wrote at
#: length and drops the one that is a single line.
OWN_CAPTION_FLOOR = 200


#: HER REAL CORPUS, AND THE REASON IT IS NOT `content/posts/`. Until 2026-09-01
#: the positive controls were read from `content/posts/*.md`, which look like
#: published posts and are not: they carry „## Cele 5 hook-uri (câte unul din
#: fiecare tip)" and „⭐ *(recomandat)*" — they are THE STUDIO'S OWN OUTPUT,
#: saved. Sorin said so, and the files say so on their second heading.
#:
#: EVERY METRIC IN THIS DIRECTORY HAD THEREFORE BEEN VALIDATED AGAINST THE THING
#: IT EXISTS TO GRADE. Worse, a rubric tuned until it ACCEPTS those controls is a
#: rubric taught to accept generated Romanian, which is the opposite of the job.
#: What that cost is written where the conventions were: five rules read off the
#: fake corpus, of which three were exactly backwards. See `CAPTION_CLOSE`.
CORPUS = CONTENT_DIR / "corpus"

#: One example out of a corpus file: a `HOOK:` line, an optional `REVEAL:` line,
#: and the `CAPTION:` that follows. Three parts, not two — the REVEAL is a real
#: slot in her posts and the studio has no field for it, which is its own open
#: question. The reveal is skipped rather than read: nothing grades it yet.
CORPUS_EXAMPLE = re.compile(
    r"^HOOK:\s*(?P<hook>.+?)\s*$.*?^CAPTION:\s*(?P<caption>.+?)\s*$",
    re.M | re.S,
)


#: THE CORPUS IS SPLIT THREE WAYS, AND THE SLICES MUST NOT TOUCH.
#:
#:   · ANCHOR  — shown to the JUDGE as what her writing looks like. Her profile
#:               cannot do this job: it says she promises no „rețete rapide", and
#:               46 of her 56 published captions are numbered lists or points
#:               behind markers. Judged
#:               against the profile alone the metric rejected six of her own
#:               posts for being lists, which is her most common format.
#:   · SPECIMEN — shown to the WRITER, out of her profile. `shown_to_the_writer`.
#:   · CONTROL  — everything left, and the only slice `her_own` returns.
#:
#: A judge shown the text it is about to grade is measuring recall. A writer
#: shown it is being graded on copying. Three disjoint slices is the only
#: arrangement where neither happens, and `test_corpus_slices.py` holds them
#: apart.
ANCHORS_PER_THEME = 2


def _corpus_blocks() -> list[tuple[str, int, str, str]]:
    """(theme, index, hook, caption) for every example in her corpus."""
    out: list[tuple[str, int, str, str]] = []
    for path in sorted(CORPUS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for index, block in enumerate(CORPUS_EXAMPLE.finditer(text), start=1):
            out.append(
                (
                    path.stem,
                    index,
                    block.group("hook").strip(),
                    block.group("caption").strip(),
                )
            )
    return out


def anchor_examples() -> list[tuple[str, str]]:
    """(hook, caption) pairs the judge may see. Never graded."""
    return [
        (hook, caption)
        for theme, index, hook, caption in _corpus_blocks()
        if index <= ANCHORS_PER_THEME
    ]


def anchor_block() -> str:
    """The anchors as one block, ready to interpolate into a rubric."""
    return "\n\n".join(
        f"HOOK: {hook}\nCAPTION: {caption}" for hook, caption in anchor_examples()
    )


def shown_to_the_writer() -> str:
    """The specimen block out of her profile, or empty when she has none.

    DERIVED, NOT LISTED. A hand-kept list of "the posts used as examples" would
    be a second copy of a choice she makes in her profile, and it would stop
    agreeing with it the first time she swaps one. Reading the section is the
    same answer with nothing to maintain.
    """
    from content_studio.voice import specimens

    profile = CONTENT_DIR / "profile.md"
    if not profile.exists():
        return ""
    return specimens(profile.read_text(encoding="utf-8"))


def her_own(limit: int = 8) -> list[Case]:
    """Positive controls: text SHE wrote and published. Expected 1.0.

    Read from disk rather than from Neon, so the controls need no database and
    no server — and so they are the same files a reader can open next to a
    verdict they doubt.

    ANYTHING THE WRITER WAS SHOWN IS NOT A CONTROL. If her profile carries
    specimens, `voice.brief` puts them in the writing prompt, and grading the
    writer on text it was handed measures recall rather than voice — the same
    leak `test_rubrics_do_not_leak.py` guards on the rubric side.
    """
    shown = shown_to_the_writer()
    cases: list[Case] = []
    for theme, index, hook, caption in _corpus_blocks():
        if index <= ANCHORS_PER_THEME:
            continue  # the judge is shown this one; see ANCHORS_PER_THEME
        if shown and caption[:120] in shown:
            continue  # the writer was given this one; see the docstring
        if len(caption) > OWN_CAPTION_FLOOR:
            cases.append(
                Case(
                    case_id=f"own-{theme}-{index}-caption",
                    kind="her own",
                    field="caption",
                    text=caption,
                    expected=1.0,
                    meta={"title": f"{theme} {index}"},
                )
            )
        if hook and hook != "—":
            cases.append(
                Case(
                    case_id=f"own-{theme}-{index}-hook",
                    kind="her own",
                    field="hook",
                    text=hook,
                    expected=1.0,
                    meta={"title": f"{theme} {index}"},
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
#: FLUENT, BUT NOT ARGUABLE — and the difference cost a run to learn. The first
#: `planted-human-1` was „Ia o respirație adâncă. Nu ești singură în această
#: călătorie…”, called a stack of calques. Two different judges read it as
#: natural, and they had a case: that register is ordinary in Romanian self-help
#: writing now. A negative control a competent speaker could defend is not a
#: control, it is a coin — it flipped between two runs of the SAME rubric and
#: judge and took the whole metric to FAIL with it. Its replacement turns on an
#: agreement error („3 pași care te VA ajuta”), which nobody defends.
#:
#: The voice half plants rules from her profile's „Lucruri pe care nu le spui
#: niciodată” and „Tonul tău”. The human half plants what a machine translating
#: into Romanian does: calques, agreement slips, telegraphic lists.
#:
#: ONE FAULT IS DELIBERATELY ABSENT, and it is the one that started this. Real
#: output mixes the legacy cedilla letters `ş`/`ţ` into Romanian that otherwise
#: uses `ș`/`ț` — measured 2026-09-01: 3 of 60 ready variants, one at 8 against
#: 9 inside a single caption, and 0 of her 27 published posts. It was planted
#: here and DeepSeek passed it twice, the second time with the character scan as
#: the literal first instruction in the rubric. That is not a wording problem:
#: `Eşti` and `Ești` are two different tokens, and a judge reads tokens. A
#: control that cannot be met teaches nothing and voids every run, so it is
#: gone — and with it, the studio's only way of catching that fault. Six lines
#: of `str.count` would do it; Sorin declined a rule layer on 2026-09-01, with
#: this cost stated.
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
        "Simți că ești blocată? Iată 3 pași care te va ajuta să te miști "
        "înainte chiar de azi.",
        "an agreement error a native cannot make — „3 pași care te VA ajuta” for "
        "„care te VOR ajuta” — plus „să te miști înainte” for move forward",
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


# ---- the judge ---------------------------------------------------------------


def judge_llm(override: str | None = None) -> tuple[LLM, str]:
    """The grader for both output metrics, and its name for the report.

    `gpt-5-mini`, the same judge as every other group, and it is chosen on
    evidence rather than convenience — the evidence being that the alternative
    was tried properly and lost.

    THE OBJECTION IS REAL: this is the family that WRITES the posts, and a
    grader from the author's own lineage marks its own work. `config.py` names
    DeepSeek for exactly that reason and kept the address through this group's
    absence. It was wired in on 2026-09-01 and measured on the controls, with
    both rubrics de-leaked so the numbers mean generalisation:

        metric   deepseek-chat            gpt-5-mini
        voice    4/4 planted, 16/16 hers  4/4 planted, 15/16 hers
        human    2/4 planted, 15/16 hers  4/4 planted, 14/16 hers

    DeepSeek is the better judge of her VOICE and cannot do `human` at all: it
    passed two planted violations, one of them a caption taken verbatim from a
    real run — it noticed „practică a refuza” was odd, then excused it. An
    independent judge that cannot tell translated Romanian from native is not a
    second opinion, it is a coin.

    So: one judge, and the controls are what stop that being self-congratulation.
    `--judge deepseek` still runs the whole thing through DeepSeek, which is how
    the table above was made and how it should be re-made if either rubric
    changes shape.
    """

    if override in {"deepseek", DEEPSEEK_MODEL} and DEEPSEEK_API_KEY:
        client_kwargs = {"base_url": DEEPSEEK_BASE_URL, "api_key": DEEPSEEK_API_KEY}
        return (
            LLM(
                provider="openai",
                model=DEEPSEEK_MODEL,
                sync_client_kwargs=client_kwargs,
                async_client_kwargs=client_kwargs,
            ),
            DEEPSEEK_MODEL,
        )

    model = override or EVAL_JUDGE_MODEL
    return LLM(provider="openai", model=model), model


# ---- shared plumbing ---------------------------------------------------------


def judge_repeatedly(frame: pd.DataFrame, evaluator, metric: str, times: int):
    """Grade every row `times` times and keep the majority verdict.

    ONE JUDGED PASS IS A SAMPLE, NOT A VERDICT, and this file learned it the
    expensive way. The same rubric and the same judge scored the planted set 4/4
    and then 3/4 on identical input — and because a single missed plant voids
    the whole run, that flip is the difference between a metric that reports and
    a metric that refuses to. The repo already knows this shape: `route/` says
    n=1 per square is a sample too.

    The mean of the 0/1 scores is kept next to the verdict as `agreement`, so a
    row the judge is genuinely torn about (0.5) is visible rather than rounded
    away into a confident-looking answer.
    """

    from phoenix.evals import evaluate_dataframe  # local: keeps the import cost off callers

    runs = [
        unpack(frame, evaluate_dataframe(frame, [evaluator]), metric)
        for _ in range(max(1, times))
    ]
    out = runs[-1].copy()
    if len(runs) == 1:
        out["agreement"] = 1.0
        return out

    scored = pd.DataFrame([run["score"] for run in runs])
    mean = scored.mean(axis=0, skipna=True)
    out["score"] = [None if pd.isna(v) else float(v >= 0.5) for v in mean]
    # 1.0 when every pass agreed, 0.5 when they split evenly.
    out["agreement"] = [
        None if pd.isna(v) else max(v, 1.0 - v) for v in mean
    ]
    return out


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
#: and used 24 times, across 13 of her 56 captions. A control set drawn from real
#: writing carries
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
