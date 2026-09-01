"""Metric `human` — does it read as Romanian written by a person?

    uv run python evals/output/human.py --dry-run   # the rows it would judge, free
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

ONE QUESTION, PUT TO A JUDGE, and it is deliberately the plain one: DOES IT
SOUND GOOD? Not correct, not on topic, not suited to her — `voice.py` asks that.
Just whether a Romanian reading it would think a person wrote it.

Spelling and diacritics are explicitly out of scope, and that is Sorin's call of
2026-09-01 rather than an oversight. It was tried the other way: a planted
cedilla mix (`ş`/`ţ` for `ș`/`ț`) sat in the controls and the judge passed it
twice, the second time with the character scan as the literal first line of the
rubric. `Eşti` and `Ești` are two tokens and a judge reads tokens. Asking it to
look at characters made the rubric longer and caught nothing.

THE JUDGE IS DEEPSEEK — `config.py` chose it, and the reason is written there:
asking `gpt-5-mini` whether this Romanian reads as machine-written is asking it
to fault its own dialect. Whether DeepSeek can tell native Romanian from
translated is measured every run by the controls, never assumed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from phoenix.evals import create_classifier, evaluate_dataframe

from content_studio import enable_utf8_output

# Same shape `experiment.py` uses to reach across groups: the repo root on the
# path, then the sibling by its full name, so one file owns the cases.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.output.cases import (  # noqa: E402
    controls_verdict,
    frame_for,
    judge_llm,
    report,
    unpack,
)

enable_utf8_output()

#: EVERY EXAMPLE BELOW IS DELIBERATELY *NOT* ONE OF THE CONTROL TEXTS.
#:
#: An earlier version quoted „mai puțin oboseală" — the exact phrase inside
#: `planted-human-4` — and scored 4/4 on the planted set. That is not a metric
#: passing, it is a rubric reciting its own answer key: the judge only had to
#: match a string it had been handed. Stripping the anchors out entirely was
#: tried next and went the other way, 2/4, passing the real production caption.
#:
#: So the faults are named with DIFFERENT specimens of the same kinds. A control
#: that passes now means the judge generalised from „mai mult energie" to „mai
#: puțin oboseală", which is the thing actually being claimed.
JUDGE_PROMPT = """You are reading ONE piece of Romanian social-media copy and answering
one question: DOES IT SOUND GOOD?

Not whether it is correct. Not whether it is on topic. Not whether it suits its
author — a separate metric asks that. Only whether a Romanian reading this would
think "a person wrote this", rather than "this was translated" or "a machine
assembled this".

THE FIELD: {field}
A `hook` is one line — the text on screen in the first two seconds of a silent
reel, or a carousel cover. A `caption` is the post itself. A hook is allowed to
be a fragment; that is its form, not a fault.

THE TEXT
{text}

Answer "human" if it reads naturally: the phrasing is what a Romanian would
actually say, the sentences carry each other, and nothing makes you stop and
re-read because the words sit oddly together.

Answer "translated" if any of these gives it away. The examples are only to show
you the KIND of fault — the text in front of you will have different ones:

1. Agreement or form that slips. „mai mult energie" for „mai multă energie";
   „două zi"; a feminine subject with a masculine adjective.
2. An English expression carried across word for word. „face sens" for it makes
   sense; „aplică pentru" a job; „sunt bun la" for I am good at.
3. A construction Romanian does not use. „a practica ceva" where a person would
   say „a exersa"; an infinitive where the language wants a subjunctive.
4. Assembled rather than written. A colon followed by three bare nouns, an
   aphorism with a dash in the middle, a list where a sentence belonged.
5. It does not stop where a person would stop. A closing flourish bolted on
   after the piece had already ended.

ONE IS ENOUGH. Do not weigh the faults against the fluency and settle on an
average — a caption can flow beautifully for four sentences and still have been
assembled. If you catch yourself writing "slightly unusual", "a bit odd", or "a
Romanian would more likely say", you have already found it: that is the answer,
and the label is "translated". A native writer does not produce phrases their
own readers have to excuse.

Spelling, punctuation and diacritics are NOT the question. Plenty of Romanians
write without diacritics entirely; that is never a fault and never decides this.
Judge how it SOUNDS.

Quote the phrase that decided it, then give the label on its own line.
"""


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
    print(f"\n{'kind':<10} {'field':<8} {'hook type':<11} {'human':<7} text")
    print("-" * 100)
    for _, row in frame.iterrows():
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
            f"{verdict:<7} {snippet}…"
        )
    print()

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
    parser.add_argument(
        "--judge", help="grade with this OpenAI model instead of the default judge"
    )
    args = parser.parse_args()

    frame = frame_for("human", controls=not args.no_controls, only=args.field)
    if args.controls_only:
        frame = frame[frame["kind"] != "generated"].reset_index(drop=True)
    if not len(frame):
        print("No case. Seed one with: uv run python evals/output/seed.py --write")
        return 1

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nReport: {report('human', frame, None)}")
        return 0

    llm, judge_name = judge_llm(args.judge)
    evaluator = create_classifier(
        name="human",
        prompt_template=JUDGE_PROMPT,
        llm=llm,
        choices={"human": 1.0, "translated": 0.0},
    )
    print(f"judge: {judge_name}")
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
    print(f"\nReport: {report('human', frame, judge_name)}")
    believable, _ = controls_verdict(frame)
    return 0 if believable else 1


if __name__ == "__main__":
    sys.exit(main())
