"""Andreea's pains, fears and beliefs, pulled out of the profile by heading.

WHY THIS EXISTS AS ITS OWN MODULE. The profile reaches the model inside
`source_packet`, JSON-encoded, roughly 31 KB of escaped markdown with the voice
guide, the offer, the pricing and the history in it. The fourteen fears and the
twenty-three beliefs are in there - buried. Measured 2026-08-25 across ten frozen
answers spanning five briefs: `AvatarResonance` scored 0.44 and NOT ONE case
reached its threshold, with the judge saying the same thing ten times - true of
any woman, therefore of none.

That is not the model refusing an instruction. `SKILL.md` does say "scoți din
pilon plus profil: durerile, dorințele și credințele limitative reale", and the
material is genuinely present. It is the same failure the caption had: an
instruction the model cannot act on, because acting on it means finding five
sections inside a wall of JSON while also holding a format, a pillar, a source
and ten distinct angles.

So the sections are lifted out and given their own block in the prompt, under
their own heading, with the ask attached. `AVATAR_SECTIONS` below is the single
list: the grader that used to import it (`evals/output/`) was removed on
2026-08-30, and whatever replaces it imports from here rather than keeping its
own copy - what the writer is shown and what a judge looks for must not drift
apart.
"""

from __future__ import annotations

import re

#: The sections that carry a nameable pain. Named rather than "the whole
#: profile" because both users of this list want a LINE - the writer has to pick
#: one, the judge has to point at it - and adding the voice guide or the pricing
#: only widens what either may point at.
AVATAR_SECTIONS = (
    "Ce își dorește cel mai mult acum?",
    "Ce probleme are în acest moment?",
    "Ce dureri simte?",
    "Fricile ei cele mai puternice",
    "Credințele ei limitative (în cuvintele ei)",
)

#: The same five in a profile that is WRITTEN in English. The studio can be used
#: in English since 2026-08-21, and a profile in English is a legitimate state,
#: not a demo hack - the first one arrived on 2026-08-31.
#:
#: THIS IS WHY IT IS NOT OPTIONAL. `sections_of` skips a title it cannot find
#: and `excerpt` returns "" rather than raising, both on purpose: a restructured
#: profile must not stop the client generating. So an English profile scored
#: 0 of 5 here, the block silently left the prompt, and the only symptom was
#: the failure this module exists to fix - proposals true of any woman.
#: Measured before the fix, on the translated profile: 8,923 characters of
#: material in the Romanian one, 0 in the English one.
AVATAR_SECTIONS_EN = (
    "What does she want most right now?",
    "What problems does she have right now?",
    "What pain does she feel?",
    "Her strongest fears",
    "Her limiting beliefs (in her own words)",
)

#: What the writer is asked to do with the block. Written here, next to the
#: material, because an instruction that lives three thousand tokens away from
#: what it refers to is the arrangement this module exists to undo.
AVATAR_ASK = """Every proposal starts from ONE particular line above — a fear, a belief or a
pain written there, in her own words — and touches it in the concrete situation
where it shows up. You do not write about „limite" or „grija de sine" in
general: you pick the line, then you write the post that touches it.

A text that is true for any woman is true for none. If you cannot name the line
you started from, the proposal is not ready."""


def sections_of(profile: str) -> list[str]:
    """The named sections, in order, silently skipping any that moved."""
    found: list[str] = []
    # Both languages, one pass. A profile is written in one of them, so the
    # other simply finds nothing - which is the behaviour this loop already had
    # for a section that moved.
    for title in (*AVATAR_SECTIONS, *AVATAR_SECTIONS_EN):
        block = re.search(
            rf"^###\s+{re.escape(title)}\s*$(.*?)(?=^###\s|\Z)",
            profile,
            re.MULTILINE | re.DOTALL,
        )
        if block is not None:
            found.append(f"### {title}\n{block.group(1).strip()}")
    return found


def excerpt(profile: str) -> str:
    """The pains as one block, or empty when the profile is not what we think.

    Empty rather than raising: a profile that has been restructured must not
    stop the client generating posts. The prompt drops the block, the run
    proceeds, and `AvatarResonance` is what notices the quality fell.
    """
    return "\n\n".join(sections_of(profile))


def brief(profile: str) -> str:
    """The block plus its instruction, ready to paste into a prompt.

    Returns empty when there is nothing to show, so the caller can interpolate
    it unconditionally without leaving a dangling heading over nothing.
    """
    material = excerpt(profile)
    if not material:
        return ""
    return (
        "THE AVATAR THIS IS WRITTEN FOR — Andreea, 25–45 years old. These are "
        "her pains, fears and beliefs, written by the client:\n\n"
        f"{material}\n\n{AVATAR_ASK}"
    )
