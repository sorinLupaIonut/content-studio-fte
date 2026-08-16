"""Run the Decision 10 eval set against the real worker.

Needs the MCP server running in another terminal:

    uv run content-studio-server
    uv run python evals/run.py

Every case starts with an empty history. The sandbox and the MCP connection are
reused, but the conversations do not mix. Any write tool is refused during an
eval; the set must not leave posts or profile changes behind.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

from agents import Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig

from content_studio import enable_utf8_output
from content_studio.audit import calls_in
from content_studio.config import MCP_TIMEOUT, MCP_URL
from content_studio.worker import (
    GATED_TOOLS,
    build_sandbox,
    build_worker,
    describe_request,
    read_profile,
)

enable_utf8_output()

HERE = Path(__file__).parent
CASES_FILE = HERE / "cases.json"
DEFAULT_REPORT = HERE / "report-latest.json"

SKILL_PATTERN = re.compile(r"\.agents[/\\]([\w-]+)[/\\]SKILL\.md")
NUMBER_PATTERN = re.compile(r"^\s*(10|[1-9])[.)]\s", re.MULTILINE)
HOOK_PATTERN = re.compile(
    r"^\s*[-*]\s*(PROVOCARE|CIFR[ĂA]|SECRET|[ÎI]NTREBARE|CONTRAST)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Content Worker evals")
    parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        type=int,
        help="run only this case; repeatable",
    )
    parser.add_argument(
        "--automatic-only",
        action="store_true",
        help="skip the cases marked by_eye",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="the output JSON file",
    )
    return parser.parse_args()


def load_cases(options: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    every = data["cases"]
    chosen = [c for c in every if not options.ids or c["id"] in options.ids]
    if options.automatic_only:
        chosen = [c for c in chosen if c["state"] == "automatic"]
    return every, chosen


def tools_and_skills(result) -> tuple[set[str], set[str], list[dict]]:
    tools: set[str] = set()
    skills: set[str] = set()
    details: list[dict] = []
    for call in calls_in(result):
        tools.add(call["name"])
        text = json.dumps(call["arguments"], ensure_ascii=False)
        skills.update(SKILL_PATTERN.findall(text))
        details.append(
            {
                "name": call["name"],
                "arguments": call["arguments"],
                "result": str(call["result"] or "")[:2000],
            }
        )
    return tools, skills, details


async def run_without_writing(worker, message, config):
    """Run one turn and refuse every approval interruption."""
    result = await Runner.run(worker, message, run_config=config)
    write_attempts: list[str] = []
    retries = 0

    while result.interruptions:
        retries += 1
        if retries > 5:
            raise RuntimeError("The agent keeps insisting on writing after five refusals.")
        state = result.to_state()
        for request in result.interruptions:
            name, _, _ = describe_request(request)
            write_attempts.append(name)
            state.reject(
                request,
                rejection_message="Evaluarea nu aprobă nicio scriere.",
            )
        result = await Runner.run(worker, state, run_config=config)

    return result, write_attempts


def answer_with_list(answers: list[str]) -> str:
    """The answer that looks most like the 10 × 5 list."""
    return max(
        answers,
        key=lambda text: (len(set(NUMBER_PATTERN.findall(text))), len(HOOK_PATTERN.findall(text))),
        default="",
    )


def proposals_and_hooks(text: str) -> tuple[int, bool]:
    """Count the proposals and check for exactly the five types in each."""
    positions = list(NUMBER_PATTERN.finditer(text))
    blocks: dict[int, str] = {}
    for index, match in enumerate(positions):
        number = int(match.group(1))
        end = positions[index + 1].start() if index + 1 < len(positions) else len(text)
        blocks[number] = text[match.start() : end]

    exact = True
    expected = {"PROVOCARE", "CIFRĂ", "SECRET", "ÎNTREBARE", "CONTRAST"}
    for number in range(1, 11):
        found = []
        for kind in HOOK_PATTERN.findall(blocks.get(number, "")):
            normalized = kind.upper().replace("CIFRA", "CIFRĂ").replace("INTREBARE", "ÎNTREBARE")
            found.append(normalized)
        exact &= len(found) == 5 and set(found) == expected
    return len(blocks), exact


def verify(case: dict, answers: list[str], tools: set[str], skills: set[str]) -> list[str]:
    rules = case.get("checks") or {}
    final = answers[-1] if answers else ""
    errors: list[str] = []

    patterns = rules.get("contains", [])
    if patterns and not any(re.search(p, final, re.IGNORECASE) for p in patterns):
        errors.append(f"the final answer matches none of the required patterns: {patterns}")

    forbidden = [p for p in rules.get("must_not_contain", []) if re.search(p, final, re.IGNORECASE)]
    if forbidden:
        errors.append(f"the final answer contains forbidden patterns: {forbidden}")

    missing = set(rules.get("tools", [])) - tools
    if missing:
        errors.append(f"tools not called: {sorted(missing)}")

    called_anyway = set(rules.get("forbidden_tools", [])) & tools
    if called_anyway:
        errors.append(f"forbidden tools were called: {sorted(called_anyway)}")

    missing_skills = set(rules.get("skills", [])) - skills
    if missing_skills:
        errors.append(f"skills not activated: {sorted(missing_skills)}")

    if "proposal_count" in rules or "hook_types" in rules:
        listing = answer_with_list(answers)
        count, exact_hooks = proposals_and_hooks(listing)
        if "proposal_count" in rules and count != rules["proposal_count"]:
            errors.append(f"proposals: {count}, expected {rules['proposal_count']}")
        if "hook_types" in rules and not exact_hooks:
            errors.append("not every proposal carries exactly the five hook types")

    return errors


async def main() -> int:
    options = parse_args()
    every, cases = load_cases(options)
    unknown = set(options.ids or []) - {c["id"] for c in every}
    if unknown:
        print(f"No such cases: {sorted(unknown)}", file=sys.stderr)
        return 2

    data_mcp = MCPServerStreamableHttp(
        params={"url": MCP_URL},
        name="content-data",
        cache_tools_list=True,
        client_session_timeout_seconds=MCP_TIMEOUT,
        require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
    )
    try:
        await data_mcp.connect()
        _, profile_md = await read_profile(data_mcp)
    except Exception as e:  # noqa: BLE001
        print(
            f"Cannot load the profile over MCP at {MCP_URL}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        await data_mcp.cleanup()
        return 2

    client, sandbox_options = build_sandbox()
    sandbox = await client.create(options=sandbox_options)
    config = RunConfig(sandbox=SandboxRunConfig(client=client, session=sandbox))
    worker = build_worker(profile_md, data_mcp)
    report: list[dict] = []
    failures = 0

    try:
        for case in cases:
            if case["state"] == "deferred":
                print(f"○ {case['id']:>2} DEFERRED     {case['title']}")
                report.append({"id": case["id"], "verdict": "deferred", "title": case["title"]})
                continue

            print(f"\n[{case['id']}/{len(every)}] {case['title']}", flush=True)
            started = time.monotonic()
            history: list = []
            answers: list[str] = []
            tools: set[str] = set()
            skills: set[str] = set()
            reported_calls: list[dict] = []
            run_error: str | None = None

            try:
                for message in case["turns"]:
                    result, attempts = await run_without_writing(
                        worker,
                        history + [{"role": "user", "content": message}],
                        config,
                    )
                    history = result.to_input_list()
                    answers.append(str(result.final_output))
                    turn_tools, turn_skills, turn_calls = tools_and_skills(result)
                    tools.update(turn_tools)
                    tools.update(attempts)
                    skills.update(turn_skills)
                    reported_calls.extend(turn_calls)
            except Exception as e:  # noqa: BLE001
                run_error = f"{type(e).__name__}: {e}"

            errors = [run_error] if run_error else verify(case, answers, tools, skills)
            errors = [e for e in errors if e]
            needs_eye = case["state"] == "by_eye" and not errors
            verdict = "by_eye" if needs_eye else ("failed" if errors else "passed")
            failures += verdict == "failed"
            mark = "◐" if verdict == "by_eye" else ("✓" if verdict == "passed" else "✗")
            print(
                f"{mark} {verdict.upper():<10} {time.monotonic() - started:.0f}s · "
                f"tools={sorted(tools) or ['—']} · skills={sorted(skills) or ['—']}"
            )
            for error in errors:
                print(f"    {error}")
            if needs_eye:
                print("    the content verdict is given from `final_answer` in the report")

            report.append(
                {
                    "id": case["id"],
                    "title": case["title"],
                    "state": case["state"],
                    "verdict": verdict,
                    "errors": errors,
                    "tools": sorted(tools),
                    "skills": sorted(skills),
                    "calls": reported_calls,
                    "final_answer": answers[-1] if answers else "",
                    "expected": case["expected"],
                }
            )
    finally:
        await client.delete(sandbox)
        await data_mcp.cleanup()

    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(
        json.dumps({"cases": report}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    passed = sum(r["verdict"] == "passed" for r in report)
    by_eye = sum(r["verdict"] == "by_eye" for r in report)
    deferred = sum(r["verdict"] == "deferred" for r in report)
    print(
        f"\nResult: {passed} passed · {failures} failed · "
        f"{by_eye} by eye · {deferred} deferred"
    )
    print(f"Report: {options.report}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
