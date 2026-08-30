"""Metric `relevance` — the skill eval: was the search any good?

    uv run python evals/skill/relevance.py --dry-run     # what would be judged, free
    uv run python evals/skill/relevance.py               # judges. Costs a few cents.
    uv run python evals/skill/relevance.py --minutes 240 # a wider window

THE OTHER HALF OF `route/`. The route group asks whether the right tool was
called; it reads the call's NAME. It cannot see that a call succeeded and came
back with nothing usable — and its README says so in as many words: a failed
tool call still counts as called. This group asks the next question, of the same
two tools: did the search actually bring back material for this brief?

ONE METRIC, BOTH TOOLS. Until 2026-08-30 `search_web` returned a synthesis
(`angles`, one prose blob written by a model) while `search_books` returned
passages, so the two needed different questions — one about retrieval, one about
groundedness. They return the same shape now, material with its provenance, so
they get the same question and the same rubric.

WHAT THE JUDGE IS SHOWN, and why each piece is there:

  · the **brief** — format, pillar, source, focus. Lifted off the prompt in the
    same trace, not off the root span's name: the eval runs name their case
    there, production runs do not, and a metric that only works on eval traffic
    measures the eval.
  · the **avatar** — Andreea's needs, desires, pains, fears and beliefs, read
    from the profile on disk through `avatar.excerpt`, the same five sections
    the writer is shown. Imported rather than copied: what the writer is asked
    for and what the judge looks for must not drift apart.
  · the **request** the model composed, and the **material** that came back.

Both halves are graded together on purpose. A perfect tool answering a lazy
question is not a good search, and neither is a sharp question that came back
empty — and both get fixed in the same place, the skill's search rule.

WHAT IT DOES NOT DO. It runs no agent and opens no container: it reads spans
Phoenix already holds, so every run it grades is one already paid for. The only
cost is the judge. It writes its verdicts back onto the spans as annotations, so
the label sits next to the call it belongs to in the Phoenix UI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from phoenix.client import Client
from phoenix.evals import LLM, create_classifier, evaluate_dataframe

from content_studio import enable_utf8_output
from content_studio.avatar import excerpt as avatar_excerpt
from content_studio.config import (
    CONTENT_DIR,
    EVAL_JUDGE_MODEL,
    PHOENIX_API_KEY,
    PHOENIX_COLLECTOR_ENDPOINT,
    PHOENIX_PROJECT_NAME,
)
from content_studio.observability import phoenix_api_base

enable_utf8_output()

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parent / "reports"

#: The two tools this group grades. Both are read-only searches, and they are
#: the only two the generation agents can see (`GENERATION_VISIBLE_TOOLS`).
TOOLS = ("search_books", "search_web")

#: The four choices, off the prompt that carried them. Read from a span in the
#: same trace rather than from the root's name, so production runs are graded
#: too — `title_prompt` and `detail_prompt` both write these four lines.
BRIEF = re.compile(
    r"Format:\s*(?P<format>[^\\\"\n]+)"
    r".{0,80}?Pilon:\s*(?P<pillar>[^\\\"\n]+)"
    r".{0,80}?Sursă:\s*(?P<source>[^\\\"\n]+)"
    r".{0,80}?Focus:\s*(?P<focus>[^\\\"\n]+)",
    re.S,
)

#: How much of the returned material the judge is shown. Whole passages would put
#: the judge's cost on the size of the shelf; the opening characters are enough
#: to tell material from noise.
MATERIAL_CHARS = 4_000

#: Seconds allowed for the span read. `get_spans_dataframe` takes its own
#: `timeout` and DEFAULTS IT TO 5 - a client-level timeout does not reach it, so
#: any window wide enough to be interesting dies at five seconds flat with an
#: `httpx.ReadTimeout` that names no call. Measured 2026-08-30: 400 spans came
#: back in 4.7s, 2000 spans hit the default and failed.
READ_TIMEOUT = 300

#: The avatar is read from disk, not from Neon, so the eval needs no server and
#: no database. The cost of that: a profile she has edited through
#: `update_profile` lives in `clients.profile_md` and this file does not see it,
#: so the judge would grade against a stale avatar. Re-seed before trusting a
#: run made after a profile edit.
PROFILE = CONTENT_DIR / "profile.md"

JUDGE_PROMPT = """You are grading ONE search made by a content-writing agent.

The agent writes Romanian social content for a coach. Before it writes, it must
fetch material from the source the client chose. You are grading that fetch —
not the post, which does not exist yet.

THE BRIEF THE AGENT WAS WORKING TO
Format: {format}
Pillar: {pillar}
Source: {source}
Focus: {focus}

WHO THE CONTENT IS FOR — the client's avatar, in her own words:
{avatar}

WHAT THE AGENT ASKED THE TOOL FOR
{description}

WHAT THE TOOL RETURNED
{material}

Answer "relevant" only if BOTH of these hold:

1. The request is shaped by the brief. It serves this format, this pillar and
   this focus, and it starts from a nameable need, desire, pain, fear or belief
   of the avatar above — not from a broad theme like "boundaries" or "self-care"
   that would be true of any woman.
2. The material that came back actually treats that subject. A passage that is
   only vaguely on-topic, or that discusses something adjacent, is not material.
   An empty result is not material either.

Answer "irelevant" if either one fails.

The material is Romanian, and some of it is English; judge the substance, never
the language. Write your reasoning first, then the label on its own.
"""


def phoenix() -> Client:
    """The Phoenix client for this project."""
    return Client(
        base_url=phoenix_api_base(PHOENIX_COLLECTOR_ENDPOINT),
        api_key=PHOENIX_API_KEY,
    )


def as_text(value: object) -> str:
    """A span attribute as prose, whatever shape the exporter wrapped it in.

    Tool output arrives as MCP content: sometimes one dict, sometimes a list of
    them, sometimes already a string. Only the text matters here.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, str):
        try:
            return as_text(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value
    if isinstance(value, list):
        return "\n".join(as_text(v) for v in value)
    if isinstance(value, dict):
        if "text" in value:
            return as_text(value["text"])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def asked_for(value: object) -> str:
    """The `description` argument — the question the model wrote for itself."""
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    try:
        args = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return str(raw)
    if not isinstance(args, dict):
        return str(raw)
    parts = [str(args.get("description", "")).strip()]
    if args.get("titles"):
        parts.append(f"(cărți alese: {', '.join(args['titles'])})")
    return " ".join(part for part in parts if part)


def brief_of(trace: pd.DataFrame) -> dict[str, str]:
    """The four choices, from the first span in this trace that carries them."""
    for value in trace["attributes.input.value"].dropna():
        found = BRIEF.search(str(value))
        if found is not None:
            return {key: text.strip() for key, text in found.groupdict().items()}
    return {"format": "?", "pillar": "?", "source": "?", "focus": "?"}


def cases(minutes: int, limit: int) -> pd.DataFrame:
    """One row per search worth grading, newest first."""
    spans = phoenix().spans.get_spans_dataframe(
        project_identifier=PHOENIX_PROJECT_NAME,
        start_time=datetime.now(UTC) - timedelta(minutes=minutes),
        limit=limit,
        timeout=READ_TIMEOUT,
    )
    if not len(spans):
        return pd.DataFrame()

    avatar = avatar_excerpt(PROFILE.read_text(encoding="utf-8"))
    searches = spans[spans["name"].isin(TOOLS)]
    rows = []
    for span_id, span in searches.iterrows():
        material = as_text(span.get("attributes.output.value"))
        trace = spans[spans["context.trace_id"] == span["context.trace_id"]]
        rows.append(
            {
                "span_id": span_id,
                "tool": span["name"],
                "started": span["start_time"],
                "description": asked_for(span.get("attributes.input.value")),
                "material": material[:MATERIAL_CHARS],
                "returned_chars": len(material),
                "avatar": avatar,
                **brief_of(trace),
            }
        )
    frame = pd.DataFrame(rows)
    return frame.sort_values("started", ascending=False) if len(frame) else frame


def unpack(frame: pd.DataFrame, graded: pd.DataFrame) -> pd.DataFrame:
    """The judge's verdicts, off the column `evaluate_dataframe` writes.

    That column is named `<score name>_score` and holds a JSON-serialized
    `Score` — name, score, label, explanation — NOT a float. Comparing it to
    1.0 is False for every row, which reads as a clean zero and is not one.
    """
    verdicts = graded.get("relevance_score")
    labels, scores, why = [], [], []
    for raw in (verdicts if verdicts is not None else [None] * len(frame)):
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict):
            labels.append(None)
            scores.append(None)
            why.append("")
            continue
        labels.append(payload.get("label"))
        scores.append(payload.get("score"))
        why.append(payload.get("explanation") or "")
    out = frame.copy()
    out["label"] = labels
    out["score"] = scores
    out["explanation"] = why
    out["execution_details"] = list(
        graded.get("relevance_execution_details", [None] * len(frame))
    )
    return out


def show(frame: pd.DataFrame, judged: bool) -> None:
    """The report, in Romanian — the terminal is read by the client too."""
    print(f"\n{'unealtă':<13} {'format':<8} {'pilon':<12} {'sursă':<9} {'':<3} ce a cerut")
    print("-" * 108)
    for _, row in frame.iterrows():
        verdict = ""
        if judged:
            verdict = "✓" if row.get("score") == 1.0 else "✗"
        ask = row["description"][:48].replace("\n", " ")
        print(
            f"{row['tool']:<13} {row['format']:<8} {row['pillar']:<12} "
            f"{row['source']:<9} {verdict:<3} {ask}…"
        )
    print()

    if not judged:
        empty = int((frame["returned_chars"] == 0).sum())
        print(f"{len(frame)} căutări de judecat. {empty} au întors zero caractere.")
        print("Niciun judecător chemat, niciun cost.")
        return

    for tool in TOOLS:
        half = frame[frame["tool"] == tool]
        if len(half):
            good = int((half["score"] == 1.0).sum())
            print(f"{tool:<14} relevanță {good}/{len(half)}")
    print(f"{'TOTAL':<14} relevanță {int((frame['score'] == 1.0).sum())}/{len(frame)}")


def report(frame: pd.DataFrame, judged: bool) -> Path:
    """The evidence of one moment, next to every other group's."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    out = REPORTS / f"relevance-{stamp}.json"
    # The avatar block is the same on every row and is her content; the report
    # carries the verdicts, not the profile.
    keep = [
        column for column in frame.columns if column not in ("avatar", "execution_details")
    ]
    out.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "judge": EVAL_JUDGE_MODEL if judged else None,
                "cases": len(frame),
                "findings": json.loads(
                    frame[keep].to_json(orient="records", date_format="iso")
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="relevance, on both search tools")
    parser.add_argument("--dry-run", action="store_true", help="what would be judged, free")
    parser.add_argument("--minutes", type=int, default=1440, help="how far back to read")
    parser.add_argument("--limit", type=int, default=2000, help="span ceiling per read")
    parser.add_argument("--tool", choices=TOOLS, help="grade only one of the two")
    parser.add_argument("--no-log", action="store_true", help="do not annotate the spans")
    args = parser.parse_args()

    if not (PHOENIX_COLLECTOR_ENDPOINT and PHOENIX_API_KEY):
        print("Phoenix nu e configurat: PHOENIX_COLLECTOR_ENDPOINT sau cheia lipsește.")
        return 1

    frame = cases(args.minutes, args.limit)
    if args.tool and len(frame):
        frame = frame[frame["tool"] == args.tool]
    if not len(frame):
        print(f"Nicio căutare în ultimele {args.minutes} de minute.")
        return 0

    if args.dry_run:
        show(frame, judged=False)
        print(f"\nRaport: {report(frame, judged=False)}")
        return 0

    evaluator = create_classifier(
        name="relevance",
        prompt_template=JUDGE_PROMPT,
        llm=LLM(provider="openai", model=EVAL_JUDGE_MODEL),
        choices={"relevant": 1.0, "irelevant": 0.0},
    )
    graded = evaluate_dataframe(frame, [evaluator])
    frame = unpack(frame, graded)

    unreadable = int(frame["score"].isna().sum())
    if unreadable:
        # A verdict that could not be read is not a verdict of zero. Say so and
        # refuse the summary rather than print a clean-looking 0/N - which is
        # exactly what this file did on its first run, on 2026-08-30.
        print(f"\n{unreadable} din {len(frame)} verdicte n-au putut fi citite.")
        for detail in frame.loc[frame["score"].isna(), "execution_details"].head(3):
            print(f"  {str(detail)[:200]}")
        if unreadable == len(frame):
            print("Niciun verdict citit — nu raportez un scor.")
            print(f"Raport: {report(frame, judged=True)}")
            return 1

    show(frame, judged=True)

    if not args.no_log:
        annotations = frame.loc[
            frame["score"].notna(), ["span_id", "label", "score", "explanation"]
        ].copy()
        phoenix().spans.log_span_annotations_dataframe(
            dataframe=annotations,
            annotation_name="relevance",
            annotator_kind="LLM",
        )
        print(f"\n{len(annotations)} verdicte urcate pe span-uri în Phoenix.")

    print(f"Raport: {report(frame, judged=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
