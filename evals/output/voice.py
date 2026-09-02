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

THE JUDGE IS `EVAL_JUDGE_MODEL`, and the objection to that is real: it is the
family that writes the posts. `config.py` names DeepSeek for exactly that
reason, it was wired in and measured on 2026-09-01, and it judges HER VOICE
better — 16/16 of her own pieces against 15/16. It lost on the other metric, so
both use one judge; see `cases.judge_llm` for the table. `--judge deepseek`
re-runs this through it.

What buys the independence back is the controls, which run every time: if her
own writing fails or a planted violation passes, no score is printed at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from phoenix.evals import create_classifier

from content_studio import enable_utf8_output
from content_studio.config import CONTENT_DIR
from content_studio.voice import excerpt as voice_excerpt

# Same shape `experiment.py` uses to reach across groups: the repo root on the
# path, then the sibling by its full name, so one file owns the cases.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.output.cases import (  # noqa: E402
    anchor_block,
    controls_verdict,
    frame_for,
    judge_llm,
    judge_repeatedly,
    report,
)

enable_utf8_output()

PROFILE = CONTENT_DIR / "profile.md"

#: WHAT IT GRADES AGAINST IS HER WRITING, NOT HER PROFILE, and the difference is
#: the whole repair of 2026-09-01. The profile is her questionnaire — what she
#: believes about her own voice — and it disagrees with her published work in at
#: least three places that have each cost a run: it disowns „trebuie" (13 of 56
#: captions use it), it promises no „rețete rapide" (46 of 56 ARE numbered
#: lists or points behind markers), and it never mentions how she closes. Judged against the profile
#: alone, this metric rejected six of her own posts, five of them for being the
#: format she uses most.
#:
#: So the profile still says WHO she is, and `anchor_block()` shows WHAT she
#: writes: ten real examples, held out of the control set by `cases.py` so the
#: judge is never shown a text it is about to grade. See `ANCHORS_PER_THEME`.
JUDGE_PROMPT = (
    """Here is how one woman describes her own voice, copied from her brand
profile. She is a coach for women in burnout.

{voice}

A PROFILE IS AN INTENTION. Here is what she actually publishes — ten real posts
of hers, as they went out:

{anchor}

Read those before you answer. Where the description above and the writing below
it disagree, THE WRITING WINS: it is what she does, the other is what she meant
to do.

Below is a {field} written FOR her — a `hook` is the one line on screen at the
start of a silent reel or on a carousel cover; a `caption` is the post itself.

{text}

WOULD SHE HAVE WRITTEN THIS?

Do not answer on overall impression, and do not settle for «close enough».
Check, one at a time:

1. Does it treat the reader in a way she never does — promising a result or a
   deadline, using a clinical word, making the reader wrong, pushing?
2. Is there a phrase she would not use — jargon, a slogan, a line that announces
   its own cleverness?
3. If it is a caption: does it end the way hers end — asking for one small,
   named thing? An offer, a private message, or a question with nowhere to put
   the answer are each enough on their own.
4. Is it written from a stage, where she would have written as someone who has
   been through it?

Say "hers" only if none of the four catches. Say "generic" otherwise, and NAME
which one and quote it.

FOUR THINGS THAT ARE NOT REASONS TO SAY GENERIC, each of which has wrongly
condemned her own published writing in an earlier version of this rubric. A
common subject: naming an experience many women share is what a hook is for, and
hers do exactly that. Plain writing: she is not trying to be clever. A numbered
list, or points behind markers: that is one of her regular formats, not a recipe
— look at the examples. And a word her profile disowns, used the way the
examples use it.

Give your reason first, quoting what decided it. Then the label on its own line.
"""
)


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
    parser.add_argument(
        "--judge", help="grade with this OpenAI model instead of the default judge"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="grade every row N times and keep the majority; the judge is stochastic",
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
    # Her real writing, held out of the control set. See `ANCHORS_PER_THEME`.
    frame["anchor"] = anchor_block()

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nReport: {report('voice', frame.drop(columns=['voice', 'anchor']), None)}")
        return 0

    llm, judge_name = judge_llm(args.judge)
    evaluator = create_classifier(
        name="voice",
        prompt_template=JUDGE_PROMPT,
        llm=llm,
        choices={"hers": 1.0, "generic": 0.0},
    )
    print(f"judge: {judge_name}")
    frame = judge_repeatedly(frame, evaluator, "voice", args.repeat)

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
