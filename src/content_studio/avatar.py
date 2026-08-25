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
their own heading, with the ask attached. Same five sections the metric grades
against - `evals/output/material.py` imports `AVATAR_SECTIONS` from here rather
than keeping its own copy, so what the writer is shown and what the judge looks
for cannot drift apart.
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

#: What the writer is asked to do with the block. Written here, next to the
#: material, because an instruction that lives three thousand tokens away from
#: what it refers to is the arrangement this module exists to undo.
AVATAR_ASK = """Fiecare propunere pleacă de la UN rând anume de mai sus — o frică, o credință
sau o durere scrisă acolo, în cuvintele ei — și îl atinge în situația concretă
în care apare. Nu scrii despre „limite" sau „grija de sine" în general: alegi
rândul, apoi scrii postarea care i-l atinge.

Un text adevărat pentru orice femeie e adevărat pentru niciuna. Dacă nu poți
numi rândul din care ai pornit, propunerea nu e gata."""


def sections_of(profile: str) -> list[str]:
    """The named sections, in order, silently skipping any that moved."""
    found: list[str] = []
    for title in AVATAR_SECTIONS:
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
        "AVATARUL PENTRU CARE SE SCRIE — Andreea, 25–45 de ani. Astea sunt "
        "durerile, fricile și credințele ei, scrise de clientă:\n\n"
        f"{material}\n\n{AVATAR_ASK}"
    )
