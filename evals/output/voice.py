"""Metric `voice` — does what the studio wrote sound like HER?

    uv run python evals/output/voice.py --dry-run   # the rows and the free layer
    uv run python evals/output/voice.py             # judges. Costs a few cents.
    uv run python evals/output/voice.py --field hook

The client's wife read a hook and a caption on 2026-09-01 and said they did not
sound like Viorela. Nothing in the suite could have caught that: `route/` grades
whether the method was opened, `skill/` whether the search returned material,
`path/` whether ten phrasings converge. A run can pass all three and produce a
post written in nobody's voice.

WHAT „HER VOICE” IS, AND WHERE IT COMES FROM. Not from taste, and not from this
file. Her profile has five sections that describe it — her signature phrases,
the questions she asks, the words she replaces, the things she never says, and
her tone — written by her, in her words. `voice_of()` lifts exactly those and
shows them to the judge. Imported from `content_studio.voice`, never copied:
what the WRITER is shown and what the JUDGE looks for must be the same text, or
this metric grades a specification the studio was never given.

ONE QUESTION, PUT TO A JUDGE. No rule layer beside it — see `cases.py` for the
word list that was tried and measured and deleted, and for why: her own
published posts break four of the ten rules her profile states.

THE JUDGE IS DEEPSEEK, and it is not a cost decision. `config.py` chose it
before this group existed: a grader from the same lineage as the author marks
its own work. Whether it can actually judge Romanian is not assumed — the
controls test it every run, and if her own writing fails or a planted violation
passes, no score is printed at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from phoenix.evals import create_classifier, evaluate_dataframe

from content_studio import enable_utf8_output
from content_studio.config import CONTENT_DIR
from content_studio.voice import excerpt as voice_excerpt

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

PROFILE = CONTENT_DIR / "profile.md"

JUDGE_PROMPT = """You are grading ONE piece of Romanian social-media copy against the
voice of the woman it is written for. She is a coach for women in burnout. This
is not a quality contest and not a grammar check — the only question is whether
SHE could have written this.

HER VOICE, IN HER OWN WORDS — taken from her brand profile:
{voice}

THE FIELD YOU ARE GRADING: {field}
A `hook` is one line: the text on screen in the first two seconds of a silent
reel, or the cover of a carousel. A `caption` is the post itself.

THE TEXT
{text}

Answer "hers" only if ALL of these hold:

1. The stance is hers — beside the reader, never above her. She has been through
   this herself. She encourages, invites and asks; she does not command, blame,
   shame or sell hard.
2. It breaks none of her limits: no promised outcome, no deadline, no clinical
   word, no invented statistic, and it never makes the reader wrong.
3. She would publish it as written. Nothing in it is foreign to her — no phrase,
   no register, no move she would not make.

WHAT IS NOT A FAULT. This is where a careful reader goes wrong, so it is worth
as much of your attention as the three above:

  · A COMMON SUBJECT. Naming an experience thousands of women share is what a
    hook is for. Her own published hooks are ordinary burnout observations —
    „Porți epuizarea ca pe o medalie.”, „Spuneam DA la toată lumea.” What makes
    them hers is the handling: the admission that follows („Știu. Am purtat-o și
    eu.”), the invitation, the question. Judge the handling, not the topic.
  · MISSING SIGNATURE PHRASES. She does not stamp them onto every post, and a
    hook is one line with no room for them. Their absence is not evidence.
  · PLAIN WRITING. She is not trying to be clever, and she writes some hooks
    without diacritics.

The block above is your calibration, and the „Exemple de hook-uri din postările
mele” lines inside it are the standard: a text at that level passes. If your
reasoning would reject one of THOSE, your bar is too high — lower it and answer
again.

Answer "generic" only when something concrete decides it: a phrase, a stance or
a move that is not hers, which you must quote. „It could apply to many coaches”
is not a reason on its own.

Write your reasoning first — quoting what decided it — then the label on its own.
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
    print(f"\n{'kind':<10} {'field':<8} {'hook type':<11} {'voice':<6} text")
    print("-" * 100)
    for _, row in frame.iterrows():
        verdict = ""
        if judged:
            if row.get("score") is None or pd.isna(row.get("score")):
                verdict = "?"
            else:
                verdict = "hers" if row["score"] == 1.0 else "gen."
            if row["expected"] is not None and not pd.isna(row["expected"]):
                agrees = row.get("score") == row["expected"]
                verdict += " ✓" if agrees else " ✗"
        snippet = row["text"][:44].replace("\n", " ")
        print(
            f"{row['kind']:<10} {row['field']:<8} {str(row['hook_type']):<11} "
            f"{verdict:<6} {snippet}…"
        )
    print()

    if not judged:
        print(f"\n{len(frame)} rows would be judged. No judge called, no cost.")
        return

    believable, why = controls_verdict(frame)
    print(f"\ncontrols       {'PASS' if believable else 'FAIL'} — {why}")
    if not believable:
        print("The generated rows below are NOT a result: the metric failed its")
        print("own controls, so a score on unlabelled text cannot be read.")

    measured = frame[frame["kind"] == "generated"]
    breakdown(measured, "voice", "sound like her")


def main() -> int:
    parser = argparse.ArgumentParser(description="voice — does it sound like her?")
    parser.add_argument("--dry-run", action="store_true", help="the rows, free")
    parser.add_argument("--field", choices=("hook", "caption"), help="only one field")
    parser.add_argument("--no-controls", action="store_true", help="measurement only")
    # Calibrating a rubric means running the controls over and over. Paying for
    # the generated rows each time buys nothing: they carry no expected score,
    # so they cannot tell you whether the change helped.
    parser.add_argument(
        "--controls-only", action="store_true", help="calibrate the rubric, cheaply"
    )
    args = parser.parse_args()

    frame = frame_for("voice", controls=not args.no_controls, only=args.field)
    if args.controls_only:
        frame = frame[frame["kind"] != "generated"].reset_index(drop=True)
    if not len(frame):
        print("No case. Seed one with: uv run python evals/output/seed.py --write")
        return 1

    voice = voice_excerpt(PROFILE.read_text(encoding="utf-8"))
    if not voice:
        print("The profile carries none of the voice sections — nothing to grade against.")
        return 1
    frame["voice"] = voice

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nReport: {report('voice', frame.drop(columns=['voice']), None)}")
        return 0

    llm, judge_name = judge_llm()
    evaluator = create_classifier(
        name="voice",
        prompt_template=JUDGE_PROMPT,
        llm=llm,
        choices={"hers": 1.0, "generic": 0.0},
    )
    print(f"judge: {judge_name}")
    graded = evaluate_dataframe(frame, [evaluator])
    frame = unpack(frame, graded, "voice")

    unreadable = int(frame["score"].isna().sum())
    if unreadable:
        # A verdict that could not be read is not a verdict of zero. Same trap
        # `skill/relevance.py` fell into on its first run.
        print(f"\n{unreadable} of {len(frame)} verdicts could not be read.")
        if unreadable == len(frame):
            print("No verdict read — no score reported.")
            return 1

    show(frame, judged=True)
    print(f"\nReport: {report('voice', frame.drop(columns=['voice']), judge_name)}")
    believable, _ = controls_verdict(frame)
    return 0 if believable else 1


if __name__ == "__main__":
    sys.exit(main())
