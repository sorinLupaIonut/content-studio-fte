"""Where the ruler's material comes from: the repo itself, never a copy.

THE PROBLEM THIS EXISTS TO REMOVE. A metric that carries its own paraphrase of
the method grades the text against a rule the model was never given. Measured
2026-08-25: `metrics.py` held its own three-line definition of Reel/Carusel/
Stories, its own four-line definition of the sources, and its own 900-1400
caption window - none of which appeared anywhere in what the studio actually
tells the model. Three private truths, editable without touching the method, and
the method editable without touching them.

So every piece is read from the one place that owns it:

    the pillars        skills/propune-postari/references/piloni.md
    the sources        skills/propune-postari/references/surse.md
    what a Reel is     generation.SILENT_REEL_BRIEF   <- the prompt itself
    other formats      generation.PRODUCED_BRIEF      <- the prompt itself
    900-1400           parsed OUT of SILENT_REEL_BRIEF
    her pains          content/profile.md, by heading

READ LIVE, NOT FROZEN, and that is the point. Edit `piloni.md` and the metric
follows on the next run; the fingerprint in `ruler.py` notices and makes the
comparison refuse itself until the baseline is re-recorded. Frozen copies would
have been safer and useless: a suite that cannot notice the method changed is
not measuring the method.

NOTHING FALLS BACK. A parse that fails raises, because the failure mode a
default would create is the one worth fearing - the window moves in the prompt,
the metric keeps grading against the old numbers, and the report says the
captions are fine.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from content_studio.avatar import AVATAR_SECTIONS, excerpt
from content_studio.harness.generation import PRODUCED_BRIEF, SILENT_REEL_BRIEF

ROOT = Path(__file__).resolve().parents[2]
PILLARS_FILE = ROOT / "skills" / "propune-postari" / "references" / "piloni.md"
SOURCES_FILE = ROOT / "skills" / "propune-postari" / "references" / "surse.md"
PROFILE_FILE = ROOT / "content" / "profile.md"

#: Re-exported, never redefined. `content_studio.avatar` owns the list, because
#: since 2026-08-25 the WRITER is shown these same sections in its prompt - and a
#: judge hunting for a line in one set of sections while the writer was handed
#: another is the quietest possible way to make a metric unwinnable.
__all__ = ["AVATAR_SECTIONS"]

#: `surse.md` is 4 KB, most of it instructions for calling `search_web` and
#: `search_books` - which a judge reading a finished text cannot use and should
#: not be charged for. Only the opening section defines what each source MEANS,
#: and that is the part `BriefCompliance` needs.
SOURCES_SECTION = "Cele 4 surse de material"

#: The caption window, as told to the model. Written as "900–1400 de\nsemne" -
#: an en dash, and a line break inside the phrase, so both are matched loosely.
CAPTION_WINDOW = re.compile(r"(\d{3,4})\s*[–—-]\s*(\d{3,4})\s+de\s+semne")


class MaterialMissing(RuntimeError):
    """A source of truth moved and the metric would have graded against air."""


def _section(text: str, title: str, level: str) -> str:
    found = re.search(
        rf"^{level}\s+{re.escape(title)}\s*$(.*?)(?=^#{{1,3}}\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if found is None:
        raise MaterialMissing(f"secțiunea «{title}» nu mai există")
    return found.group(1).strip()


@lru_cache(maxsize=1)
def pillars() -> str:
    """The five pillars, in the method's own words."""
    return PILLARS_FILE.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def sources() -> str:
    """What each of the four sources may and may not give."""
    text = SOURCES_FILE.read_text(encoding="utf-8")
    return f"# {SOURCES_SECTION}\n{_section(text, SOURCES_SECTION, '#')}"


@lru_cache(maxsize=1)
def formats() -> str:
    """What the studio tells the model a format is - verbatim, both halves.

    Not a summary of Reel/Carusel/Stories: the exact two blocks the detail
    prompt chooses between. If the judge is to ask "would this look different in
    another format", it has to hold the same definition the writer held.
    """
    return (
        "Ce i se spune modelului despre formate:\n\n"
        f"— Reel (mut, cum filmează ea):\n{SILENT_REEL_BRIEF.strip()}\n\n"
        f"— Carusel și Stories (produse, cu script):\n{PRODUCED_BRIEF.strip()}"
    )


@lru_cache(maxsize=1)
def caption_window() -> tuple[int, int]:
    """The character range, parsed out of the instruction that sets it.

    Raises rather than defaulting. The schema floor and this window agreed only
    from 2026-08-25, when `SILENT_REEL_CAPTION_FLOOR` was raised 200 -> 900; the
    prompt is still the right source, because it carries both ends and the
    schema carries one.
    """
    found = CAPTION_WINDOW.search(SILENT_REEL_BRIEF)
    if found is None:
        raise MaterialMissing(
            "fereastra captionului nu mai e în SILENT_REEL_BRIEF — "
            "CaptionLength nu are ce măsura"
        )
    return int(found.group(1)), int(found.group(2))


@lru_cache(maxsize=1)
def avatar() -> str:
    """Her pains, fears and beliefs, pulled out of the profile by heading.

    Extracted by the app's own function, not by a second parser here: the writer
    is handed exactly this text, so the judge must be handed exactly this text.
    """
    return excerpt(PROFILE_FILE.read_text(encoding="utf-8"))
