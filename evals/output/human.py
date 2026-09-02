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

THE JUDGE IS `EVAL_JUDGE_MODEL`, which is the family that writes the posts, and
that objection was taken seriously enough to test. DeepSeek — named in
`config.py` precisely to avoid it — caught 2 of 4 planted violations here, one
of them a caption taken verbatim from a real run: it noticed „practică a
refuza” was odd and then excused it. An independent judge that cannot tell
translated Romanian from native is not a second opinion. `gpt-5-mini` catches
4 of 4, so it judges, and the controls are what keep that honest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from phoenix.evals import create_classifier

from content_studio import enable_utf8_output

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

#: A CHECKLIST, NOT A JUDGEMENT, AND THE NUMBERS ARE WHY. Measured on
#: 2026-09-01 against an Opus reading of 30 real variants, same judge and same
#: texts for all three:
#:
#:   · "does it sound good?", no examples  ....  43%, caught  3 of 20 faults
#:   · the same with five worked examples  ....  67%, caught 11 of 20
#:   · these five checks, no examples       ....  97%, caught 20 of 20
#:
#: The first was charmed by fluency: asked about a caption carrying a missing
#: clitic, it answered „formulare concisă, idiomatică și colocvială". It was
#: reading the whole and forming an impression, which is exactly what a fluent
#: machine text survives.
#:
#: SO THE EXAMPLES WERE NOT WHAT WAS MISSING — the procedure was, and that
#: settles a question this file had open. Sorin asked for no examples; the
#: earlier repair was to add them, and it bought 24 points where naming the
#: KINDS and forcing one pass per kind bought 54. Nothing here quotes a control,
#: so `test_rubrics_do_not_leak.py` has nothing to catch and the metric is
#: measuring rather than remembering.
#:
#: `{anchor}` IS NOT AN EXAMPLE — IT IS THE MEDIUM. The checklist above then
#: failed its own controls, 11 of her 16 published pieces marked „translated",
#: and three of the five rejections opened with a numbered list or a 📌. Counted
#: over the real corpus: 46 of her 56 captions are numbered lists or points
#: behind markers, 44 close by asking for a follow and 32 by asking the reader
#: to save the post. Check 5 named a bolted-on closing line as assembly and
#: check 6 named numbering as the register of a manual — so two of the six were
#: condemning the two commonest habits of everyone who writes on this platform.
#:
#: The repair is the one `voice.py` already carries, and it is the same fix for
#: a different reason. There the anchors say what SHE writes; here they say what
#: the MEDIUM looks like when a person writes it, so that a convention is not
#: read as a machine. The metric stays author-neutral — nothing is graded
#: against their subject or their author, which is the whole difference between
#: this file and `voice.py`.
JUDGE_PROMPT = """Below is Romanian text from a social-media post — a {field}. A `hook` is one line
and may be a fragment; a `caption` is the whole post.

FIRST, WHAT THIS MEDIUM LOOKS LIKE WHEN A PERSON WRITES IT — ten real posts,
published by a Romanian woman on Instagram, copied as they went out:

{anchor}

They are here so that a habit of the platform is not mistaken for a machine.
Read them, then forget who wrote them: nothing below is graded against their
subject, their author or their opinions. They tell you one thing only — what
native Romanian looks like in this format.

NOW THE TEXT TO JUDGE:

{text}

WOULD A ROMANIAN READ THIS AND THINK A PERSON WROTE IT?

Do not answer on overall impression. Confident, flowing Romanian can still carry
one phrase that gives the machine away, and one is enough — a text that reads
well for four sentences and slips in the fifth is not a text a person wrote.

So do not weigh it up. Go through the text phrase by phrase, and check each of
these in turn:

1. A grammar word missing or wrong — a clitic, a reflexive, a negation, the
   wrong case after a verb, an adjective that does not agree with its noun, an
   indicative where the sentence needs an imperative or a subjunctive.
2. An English sentence wearing Romanian words: the thought is English and the
   words were swapped one for one.
3. A word or a pairing of words that Romanian does not use, or uses in another
   sense than the one meant here.
4. A sentence that points at something that is nowhere — a step, a list, an
   item, a number the reader has no way to reach. A caption travels with a reel
   or a carousel, so pointing at what is ON SCREEN is not this fault; pointing
   at «pasul 2» of a list nobody ever wrote is.
5. Writing that was assembled rather than said — a phrase built out of
   labels because nobody chose a verb, a sentence that lists where it should
   say. THE SIGN-OFF IS NOT THIS FAULT: a line tacked on after the piece has
   ended, asking the reader to save the post or to follow, is what every
   account on this platform does, and six of the ten above do it.
6. The register of another medium entirely — an article, a manual, a landing
   page, a school essay — where this is one person talking to one person on
   her phone. Announcing what the text is about to do («în acest articol vom
   vedea») belongs to an article and never to this. A NUMBERED LIST DOES NOT:
   seven of the ten above are numbered lists or points behind markers,
   written by a person, and the numbering is never the fault by itself —
   read the sentences inside it instead.

Answer "translated" if you find one, and QUOTE IT.

ONE TEST DECIDES WHETHER WHAT YOU FOUND COUNTS: would a Romanian STOP at it, or
would they only have written it differently? A better phrasing exists for almost
every sentence ever written, and finding one is not this question. What you are
looking for is what a native would not have produced at all — a form that is
wrong, a word that does not exist, an English sentence in Romanian clothes. If
your reason begins «a native would rather say» and the original is merely
plainer or more roundabout, that is a preference, and the answer is "human".

The one thing that trips people on this test: a translated idiom is usually
GRAMMATICAL. A phrase carried over word for word from English can break no rule
of Romanian at all and still be something no Romanian ever said — the sentence
is well formed and the thought underneath it is not Romanian. That is the fault,
not a preference, and «nothing here is incorrect» is not a reason to pass it.

Answer "human" after going through all six and finding nothing that would stop
a reader.

THREE THINGS THAT NEVER DECIDE THIS, and each one has wrongly condemned her own
published writing in an earlier version of this rubric.

Borrowed English words. The vocabulary of coaching and wellbeing in Romanian is
full of them — they take Romanian articles and endings and stand anywhere in the
sentence, as subject, object or predicate. That is the register, not a calque,
and it is never the fault by itself, however English the term looks.

Doubled pronouns. Romanian REQUIRES the clitic even when the stressed pronoun is
already there — «pe tine te costă», «ție ți-a spus». It is grammar, not
redundancy, and it is one of the surest marks of a native writer. Never call it
a pleonasm.

Spelling, punctuation and diacritics. Plenty of Romanians write without
diacritics entirely; it is never a fault and never decides this.

The conventions of the platform, and only these four: a numbered list, points
behind 📌 or ✔️, an emoji inside a sentence, and a closing line asking the reader
to save the post or to follow. Every one is in the real posts above and a person
wrote all of them.

THIS EXCUSES THE FORMAT AND NEVER THE WORDS. A closing line is still Romanian
and is judged as Romanian like every one above it. A slogan carried over from
English does not become native by standing where a sign-off stands — check 2
applies to the last line exactly as it applies to the first.

Give your reason first, quoting what decided it. Then the label on its own line.
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
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="grade every row N times and keep the majority; the judge is stochastic",
    )
    args = parser.parse_args()

    frame = frame_for("human", controls=not args.no_controls, only=args.field)
    if args.controls_only:
        frame = frame[frame["kind"] != "generated"].reset_index(drop=True)
    if not len(frame):
        print("No case. Seed one with: uv run python evals/output/seed.py --write")
        return 1

    # What the medium looks like when a person writes it, held out of the
    # control set. See `ANCHORS_PER_THEME`.
    frame["anchor"] = anchor_block()

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nReport: {report('human', frame.drop(columns=['anchor']), None)}")
        return 0

    llm, judge_name = judge_llm(args.judge)
    evaluator = create_classifier(
        name="human",
        prompt_template=JUDGE_PROMPT,
        llm=llm,
        choices={"human": 1.0, "translated": 0.0},
    )
    print(f"judge: {judge_name}")
    frame = judge_repeatedly(frame, evaluator, "human", args.repeat)

    unreadable = int(frame["score"].isna().sum())
    if unreadable:
        # A verdict that could not be read is not a verdict of zero.
        print(f"\n{unreadable} of {len(frame)} verdicts could not be read.")
        if unreadable == len(frame):
            print("No verdict read — no score reported.")
            return 1

    show(frame, judged=True)
    print(f"\nReport: {report('human', frame.drop(columns=['anchor']), judge_name)}")
    believable, _ = controls_verdict(frame)
    return 0 if believable else 1


if __name__ == "__main__":
    sys.exit(main())
