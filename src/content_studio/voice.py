"""How she writes, pulled out of the profile by heading.

THE SAME FAULT AS `avatar.py`, ONE DOOR DOWN, AND FOUND THE SAME WAY. That module
exists because Andreea's pains were genuinely present in the profile and
genuinely unusable: buried inside 28 KB of escaped markdown in `source_packet`,
they produced proposals true of any woman, therefore of none. The sections were
lifted into their own block and the score moved.

Her VOICE was in exactly the same place and was never lifted. Four sections —
`Vocea ta`, `Expresii pe care le folosești des`, `Lucruri pe care nu le spui
niciodată`, `Tonul tău` — 3,673 characters that say which phrases are hers,
which questions she asks, what she never says, and in what tone. The writer was
shown none of them. It was shown WHO to write for and never HOW SHE SOUNDS.

Found on 2026-09-01, not by an eval: the client's wife read a hook and a caption
in Romanian and said they did not sound like Viorela. Reading the run back
against her profile, the generated caption

  · used „trebuie" twice, against „nu folosesc «trebuie», nu oblig, nu forțez"
  · opened „Îți promit:", against „Ce nu promit: … lucruri pe care nu le pot
    onora"
  · carried none of her seven signature phrases and none of her four reflection
    questions

That is not a model ignoring an instruction. It is a model that was never given
one — the same shape of failure, in the same file, for the same reason.

WHAT THIS IS NOT. It is not a style rule invented here, and this module holds no
opinion about good writing: every line it produces is her own text, read off her
own profile. If she edits the profile, the writer changes with it, which is the
whole point of a method she owns.

`VOICE_SECTIONS` is the single list. `harness/generation.py` shows it to the
writer and `evals/output/voice.py` shows it to the judge — imported from here by
both, never copied, so what is asked for and what is graded cannot drift apart.
"""

from __future__ import annotations

import re

#: The sections that describe how she sounds. Named rather than "the whole
#: profile" for the reason `avatar.py` gives: both users of this list want
#: LINES — the writer has to sound like them, the judge has to point at one —
#: and adding the pricing or the client results only widens what either may
#: point at.
#:
#: `Credințele tale de bază` is deliberately NOT here. It is what she believes,
#: not how she writes; it belongs to the content of a post, and the pillar
#: already carries that.
VOICE_SECTIONS = (
    "Vocea ta",
    "Expresii pe care le folosești des",
    "Lucruri pe care nu le spui niciodată",
    "Tonul tău",
)

#: HER OWN POSTS, AND THEY ARE NOT PART OF `VOICE_SECTIONS`. The four sections
#: above DESCRIBE her voice; this one SHOWS it. A description cannot carry a
#: convention it never mentions, and hers are full of them: 44 of her 56
#: published captions close by asking for a follow, 32 by asking the reader to
#: save the post, and her profile contains neither phrase anywhere. The writer
#: had never seen a finished post of hers, and filled the shape with the only
#: caption shape a model knows — a numbered recipe closing on an offer.
#:
#: KEPT OUT OF `excerpt()` ON PURPOSE, which is why it is a separate name and
#: not a fifth entry above. `excerpt()` is what `evals/output/voice.py` shows
#: the JUDGE, and grading a writer on text it was handed measures copying. The
#: writer gets specimens, the judge gets anchors, and `tests/unit/
#: test_corpus_slices.py` keeps the two sets from overlapping.
SPECIMEN_SECTION = "Postări scrise de tine"
SPECIMEN_SECTION_EN = "Posts you have written"

#: The shape of a closing, counted over her 56 real captions: 44 ask for a
#: follow, 32 to save the post, 46 are numbered lists or points behind markers,
#: and exactly one of them sells anything. The last of those is the one that had to be
#: written down — the skill asks for an engagement question AND a CTA from her
#: price list, so every generated caption ended on an offer.
#:
#: THIS IS THE PRODUCT'S RULE, NOT HERS, and that is why it lives here rather
#: than in her profile: it reaches every client's writer through
#: `generation.CAPTION_SHAPE`, so nothing Viorela-specific may go in it. What is
#: hers is in her profile, and the specimens are how it travels.
CAPTION_CLOSE = (
    "It ends by asking for one small thing and naming it — most often to save "
    "the post, or to follow — and where it asks a question, it asks exactly "
    "one. Never an offer inside the post: no session, no message in private, no "
    "writing someone's lines for them. A numbered list or a set of marked "
    "points is a shape she uses often and is not a fault; what is a fault is a "
    "list of lines for the reader to recite back to someone."
)

#: The same four in a profile WRITTEN in English. Verified on 2026-09-01 against
#: the one English profile in the database — a translated profile is a supported
#: state since 2026-08-21, and `avatar.py` records what it costs to forget that:
#: its block silently rendered empty and the only symptom was the failure it
#: existed to fix.
VOICE_SECTIONS_EN = (
    "Your voice",
    "Expressions you use often",
    "Things you never say",
    "Your tone",
)

#: What the writer is asked to do with the block, written next to the material
#: rather than three thousand tokens away from it.
#:
#: IT ASKS FOR ONE THING AND REFUSES ANOTHER, on purpose. Naming a phrase she
#: uses is the instruction; pasting her signature lines into every post is not —
#: five variants that all end „Nu poți să dai din ce nu ai." would be a
#: different way of sounding like nobody.
VOICE_ASK = """Write in THIS voice. Not a summary of it — in it.

Before you write, take one thing from above and let it shape the piece: a phrase
she actually uses, a question she actually asks, the way she opens a subject.
Do not paste her signature lines into every variant; five posts closing on the
same sentence sound as manufactured as five that sound like nobody.

The „Lucruri pe care nu le spui niciodată" section is a hard limit, not a
preference. She promises no outcome and no deadline, she uses no clinical
words, she does not make the reader wrong, and she does not push.

Write Romanian the way she writes it — as a friend who has been through this,
never as a coach on a stage. If the text would work unchanged in any other
coach's account, it is not hers yet."""


#: What the writer is asked to do with the specimens — READ them, not mine them.
#: The failure this answers is not a missing rule; it is a writer that had never
#: seen a finished post of hers and filled the shape with the only caption shape
#: a model knows: a numbered recipe closing on an offer.
SPECIMEN_ASK = """These are finished posts of hers. Read them before you write, and
notice the SHAPE — where she starts, how much of herself is in it, and how it
ends. Do not reuse their subject and do not lift a sentence out of the body:
what carries over from there is the shape, never the words.

THE LAST LINE IS THE EXCEPTION, and it is the one thing that is the same in
every post she publishes: look at how all of them close — the same invitation,
the same sign-off — and close yours the same way. That much is not borrowing,
it is her signature."""


def _section(profile: str, title: str) -> str | None:
    """One `###` section's body, or None when the profile does not carry it."""
    block = re.search(
        rf"^###\s+{re.escape(title)}\s*$(.*?)(?=^###\s|\Z)",
        profile,
        re.MULTILINE | re.DOTALL,
    )
    return block.group(1).strip() if block is not None else None


def sections_of(profile: str) -> list[str]:
    """The named sections, in order, silently skipping any that moved."""
    found: list[str] = []
    # Both languages, one pass: a profile is written in one of them, so the
    # other simply finds nothing.
    for title in (*VOICE_SECTIONS, *VOICE_SECTIONS_EN):
        body = _section(profile, title)
        if body is not None:
            found.append(f"### {title}\n{body}")
    return found


def specimens(profile: str) -> str:
    """Her own published posts, as written, or empty when she has none there.

    Empty is a supported state, not a defect: a client who has not put finished
    posts in her profile gets the description alone, exactly as before this
    existed. It must never fall back to another client's writing — the reason
    this reads the profile, which is already per-client, and not the files under
    `content/posts/`, which are hers alone.
    """
    for title in (SPECIMEN_SECTION, SPECIMEN_SECTION_EN):
        body = _section(profile, title)
        if body:
            return body
    return ""


def excerpt(profile: str) -> str:
    """Her voice as one block, or empty when the profile is not what we think.

    Empty rather than raising, for the reason `avatar.excerpt` is: a profile she
    has restructured must not stop her generating posts. The prompt drops the
    block and the run proceeds — and `evals/output/voice.py` is what notices the
    writing stopped sounding like her.
    """
    return "\n\n".join(sections_of(profile))


def brief(profile: str) -> str:
    """The block plus its instruction, ready to paste into a prompt.

    Returns empty when there is nothing to show, so the caller can interpolate
    it unconditionally without leaving a dangling heading over nothing.
    """
    material = excerpt(profile)
    shown = specimens(profile)
    if not material and not shown:
        return ""
    parts: list[str] = []
    if material:
        parts.append(
            "HOW SHE WRITES — her voice, her phrases and her limits, in her own "
            "words, copied from her brand profile:\n\n"
            f"{material}\n\n{VOICE_ASK}"
        )
    if shown:
        parts.append(
            "AND HERE IS WHAT A FINISHED POST OF HERS LOOKS LIKE — published, "
            "whole, unedited:\n\n"
            f"{shown}\n\n{SPECIMEN_ASK}"
        )
    return "\n\n".join(parts)
