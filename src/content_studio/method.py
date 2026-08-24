"""The method, assembled ahead of the call instead of fetched during it.

WHY THIS EXISTS. Progressive disclosure pays for itself when you do not know
which reference a run will need: the frontmatter description decides whether the
body is loaded, the body decides whether a `references/` file is, and nothing is
in context until something upstream asked for it by name. That is rule 4, and it
is still the right shape for chat, where the next question is unknown.

The structured generation path is not that situation. The form has already
answered every question the skill body would branch on - format, source, pillar -
before a single token is sent. Measured on 2026-08-24: a Reel detail run spent
five model turns, four of which produced no content at all (143 output tokens
between them, each one the name of the next file to open), and every one of those
four re-sent everything accumulated so far. 84,269 input tokens to write 1,537.
The files it fetched were the same four every time, and they were derivable from
the form before the run started.

So on that path the method is assembled here and handed over whole. The skill
body still owns the method, still lives on disk, and is still edited without
touching code - what changes is only when it arrives. `citeste-referinta` stays
attached for the files this module does NOT preload (the production references,
which depend on what she asks rather than on what she picked), so nothing that
used to be reachable becomes unreachable.

CONTRADICTIONS ARE THE FAILURE MODE HERE, not token count. A body that says
"cere structura-reel.md" sitting above the contents of `structura-reel.md` is the
same fault that cost this project 126 KB of unread method once already, pointing
the other way: the model spends a turn asking for what it was already given. So
every preloaded reference has its call block rewritten in the body, and the
rewrite is what `tests/unit/test_method.py` holds.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from content_studio.config import SKILLS_DIR
from content_studio.worker import REFERENCE_TOOL_NAME, parse_skill, reference_index

#: Which references a skill body demands unconditionally - the ones its steps
#: mark "de fiecare dată, înainte să scrii". Keyed by skill name.
#:
#: `propune-postari/surse.md` appears under both skills on purpose: Faza 2 asks
#: for the other phase's reference deliberately, because the rules about what a
#: source may yield matter more when writing the whole text than when writing a
#: title. See `skills/dezvolta-postarea/SKILL.md`, Pasul 5.
ALWAYS: dict[str, tuple[str, ...]] = {
    "propune-postari": (
        "propune-postari/piloni.md",
        "propune-postari/surse.md",
    ),
    "dezvolta-postarea": (
        "dezvolta-postarea/piloni-si-cont.md",
        "propune-postari/surse.md",
        # Sorin's call, 2026-08-24, with the objection on the record: the file
        # is the Brand Legends manual, and four of its ten worked reels are
        # talking-head scripts ("Vorbeste:", "VIDEO CU TINE", "REEL TALKING")
        # while her reels are mute and the Reel contract has no `script` field.
        # It goes in whole anyway. Two things keep the contradiction survivable:
        # `SILENT_REEL_BRIEF` is in the user message, so the mute rule is the
        # LAST thing read before writing, and the four carousels here are the
        # only worked method Carusel has anywhere in the project.
        "dezvolta-postarea/idei.md",
    ),
}

#: What the chosen format adds. Carusel is deliberately empty: its structure is
#: three lines inside SKILL.md and has no file, and inventing one to fill this
#: table would be a method change smuggled in as a cache optimisation.
BY_FORMAT: dict[str, dict[str, tuple[str, ...]]] = {
    "propune-postari": {"Reel": (), "Carusel": (), "Stories": ()},
    "dezvolta-postarea": {
        "Reel": (
            "dezvolta-postarea/structura-reel.md",
            "dezvolta-postarea/hookuri-si-scripturi.md",
            "dezvolta-postarea/b-roll.md",
        ),
        "Stories": ("dezvolta-postarea/stories.md",),
        "Carusel": (),
    },
}

#: What the chosen source adds. Only Faza 1 names `carti.md`; Faza 2 reaches the
#: shelf through `search_books` and never asks for it, so it is not listed there.
#: Preloading a file the body never mentions is tokens with no instruction
#: attached to them.
BY_SOURCE: dict[str, dict[str, tuple[str, ...]]] = {
    "propune-postari": {
        "Cărți": ("propune-postari/carti.md",),
        "Combinat": ("propune-postari/carti.md",),
        "Internet": (),
        "Memorie": (),
    },
    "dezvolta-postarea": {
        "Cărți": (),
        "Combinat": (),
        "Internet": (),
        "Memorie": (),
    },
}

#: The pillar selects nothing, and that is not an omission: one file covers all
#: five pillars, so the set does not change with the choice.

#: A fenced block whose whole content is one `citeste-referinta("key")` call.
#: This is the shape every SKILL.md uses to send the model at a reference, and
#: `tests/unit/test_skill_references.py` already holds that shape.
CALL_BLOCK = re.compile(
    r"```\s*\n" + re.escape(REFERENCE_TOOL_NAME) + r"\(\"(?P<key>[^\"]+)\"\)\s*\n```",
)


def preload_keys(skill: str, format: str, source: str) -> list[str]:
    """Every reference this run will need, in a stable order.

    Stable because these files land in the cached prefix, and an order that
    varied between processes would buy a full prefix re-read on every request
    that happened to land on the other one - the same reason `reference_index`
    sorts.
    """
    keys: list[str] = []
    for group in (
        ALWAYS.get(skill, ()),
        BY_FORMAT.get(skill, {}).get(format, ()),
        BY_SOURCE.get(skill, {}).get(source, ()),
    ):
        for key in group:
            if key not in keys:
                keys.append(key)
    return keys


def _annotate(body: str, keys: Iterable[str]) -> str:
    """Replace the call block of every preloaded reference with a pointer.

    The instruction around the block is left exactly as written - it is the
    method, and it says *why* the file matters. Only the imperative to go and
    fetch it is answered, because it has already been answered.
    """
    preloaded = set(keys)

    def swap(match: re.Match[str]) -> str:
        key = match.group("key")
        if key not in preloaded:
            return match.group(0)
        return f"> Referința `{key}` e deja mai jos, întreagă. Nu o mai ceri."

    return CALL_BLOCK.sub(swap, body)


def method_block(skill: str, format: str, source: str) -> tuple[str, list[str]]:
    """The skill body and its references, as one block. Returns (text, keys).

    The keys come back so the caller can log what a run was actually given -
    without that, "did it get b-roll.md?" becomes a question you answer by
    reading a prompt instead of a record.
    """
    skill_md = SKILLS_DIR / skill / "SKILL.md"
    _, _, body = parse_skill(skill_md)
    index = reference_index()

    keys = [key for key in preload_keys(skill, format, source) if key in index]
    parts = [
        "--- METODA TA, ÎNTREAGĂ ---",
        "Mai jos e metoda pentru exact ce ți se cere: corpul ei, apoi fiecare",
        "referință de care are nevoie. Nu ceri niciuna dintre ele - le ai deja.",
        "O citești și o aplici; un pas sărit e metodă neaplicată.",
        "",
        _annotate(body, keys),
    ]
    for key in keys:
        parts.append(f"\n--- REFERINȚA {key} ---\n")
        # ANNOTATED TOO, not just the skill body. References send each other at
        # references: `propune-postari/surse.md` points at `carti.md`, and with
        # both preloaded the second block was still telling the model to fetch a
        # file printed a few thousand tokens below it. Caught by
        # `tests/unit/test_method.py`, which is why that test walks every shape
        # rather than one.
        parts.append(_annotate(index[key].read_text(encoding="utf-8"), keys))
    return "\n".join(parts), keys
