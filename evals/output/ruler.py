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

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from deepeval.models.base_model import DeepEvalBaseLLM

from content_studio.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from evals.output import material
from evals.output.metrics import avatar_resonance, brief_compliance, hallucination


class NeverCalled(DeepEvalBaseLLM):
    """A judge that exists only to be read, and refuses to be used.

    The three judged metrics are BUILT here so the fingerprint reflects the
    rubric the suite actually runs rather than a copy kept in step by hand.
    Building one needs a model argument, and a plain string was the obvious
    choice until a clean CI checkout proved otherwise: DeepEval resolves a
    string through `initialize_model`, which constructs an `OpenAIModel`, which
    demands `OPENAI_API_KEY` at construction. On a machine with a `.env` that
    passes; in CI it raised during COLLECTION, so the free deterministic layer
    never ran either. Measured 2026-08-25 against a bare clone.

    Raising in `generate` rather than returning something is the second half:
    if a refactor ever routes real grading through this object, it must fail
    loudly instead of quietly scoring everything the same.
    """

    def __init__(self) -> None:
        super().__init__("ruler-fingerprint-only")

    def load_model(self) -> None:
        return None

    def get_model_name(self) -> str:
        return "ruler-fingerprint-only"

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("NeverCalled exists for the fingerprint, not for grading")

    async def a_generate(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("NeverCalled exists for the fingerprint, not for grading")


NEVER_CALLED = NeverCalled()

ROOT = Path(__file__).resolve().parents[2]


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
    return {
        # Digested from `material`, which reads the live files - so this fires
        # the moment `piloni.md` or the profile is edited, without waiting for a
        # re-seed. That is the whole reason the material is not frozen.
        "piloni": _digest(material.pillars()),
        "avatar": _digest(material.avatar()),
        "surse": _digest(material.sources()),
        "formate": _digest(material.formats()),
        "BriefCompliance": _digest(_spec(brief_compliance(model=NEVER_CALLED))),
        "Hallucination": _digest(_spec(hallucination(model=NEVER_CALLED))),
        "AvatarResonance": _digest(_spec(avatar_resonance(model=NEVER_CALLED))),
        "judge": _digest(f"{DEEPSEEK_MODEL}@{DEEPSEEK_BASE_URL}"),
        # The subject, not the ruler, and it belongs here for the same reason:
        # a mean over fifteen cases and a mean over twenty are two numbers that
        # look comparable and are not. Promotion is supposed to trip this.
        "cases": _digest(
            json.dumps(
                [
                    [
                        c["id"],
                        c["actual_output"],
                        c.get("caption") or "",
                        # The grounding is part of the subject: the same answer
                        # judged with passages and without is two measurements.
                        c.get("context") or [],
                    ]
                    for c in cases
                ],
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
    "BriefCompliance": "rubrica sau pragul BriefCompliance",
    "Hallucination": "rubrica sau pragul Hallucination",
    "AvatarResonance": "rubrica sau pragul AvatarResonance",
    "judge": "judecătorul (model sau endpoint)",
    "cases": "setul de cazuri — text înghețat adăugat, scos sau re-sămânțat",
}


#: The eval stack itself, and the frozen set it grades.
OWN_FILES = ("evals/output/*.py", "evals/output/golden.json")


def watched_files() -> list[str]:
    """Every file whose edit can move a score, repo-relative and DERIVED.

    Not a list somebody maintains. The material files come from `material.py`'s
    own constants, and the modules come from `sys.modules` after importing this
    one - so `SILENT_REEL_BRIEF` living in `generation.py` and `DEEPSEEK_MODEL`
    living in `config.py` are found rather than remembered.

    This is what CI triggers on. A hand-written path list drifts from the ruler
    the first time a reference moves, and drifts SILENTLY: the gate simply stops
    running on the change that needed it most. `tests/unit/test_eval_trigger.py`
    holds the workflow against this function.
    """
    found = {
        material.PILLARS_FILE,
        material.SOURCES_FILE,
        material.PROFILE_FILE,
    }
    # DIRECT imports only, read out of the source with `ast`. `sys.modules`
    # was the first attempt and over-approximated badly - it returned
    # `language.py` and two `__init__.py` files, none of which can move a score
    # on frozen text, and CI that fires when nothing could have changed teaches
    # people to ignore it as surely as CI that never fires.
    src = ROOT / "src"
    for source in sorted((ROOT / "evals" / "output").glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.split(".")[0] == "content_studio":
                continue
            module = src / Path(*node.module.split("."))
            for candidate in (module.with_suffix(".py"), module / "__init__.py"):
                if candidate.is_file():
                    found.add(candidate)
                    break

    relative = {p.relative_to(ROOT).as_posix() for p in found}
    for pattern in OWN_FILES:
        relative.update(
            p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern)
        )
    return sorted(relative)


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
