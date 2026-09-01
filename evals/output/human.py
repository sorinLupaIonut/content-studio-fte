"""Metric `human` — does it read as Romanian written by a person?

    uv run python evals/output/human.py --dry-run   # the rows and the free layer
    uv run python evals/output/human.py             # judges. Costs a few cents.
    uv run python evals/output/human.py --field caption

The other half of what the client's wife said on 2026-09-01. `voice.py` asks
whether the text is HERS; this one asks whether it is anybody's — whether it
reads as Romanian somebody wrote, or as English somebody translated.

The two are genuinely different faults and they are fixed in different places. A
text can be perfectly idiomatic Romanian and still sound like any coach on the
internet (that is `voice`); a text can hit every one of her signature phrases
and still read as machine output (that is this one). Grading them as one number
would say a post is bad without saying which way.

TWO LAYERS, AND THE FREE ONE IS THE MORE CERTAIN.

  · `tells` — deterministic, no model, no cost. Chiefly the CEDILLA MIX: `ţ`
    (U+0163) and `ş` (U+015F) are Turkish letters kept in legacy Romanian
    codepages, while correct Romanian is `ț` (U+021B) and `ș` (U+0219). A
    person typing Romanian produces one of the two, consistently, because their
    keyboard emits one of the two. A model producing both inside one paragraph
    is not making a stylistic choice.

    Measured 2026-09-01 across the 60 ready variants in the database and her 27
    published posts: three generated captions mix them — one at 8 cedilla
    against 9 comma-below — and NONE of hers do. All three were Viorela's, and
    they are the ones her wife was reading. It also catches the non-breaking
    hyphen (U+2011), which no Romanian keyboard has.

  · `human` — the judge, for what no character test can see: calques, agreement
    slips, telegraphic colon-lists, and the closing-flourish aphorism.

WHY THE FREE LAYER IS NOT THE WHOLE METRIC. It is certain but narrow: it proves
a machine touched the text and cannot tell you that „mai puțin oboseală" is
wrong, that „practică a refuza" is not a Romanian construction, or that „Te
întreb din prietenie" is a sentence nobody says. Those need a reader.

THE JUDGE IS gpt-5 BY DEFAULT — see `config.OUTPUT_JUDGE_MODEL`. Asking
`gpt-5-mini` whether this Romanian reads as machine-written is asking it to
fault its own dialect.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from phoenix.evals import LLM, create_classifier, evaluate_dataframe

from content_studio import enable_utf8_output
from content_studio.config import OUTPUT_JUDGE_MODEL

# Same shape `experiment.py` uses to reach across groups: the repo root on the
# path, then the sibling by its full name, so one file owns the cases.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.output.cases import (  # noqa: E402
    cedilla_mix,
    controls_verdict,
    frame_for,
    report,
    unpack,
)

enable_utf8_output()

#: A hyphen no Romanian keyboard produces. It arrives from a model that has read
#: a lot of typeset English, and it survives into the caption she publishes.
NON_BREAKING_HYPHEN = "‑"

JUDGE_PROMPT = """You are reading ONE piece of Romanian text and answering a single
question: was this written by a Romanian speaker, or translated into Romanian?

You are NOT grading whether it is good, whether it is on topic, or whether it
suits its author. Only whether the Romanian is native.

THE FIELD: {field}
A `hook` is one line — the text on screen in the first two seconds of a silent
reel, or a carousel cover. A `caption` is the post itself. A hook is allowed to
be a fragment; that is its form, not a fault.

THE TEXT
{text}

Answer "human" only if ALL of these hold:

1. The grammar is Romanian. Agreement holds (a Romanian writes „mai puțină
   oboseală", never „mai puțin oboseală"), and the constructions are ones the
   language actually uses.
2. No calques. „La sfârșitul zilei", „fii sigură că" for make sure, „moduri
   cheie", „a realiza" in the sense of to realise, „ia-ți înapoi puterea" —
   these are English sentences wearing Romanian words.
3. It is written, not assembled. A person writes in sentences that carry each
   other. A machine writes „Rezultatul:" followed by three nouns, then an
   aphorism with a dash in the middle, then another list.
4. It ends where a person would end it. Not with a bolted-on flourish after the
   closing question, and not with a summary of what was just said.

Answer "translated" if any one of them fails. Quote the phrase that decided it.

Ignore spelling of diacritics: a separate check already handles that, and it is
not your question. Write your reasoning first, then the label on its own.
"""


def free_layer(frame: pd.DataFrame) -> pd.DataFrame:
    """The character tells. No model, no cost, no judgement."""
    out = frame.copy()
    findings: list[str] = []
    clean: list[bool] = []
    for text in out["text"]:
        legacy, correct = cedilla_mix(text)
        notes: list[str] = []
        if legacy and correct:
            notes.append(f"mixes {legacy} legacy cedilla with {correct} comma-below")
        elif legacy:
            notes.append(f"{legacy} legacy cedilla letters (ş/ţ), not Romanian")
        if NON_BREAKING_HYPHEN in text:
            notes.append("non-breaking hyphen (U+2011), absent from any Romanian keyboard")
        findings.append("; ".join(notes))
        clean.append(not notes)
    out["tells"] = findings
    out["tells_ok"] = clean
    return out


def breakdown(measured: pd.DataFrame, metric: str, verb: str) -> None:
    """The measurement, split by field and — when there is one — by tag.

    A tag is what makes a before and an after comparable: both halves are graded
    in the same call, by the same judge, against the same controls, so the only
    thing that differs between the two numbers is the output itself.
    """
    tags = [tag for tag in measured.get("tag", pd.Series(dtype=str)).unique() if tag]
    for field_name in ("hook", "caption"):
        half = measured[measured["field"] == field_name]
        if len(half):
            good = int((half["score"] == 1.0).sum())
            print(f"{metric} {field_name:<10} {good}/{len(half)} {verb}")
    good = int((measured["score"] == 1.0).sum())
    print(f"{metric.upper() + ' TOTAL':<18} {good}/{len(measured)}")

    if len(tags) > 1:
        print()
        for tag in tags:
            part = measured[measured["tag"] == tag]
            good = int((part["score"] == 1.0).sum())
            print(f"  {tag:<26} {good}/{len(part)}")


def show(frame: pd.DataFrame, judged: bool) -> None:
    print(f"\n{'kind':<10} {'field':<8} {'hook type':<11} {'free':<5} {'human':<7} text")
    print("-" * 108)
    for _, row in frame.iterrows():
        free = "ok" if row["tells_ok"] else "TELL"
        verdict = ""
        if judged:
            if row.get("score") is None or pd.isna(row.get("score")):
                verdict = "?"
            else:
                verdict = "human" if row["score"] == 1.0 else "transl."
            if row["expected"] is not None and not pd.isna(row["expected"]):
                verdict += " ✓" if row.get("score") == row["expected"] else " ✗"
        snippet = row["text"][:42].replace("\n", " ")
        print(
            f"{row['kind']:<10} {row['field']:<8} {str(row['hook_type']):<11} "
            f"{free:<5} {verdict:<7} {snippet}…"
        )
    print()

    tells = frame[~frame["tells_ok"]]
    print(f"character tells  {len(frame) - len(tells)}/{len(frame)} clean")
    for _, row in tells.iterrows():
        print(f"    {row['case_id']}: {row['tells']}")

    if not judged:
        print(f"\n{len(frame)} rows would be judged. No judge called, no cost.")
        return

    believable, why = controls_verdict(frame)
    print(f"\ncontrols         {'PASS' if believable else 'FAIL'} — {why}")
    if not believable:
        print("The generated rows below are NOT a result: the metric failed its")
        print("own controls, so a score on unlabelled text cannot be read.")

    measured = frame[frame["kind"] == "generated"]
    breakdown(measured, "human", "read as written by a person")


def main() -> int:
    parser = argparse.ArgumentParser(description="human — is the Romanian native?")
    parser.add_argument("--dry-run", action="store_true", help="the rows, free")
    parser.add_argument("--field", choices=("hook", "caption"), help="only one field")
    parser.add_argument("--no-controls", action="store_true", help="measurement only")
    # Calibrating a rubric means running the controls over and over. Paying for
    # the generated rows each time buys nothing: they carry no expected score,
    # so they cannot tell you whether the change helped.
    parser.add_argument(
        "--controls-only", action="store_true", help="calibrate the rubric, cheaply"
    )
    parser.add_argument("--judge", default=OUTPUT_JUDGE_MODEL, help="the judging model")
    args = parser.parse_args()

    frame = frame_for("human", controls=not args.no_controls, only=args.field)
    if args.controls_only:
        frame = frame[frame["kind"] != "generated"].reset_index(drop=True)
    if not len(frame):
        print("No case. Seed one with: uv run python evals/output/seed.py --write")
        return 1

    frame = free_layer(frame)

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nReport: {report('human', frame, None)}")
        return 0

    evaluator = create_classifier(
        name="human",
        prompt_template=JUDGE_PROMPT,
        llm=LLM(provider="openai", model=args.judge),
        choices={"human": 1.0, "translated": 0.0},
    )
    graded = evaluate_dataframe(frame, [evaluator])
    frame = unpack(frame, graded, "human")

    unreadable = int(frame["score"].isna().sum())
    if unreadable:
        # A verdict that could not be read is not a verdict of zero.
        print(f"\n{unreadable} of {len(frame)} verdicts could not be read.")
        if unreadable == len(frame):
            print("No verdict read — no score reported.")
            return 1

    show(frame, judged=True)
    print(f"\nReport: {report('human', frame, args.judge)}")
    believable, _ = controls_verdict(frame)
    return 0 if believable else 1


if __name__ == "__main__":
    sys.exit(main())
