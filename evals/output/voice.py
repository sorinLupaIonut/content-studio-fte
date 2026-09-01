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

TWO LAYERS, AND THE CHEAP ONE RUNS FIRST.

  · `banned` — free, certain, no judgement. Six words her profile forbids and
    her own 27 published posts never use. The list is short because it was
    measured rather than read: four obvious candidates, „trebuie” among them,
    turned out to be things she does constantly. See `cases.py`.
  · `voice` — the judge, for everything a word list cannot see: whether the
    warmth is hers, whether it teaches without obliging, whether it could have
    been written for any coach with a different name at the bottom.

THE JUDGE IS gpt-5 BY DEFAULT, AND THAT IS THE POINT OF THE METRIC. AGENTS.md
warns that a judge on the writer's own model scores its own phrasing as good,
because it is the phrasing it would have chosen. For a metric whose entire
question is „does this read as written by a person with this voice”, that is not
a caveat, it is the failure mode. `OUTPUT_JUDGE_MODEL` in `config.py` is gpt-5
for this reason; set it to something cheaper only for a smoke test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from phoenix.evals import LLM, create_classifier, evaluate_dataframe

from content_studio import enable_utf8_output
from content_studio.config import CONTENT_DIR, OUTPUT_JUDGE_MODEL
from content_studio.voice import excerpt as voice_excerpt

# Same shape `experiment.py` uses to reach across groups: the repo root on the
# path, then the sibling by its full name, so one file owns the cases.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.output.cases import (  # noqa: E402
    banned_hits,
    controls_verdict,
    frame_for,
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


def free_layer(frame: pd.DataFrame) -> pd.DataFrame:
    """Her never-words, per row. No model, no cost."""
    out = frame.copy()
    hits = [banned_hits(text) for text in out["text"]]
    out["banned"] = ["; ".join(hit) for hit in hits]
    out["banned_ok"] = [not hit for hit in hits]
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
    print(f"\n{'kind':<10} {'field':<8} {'hook type':<11} {'free':<5} {'voice':<6} text")
    print("-" * 108)
    for _, row in frame.iterrows():
        free = "ok" if row["banned_ok"] else "BAN"
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
            f"{free:<5} {verdict:<6} {snippet}…"
        )
    print()

    banned = frame[~frame["banned_ok"]]
    print(f"banned words   {len(frame) - len(banned)}/{len(frame)} clean")
    for _, row in banned.iterrows():
        print(f"    {row['case_id']}: {row['banned']}")

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
    parser.add_argument("--judge", default=OUTPUT_JUDGE_MODEL, help="the judging model")
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
    frame = free_layer(frame)

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nReport: {report('voice', frame.drop(columns=['voice']), None)}")
        return 0

    evaluator = create_classifier(
        name="voice",
        prompt_template=JUDGE_PROMPT,
        llm=LLM(provider="openai", model=args.judge),
        choices={"hers": 1.0, "generic": 0.0},
    )
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
    print(f"\nReport: {report('voice', frame.drop(columns=['voice']), args.judge)}")
    believable, _ = controls_verdict(frame)
    return 0 if believable else 1


if __name__ == "__main__":
    sys.exit(main())
