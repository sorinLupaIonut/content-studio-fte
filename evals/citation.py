"""`citare` — Citation Correctness: `source` claims only what the tools returned.

    uv run content-studio-server          # terminal 1
    uv run python evals/citation.py       # terminal 2
    uv run python evals/citation.py --id carti-pagina-reala

WHAT IS MEASURED. The code half of the RAG family (layer 6). A phase-2 run is
made through the real generation path — method in a container, `detail_prompt`,
the production output contract — and every claim of provenance on the five
variants' `source` fields is held against what the tools returned in THAT
run, never against the shelf in general:

  · a book title on `source` must be one `search_books` actually returned;
  · a cited page must be among the returned pages for that book — a page
    invented for a book whose passages carry none is the exact fraud this
    metric hunts (the skill says: no page returned, no page written);
  · a URL on `source` must be one `search_web` returned;
  · `Memorie` runs search nowhere and say "din memorie" — the negative
    control: a book or link cited there is provenance theater.

CODE, NOT A JUDGE: existence is a membership test. Whether the *content* of
the post is supported by those passages is Faithfulness — the judge half of
the same family, validated separately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents import ModelSettings
from agents.run_config import RunConfig

sys.path.insert(0, str(Path(__file__).parent))

from convergence import data_mcp_server  # noqa: E402
from tool_use import run_without_writing  # noqa: E402

from content_studio import enable_utf8_output  # noqa: E402
from content_studio.audit import calls_in  # noqa: E402
from content_studio.config import MCP_URL  # noqa: E402
from content_studio.harness.generation import (  # noqa: E402
    GenerationBatchRequest,
    IdeaTitle,
    detail_output_type,
    detail_prompt,
)
from content_studio.sandbox import sandbox_run_config  # noqa: E402
from content_studio.worker import build_worker, read_profile  # noqa: E402

enable_utf8_output()

HERE = Path(__file__).parent
DATASET_FILE = HERE / "citation-dataset.json"
REPORTS = HERE / "reports"

URL_RE = re.compile(r"https?://\S+")
PAGE_RE = re.compile(r"pagina\s+(\d+)", re.IGNORECASE)


def gathered_evidence(calls: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """(book passages, web URLs, tool names) actually returned in this run."""
    passages: list[dict] = []
    urls: list[str] = []
    names: list[str] = []
    for call in calls:
        names.append(call["name"])
        raw = call.get("result")
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            continue
        if call["name"] == "search_books":
            rows = data if isinstance(data, list) else [data]
            passages.extend(r for r in rows if isinstance(r, dict))
        elif call["name"] == "search_web" and isinstance(data, dict):
            urls.extend(s.get("url", "") for s in data.get("sources", []))
            urls.extend(URL_RE.findall(str(data.get("angles", ""))))
    return passages, urls, names


def verdict_source(
    source: str, sursa: str, passages: list[dict], urls: list[str], names: list[str]
) -> list[str]:
    """Every reason this one `source` field lies; empty means honest."""
    reasons: list[str] = []
    titles = {str(p.get("title") or "") for p in passages}
    cited_title = next((t for t in titles if t and t in source), None)

    if sursa == "Memorie":
        if "memorie" not in source.lower():
            reasons.append(f"sursa Memorie trebuie declarată; scrie: {source!r}")
        if names:
            reasons.append(f"rulare din Memorie care a căutat totuși: {names}")
        if URL_RE.search(source):
            reasons.append(f"link pe o rulare din Memorie: {source!r}")
        return reasons

    if sursa == "Cărți":
        if cited_title is None:
            reasons.append(
                f"niciun titlu întors de search_books nu apare în source: {source!r}"
            )
        for page in PAGE_RE.findall(source):
            owner_pages = {
                str(p.get("page"))
                for p in passages
                if cited_title and str(p.get("title") or "") == cited_title
            }
            if page not in owner_pages:
                reasons.append(
                    f"pagina {page} nu e printre paginile întoarse pentru "
                    f"{cited_title or 'cartea citată'}: {sorted(owner_pages)}"
                )
        return reasons

    if sursa == "Internet":
        cited = URL_RE.findall(source)
        if not cited:
            reasons.append(f"sursa Internet fără niciun link în source: {source!r}")
        for url in cited:
            clean = url.rstrip(").,]")
            if not any(clean in real or real in clean for real in urls if real):
                reasons.append(f"link necunoscut uneltei: {clean}")
        return reasons

    return [f"mod-sursă neacoperit de metrică: {sursa}"]


async def run_case(data_mcp, profile_md: str, case: dict[str, Any]) -> dict[str, Any]:
    # gpt-5-mini, which since 2026-08-27 is the only model the interface
    # offers - so this is production's model, not a stand-in for it.
    worker = build_worker(
        profile_md,
        data_mcp,
        model="gpt-5-mini",
        output_type=detail_output_type(case["format"]),
        model_settings=ModelSettings(
            reasoning={"effort": "minimal"}, verbosity="low", max_tokens=24_000
        ),
    )
    request = GenerationBatchRequest(
        format=case["format"],
        pillar=case["pilon"],
        source=case["sursa"],
        focus=case.get("focus"),
    )
    idea = IdeaTitle(**case["idee"])
    # One container per case, the same as production gives one per run. The
    # method has to be opened from inside it, which is the point: a citation
    # metric run against a worker that never reached its own method would be
    # measuring the model's memory, not the method.
    async with sandbox_run_config(f"citation-{case['id']}") as sandbox:
        result, _ = await run_without_writing(
            worker,
            detail_prompt(request, idea, profile_md),
            RunConfig(sandbox=sandbox),
        )
    passages, urls, names = gathered_evidence(calls_in(result))
    details = result.final_output
    reasons: list[str] = []
    sources: list[str] = []
    for variant in details.variants:
        sources.append(variant.source)
        reasons.extend(verdict_source(variant.source, case["sursa"], passages, urls, names))
    return {
        "case": case["id"],
        "score": 0.0 if reasons else 1.0,
        "route": names,
        "sources": sources,
        "returned_titles": sorted({str(p.get("title")) for p in passages}),
        "returned_urls": urls,
        "reasons": reasons,
    }


async def run(ids: list[str] | None) -> int:
    data = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    cases = data["cazuri"]
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    server = data_mcp_server()
    try:
        await server.connect()
        _, profile_md = await read_profile(server)
    except Exception as e:  # noqa: BLE001
        print(f"Serverul MCP nu răspunde la {MCP_URL}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    findings = []
    failures = 0
    try:
        for case in cases:
            started = time.monotonic()
            try:
                finding = await run_case(server, profile_md, case)
            except Exception as e:  # noqa: BLE001
                finding = {
                    "case": case["id"],
                    "score": 0.0,
                    "reasons": [f"rularea a eșuat: {type(e).__name__}: {e}"],
                }
            failures += finding["score"] < 1.0
            mark = "✓" if finding["score"] == 1.0 else "✗"
            print(f"{mark} {case['id']:<28} {time.monotonic() - started:>4.0f}s")
            for src in finding.get("sources", []):
                print(f"    source: {src[:96]}")
            for reason in finding.get("reasons", []):
                print(f"    !! {reason}")
            findings.append(finding)
    finally:
        await server.cleanup()

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"citation-{stamp}.json"
    out.write_text(
        json.dumps({"generated_at": stamp, "findings": findings}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"\ncitare: {len(cases) - failures}/{len(cases)} · {out.relative_to(HERE.parent)}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Citation Correctness on real phase-2 runs")
    parser.add_argument("--id", dest="ids", action="append")
    args = parser.parse_args()
    return asyncio.run(run(args.ids))


if __name__ == "__main__":
    raise SystemExit(main())
