"""Freeze what the studio already wrote into a gradable set.

    uv run python evals/output/seed_golden.py --batches 5
    uv run python evals/output/seed_golden.py --batch 62dfb546

WHY THE DATABASE AND NOT A TRACE. Output evals grade a pair - what was asked,
what came out - and both halves are already columns: `generation_batches` holds
the brief the interface built, `generation_ideas` and `generation_variants` hold
what the model returned. `public.traces` would give the same text back the long
way round, through a `response_id` and a provider call.

WHY IT IS FROZEN. Re-generating on every run would make the suite cost money,
need three services up, and grade a different text each time - so a score moving
would tell you nothing about whether anything changed. A frozen set is what
makes a regression readable.

ONE ROW PER GRADABLE ANSWER, not one per run. A title run emits ten ideas and a
detail run five variants; a metric scores a caption, not a batch. Averaging ten
ideas into one number before grading throws away the only resolution that lets
you say WHICH idea went generic.

THE RULER IS NOT STORED HERE AT ALL. Until 2026-08-25 this script copied the
profile excerpt and the pillars into the file, and re-reading them on every
re-seed was a silent way to change the measure while keeping the old baseline.
They are read live by `material.py` and watched by `ruler.py` instead; this file
holds the SUBJECT - what was asked and what came out - and nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "evals" / "golden.json"

BATCHES_SQL = """
    SELECT b.id::text AS id, b.source, b.pillar, b.format, b.focus,
           b.source_packet, b.status, b.created_at
      FROM public.generation_batches b
     WHERE b.status IN ('ready', 'titles_ready', 'generating')
     ORDER BY b.created_at DESC
     LIMIT :limit
"""

IDEAS_SQL = """
    SELECT i.id::text AS id, i.batch_id::text AS batch_id, i.ordinal,
           i.title, i.angle, i.status
      FROM public.generation_ideas i
     WHERE i.batch_id = ANY(CAST(:batch_ids AS uuid[]))
     ORDER BY i.batch_id, i.ordinal
"""

VARIANTS_SQL = """
    SELECT v.idea_id::text AS idea_id, v.hook_type, v.hook, v.script,
           v.caption, v.hashtags, v.cta, v.source
      FROM public.generation_variants v
     WHERE v.idea_id = ANY(CAST(:idea_ids AS uuid[]))
       AND v.status = 'ready'
     ORDER BY v.idea_id, v.hook_type
"""


def as_json(value: Any) -> Any:
    """asyncpg hands jsonb back decoded; a fixture or another driver may not."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def passages_of(packet: Any) -> list[str]:
    """The passages the source brought back, or nothing for a Memorie batch."""
    packet = as_json(packet)
    if not isinstance(packet, dict):
        return []
    books = packet.get("books")
    return [str(p) for p in books] if isinstance(books, list) else []


def brief_of(batch: dict[str, Any]) -> dict[str, str]:
    return {
        "pilon": batch["pillar"],
        "format": batch["format"],
        "sursa": batch["source"],
        "focus": batch["focus"] or "",
    }


def brief_sentence(brief: dict[str, str]) -> str:
    """The ask, rebuilt in the words the interface used to build it."""
    line = (
        f"Pilonul «{brief['pilon']}», formatul «{brief['format']}», "
        f"sursa «{brief['sursa']}»"
    )
    return f"{line}. Focus: {brief['focus']}." if brief["focus"] else f"{line}."


def idea_case(
    batch: dict[str, Any], idea: dict[str, Any], passages: list[str]
) -> dict[str, Any]:
    brief = brief_of(batch)
    return {
        "id": f"{batch['id'][:8]}-i{idea['ordinal']:02d}",
        "category": "idea",
        "brief": brief,
        "input": f"Propune o idee de postare. {brief_sentence(brief)}",
        "context": passages,
        "actual_output": f"{idea['title']}\n\n{idea['angle']}",
        "caption": None,
        # Hers to write, one line, and only on the cases that fail. A frozen
        # answer says what happened; this is the only field that can say what
        # SHOULD have. Left null rather than guessed - a machine-written
        # expectation is just the output paraphrased, and would turn the set
        # into one that agrees with itself.
        "expected_behavior": None,
        "meta": {"batch_id": batch["id"], "ordinal": idea["ordinal"]},
    }


def variant_case(
    batch: dict[str, Any],
    idea: dict[str, Any],
    variant: dict[str, Any],
    passages: list[str],
) -> dict[str, Any]:
    brief = brief_of(batch)
    tags = as_json(variant["hashtags"]) or []
    parts = [
        f"HOOK ({variant['hook_type']}): {variant['hook']}",
        f"SCRIPT: {variant['script']}" if variant["script"] else None,
        f"CAPTION: {variant['caption']}",
        f"CTA: {variant['cta']}",
        f"HASHTAGS: {' '.join(tags)}",
        f"SURSA: {variant['source']}",
    ]
    return {
        "id": f"{batch['id'][:8]}-i{idea['ordinal']:02d}-{variant['hook_type']}",
        "category": "variant",
        "brief": brief,
        "input": (
            f"Dezvoltă ideea «{idea['title']}», varianta {variant['hook_type']}. "
            f"{brief_sentence(brief)}"
        ),
        "context": passages,
        "actual_output": "\n\n".join(p for p in parts if p),
        # The caption on its own, because `CaptionLength` counts characters and
        # must not count the hook and the script it is packaged with above.
        "caption": variant["caption"],
        "expected_behavior": None,
        "meta": {
            "batch_id": batch["id"],
            "ordinal": idea["ordinal"],
            "hook_type": variant["hook_type"],
        },
    }


async def collect(limit: int, only: str | None) -> dict[str, Any]:
    url, connect_args = database_url()
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(BATCHES_SQL), {"limit": limit})).mappings()
            batches = [dict(r) for r in rows]
            if only:
                batches = [b for b in batches if b["id"].startswith(only)]
            if not batches:
                return {"cases": [], "batches": []}

            rows = (
                await conn.execute(
                    text(IDEAS_SQL), {"batch_ids": [b["id"] for b in batches]}
                )
            ).mappings()
            ideas = [dict(r) for r in rows]

            variants: list[dict[str, Any]] = []
            if ideas:
                rows = (
                    await conn.execute(
                        text(VARIANTS_SQL), {"idea_ids": [i["id"] for i in ideas]}
                    )
                ).mappings()
                variants = [dict(r) for r in rows]
    finally:
        await engine.dispose()

    by_batch = {b["id"]: b for b in batches}
    by_idea: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        by_idea.setdefault(variant["idea_id"], []).append(variant)

    cases: list[dict[str, Any]] = []
    for idea in ideas:
        batch = by_batch[idea["batch_id"]]
        passages = passages_of(batch["source_packet"])
        cases.append(idea_case(batch, idea, passages))
        for variant in by_idea.get(idea["id"], []):
            cases.append(variant_case(batch, idea, variant, passages))

    return {"cases": cases, "batches": batches}


def main() -> int:
    enable_utf8_output()
    parser = argparse.ArgumentParser(description="Seed evals/golden.json from Neon.")
    parser.add_argument("--batches", type=int, default=5, help="how many recent batches")
    parser.add_argument("--batch", help="only this batch, by id or its first 8 chars")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    try:
        collected = asyncio.run(collect(args.batches, args.batch))
    except MissingConfig as exc:
        print(f"Configurare lipsă: {exc}", file=sys.stderr)
        return 2

    cases: list[dict[str, Any]] = collected["cases"]
    if not cases:
        print("Niciun lot de înghețat. Generează unul din interfață întâi.")
        return 1

    # Re-seeding must not silently discard the two things a person wrote: the
    # expectations, and the baseline CI blocks on. Carried over by case id, so a
    # case that no longer exists drops its expectation with it.
    previous: dict[str, Any] = {}
    if args.out.is_file():
        previous = json.loads(args.out.read_text(encoding="utf-8"))
    kept = {
        c["id"]: c.get("expected_behavior")
        for c in previous.get("cases", [])
        if c.get("expected_behavior")
    }
    for case in cases:
        if case["id"] in kept:
            case["expected_behavior"] = kept[case["id"]]

    payload = {
        "_": [
            "Set înghețat pentru output evals (stratul 3). Scris de",
            "`evals/output/seed_golden.py` din ce a produs deja studioul - nu de",
            "mână, și niciodată regenerat în timpul unei rulări de teste.",
            "Aici stă DOAR subiectul: ce s-a cerut și ce a ieșit. Rigla - piloni,",
            "surse, formate, profilul Andreei - se citește vie din fișierele ei,",
            "prin evals/output/material.py, și e amprentată de ruler.py.",
        ],
        # Written by `report.py --update-baseline`, never here: a baseline is a
        # measurement of a run, and this script has not run anything.
        "baseline": previous.get("baseline", {}),
        "open": previous.get("open", []),
        "cases": cases,
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    ideas = sum(1 for c in cases if c["category"] == "idea")
    with_passages = sum(1 for c in cases if c["context"])
    print(f"{args.out.relative_to(ROOT)}: {len(cases)} cazuri")
    print(f"  {ideas} idei, {len(cases) - ideas} variante")
    print(f"  {with_passages} cu pasaje din sursă, {len(cases) - with_passages} fără")
    for batch in collected["batches"]:
        mine = [c for c in cases if c["meta"]["batch_id"] == batch["id"]]
        if mine:
            print(
                f"  lot {batch['id'][:8]}  {batch['format']}/{batch['pillar']}"
                f"/{batch['source']}  →  {len(mine)} cazuri"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
