"""The fingerprint of the ruler, so a comparison can refuse itself.

A score has two halves - the frozen text and the ruler that measures it - and
only one of them is protected by freezing. The ruler is editable, in eight
places, and none of them left a mark:

    piloni.md            -> BriefCompliance grades old text by a new definition
    surse.md             -> what a source may give, and so what counts invented
    SILENT_REEL_BRIEF    -> both what a Reel is and the caption window
    profile.md           -> AvatarResonance grades text that could not know
    the rubrics          -> all three, silently
    the thresholds       -> what passes, not what scores
    the judge model      -> not ours to control at all
    the case set itself  -> means across different sets are not comparable

Every one of those is a file he edits on purpose, which is the point: the metric
follows the method instead of carrying a copy of it.

WHAT THIS BUYS. Not prevention - the gate must never stop him editing the
method, that is the work. What it buys is that a comparison between two
different rulers REFUSES rather than reports. Green then means one thing only:
same text, same ruler, no worse.

The ritual it creates is the point. Edit `piloni.md`, CI goes red with the
reason, run `report.py --update-baseline`, commit the new `golden.json`. The
ruler change becomes a line in a diff instead of a silent shift under a number
nobody re-read.

WHAT IS NOT HASHED, AND WHY. `AVATAR_SECTIONS` decides WHICH parts of the
profile become `avatar`; it is covered transitively, since changing it changes
the extracted text, which is hashed. A second digest would only ever fire
alongside the first.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from content_studio.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from evals.output import material
from evals.output.metrics import avatar_resonance, brief_compliance, hallucination

#: The three judged metrics are built to be READ here, never called, so the
#: fingerprint reflects the rubric the suite actually runs rather than a copy of
#: it kept in step by hand. GEval accepts a model name as a string and resolves
#: it lazily, so constructing one costs no key and no network - verified
#: 2026-08-25. If a future DeepEval validates the name at construction, this is
#: the line that breaks, and the fix is a real judge here, not a copied rubric.
NEVER_CALLED = "ruler-fingerprint-only"


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _spec(metric: Any) -> str:
    """A judged metric, reduced to everything that can move a score."""
    return json.dumps(
        {
            "name": metric.name,
            "threshold": metric.threshold,
            "params": [str(p) for p in metric.evaluation_params],
            "steps": list(metric.evaluation_steps or []),
            "rubric": [
                [list(band.score_range), band.expected_outcome]
                for band in (metric.rubric or [])
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def ruler_parts(gold: dict[str, Any]) -> dict[str, str]:
    """Every input that can move a score, one digest each.

    Per part rather than one number for the whole thing, because "the ruler
    changed" is not actionable and "piloni changed" is.
    """
    cases = gold.get("cases") or []
    low, high = material.caption_window()
    return {
        # Digested from `material`, which reads the live files - so this fires
        # the moment `piloni.md` or the profile is edited, without waiting for a
        # re-seed. That is the whole reason the material is not frozen.
        "piloni": _digest(material.pillars()),
        "avatar": _digest(material.avatar()),
        "surse": _digest(material.sources()),
        "formate": _digest(material.formats()),
        "caption_window": _digest(f"{low}-{high}"),
        "BriefCompliance": _digest(_spec(brief_compliance(model=NEVER_CALLED))),
        "Hallucination": _digest(_spec(hallucination(model=NEVER_CALLED))),
        "AvatarResonance": _digest(_spec(avatar_resonance(model=NEVER_CALLED))),
        "judge": _digest(f"{DEEPSEEK_MODEL}@{DEEPSEEK_BASE_URL}"),
        # The subject, not the ruler, and it belongs here for the same reason:
        # a mean over fifteen cases and a mean over twenty are two numbers that
        # look comparable and are not. Promotion is supposed to trip this.
        "cases": _digest(
            json.dumps(
                [[c["id"], c["actual_output"], c.get("caption") or ""] for c in cases],
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
    }


def fingerprint(gold: dict[str, Any]) -> dict[str, Any]:
    parts = ruler_parts(gold)
    return {
        "id": _digest(json.dumps(parts, sort_keys=True)),
        "parts": parts,
    }


#: What each part means when it moves, in the words that say what to do about it.
WHY = {
    "piloni": "definițiile pilonilor (skills/.../piloni.md)",
    "avatar": "durerile din profil (content/profile.md, secțiunile pentru avatar)",
    "surse": "ce are și ce n-are voie fiecare sursă (skills/.../surse.md)",
    "formate": "ce i se spune modelului despre format (generation.py)",
    "caption_window": "fereastra captionului (SILENT_REEL_BRIEF)",
    "BriefCompliance": "rubrica sau pragul BriefCompliance",
    "Hallucination": "rubrica sau pragul Hallucination",
    "AvatarResonance": "rubrica sau pragul AvatarResonance",
    "judge": "judecătorul (model sau endpoint)",
    "cases": "setul de cazuri — text înghețat adăugat, scos sau re-sămânțat",
}


def drift(recorded: dict[str, Any] | None, gold: dict[str, Any]) -> list[str]:
    """What moved since the baseline was recorded. Empty means comparable.

    A baseline with no fingerprint at all is drift too, and deliberately so: it
    was recorded before anything watched the ruler, so nothing can vouch for
    which ruler it used.
    """
    now = ruler_parts(gold)
    if not recorded or not recorded.get("parts"):
        return ["referința e dinainte de amprentă — nu se știe cu ce riglă a fost măsurată"]

    was = recorded["parts"]
    moved = [
        f"{WHY.get(name, name)}  [{was.get(name, '—')} → {value}]"
        for name, value in now.items()
        if was.get(name) != value
    ]
    moved += [
        f"{WHY.get(name, name)}  [dispărut din amprentă]"
        for name in was
        if name not in now
    ]
    return moved
