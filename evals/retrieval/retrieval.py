"""The search_books pair — `regasire` and `control-negativ`, tool probed directly.

    uv run content-studio-server          # terminal 1
    uv run python evals/retrieval/retrieval.py      # terminal 2

WHAT IS MEASURED, and why no agent is in the loop: layer 6 (RAG) failures are
the tool's own — the right book not surfaced, or an off-topic query scoring
like a match — and putting the agent between the query and the verdict would
only add noise and cost. The probe calls `search_books` the way the agent
does, with `description` in her words, and reads titles and scores back.

  · `regasire` (recall@3): the labelled book must appear in the top 3
    passages. This is the guard on architecture rule 3 — the same embedding
    model at both ends — and on the language gap: 8 of the 17 books are
    English and near-invisible to Romanian phrasings. One case is left red
    on purpose as the detector for that gap (see the dataset).
  · `control-negativ`: queries with nothing on the shelf. The number that
    matters is the SEPARATION between the lowest passing positive top-score
    and the highest negative top-score. Measured on 2026-08-26 the bands
    overlap (positives 0.44–0.63, negatives up to 0.54), which is why score
    alone must never gate a passage — the skill already says so in words;
    this metric says it in numbers, and alarms if the margin shrinks.

CODE, NO JUDGE, NO MODEL: the only spend is one embedding per query. Output
of every case lands in the report with its scores, so a label can be argued
against the evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.mcp import MCPServerStreamableHttp

from content_studio import enable_utf8_output
from content_studio.config import MCP_TIMEOUT, MCP_URL

enable_utf8_output()

HERE = Path(__file__).parent
DATASET_FILE = HERE / "retrieval-dataset.json"
#: One reports folder for the whole suite, one level up from this group.
REPORTS = HERE.parent / "reports"
ROOT = HERE.parents[2]
TOP_K = 3


async def top_passages(
    server: MCPServerStreamableHttp, case: dict[str, Any]
) -> list[dict[str, Any]]:
    result = await server.session.call_tool(
        "search_books",
        {
            "description": case["descriere"],
            "description_en": case["descriere_en"],
            "limit": TOP_K,
        },
    )
    passages: list[dict[str, Any]] = []
    for item in result.content:
        text = getattr(item, "text", None)
        if not text:
            continue
        parsed = json.loads(text)
        passages.extend(parsed if isinstance(parsed, list) else [parsed])
    return passages[:TOP_K]


def found(carti: list[str], passages: list[dict[str, Any]]) -> bool:
    titles = [str(p.get("title") or "") for p in passages]
    return any(want in title for want in carti for title in titles)


def summarised(passages: list[dict[str, Any]]) -> list[tuple[float, str]]:
    return [
        (round(float(p.get("score") or 0), 3), str(p.get("title"))[:44]) for p in passages
    ]


async def run() -> int:
    data = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    server = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        client_session_timeout_seconds=MCP_TIMEOUT,
    )
    try:
        await server.connect()
    except Exception as e:  # noqa: BLE001
        print(f"Serverul MCP nu răspunde la {MCP_URL}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    findings: dict[str, list[dict[str, Any]]] = {"pozitive": [], "negative": []}
    try:
        print("— regasire (recall@3) —")
        for case in data["pozitive"]:
            passages = await top_passages(server, case)
            hit = found(case["carti"], passages)
            top = summarised(passages)
            print(("✓" if hit else "✗"), f"{case['id']:<28}", top)
            findings["pozitive"].append(
                {"case": case["id"], "hit": hit, "top": top, "carti": case["carti"]}
            )
        print("\n— control-negativ —")
        for case in data["negative"]:
            passages = await top_passages(server, case)
            top = summarised(passages)
            print(" ", f"{case['id']:<28}", top)
            findings["negative"].append({"case": case["id"], "top": top})
    finally:
        await server.cleanup()

    hits = [f for f in findings["pozitive"] if f["hit"]]
    recall = len(hits) / len(findings["pozitive"]) if findings["pozitive"] else 0.0
    passing_tops = [f["top"][0][0] for f in hits if f["top"]]
    negative_tops = [f["top"][0][0] for f in findings["negative"] if f["top"]]
    margin = (min(passing_tops) - max(negative_tops)) if passing_tops and negative_tops else None

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"retrieval-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "regasire": round(recall, 3),
                "separare": None if margin is None else round(margin, 3),
                "findings": findings,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nregasire: {len(hits)}/{len(findings['pozitive'])}", end="")
    if margin is not None:
        verdictul = "pozitivele și negativele se SUPRAPUN" if margin <= 0 else "separare pozitivă"
        print(f" · separare: {margin:+.3f} ({verdictul})", end="")
    print(f" · {out.relative_to(ROOT)}")
    return 0


def main() -> int:
    argparse.ArgumentParser(description="search_books: recall@3 + negative control").parse_args()
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
