"""`fidelitate` — the method reaches the container whole, byte for byte.

    uv run python evals/route/fidelity.py       # one container, no model, no cost

WHAT IS MEASURED, AND WHY IT MOVED. Until 2026-08-27 the method was carried by
three tools of ours - one per skill, plus `citeste-referinta` - and the metric
was the courier's honesty: does what the model receives equal what sits on disk?
The couriers are gone. The method is mounted into a sandbox and opened by the
model with the shell, so the same question now has a different address: does
what landed in the container equal what sits on disk?

It is the same failure it always was, and it is still silent. A file that
arrives truncated, re-encoded, or not at all does not raise: the model reads
what is there and writes something plausible from the rest. Romanian makes the
encoding half real rather than theoretical - every one of these files is full of
diacritics, and a mount that lost them would still look like a mount that worked.

So this opens one real container, lists what is under `.agents/`, reads every
file back, and compares bytes. No model is called and nothing is generated: the
only cost is about a second of container, which is what makes it cheap enough to
run before any commit that touches `skills/` or the sandbox wiring.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from content_studio import enable_utf8_output
from content_studio.config import SKILLS_DIR
from content_studio.sandbox import SKILLS_PATH, sandbox_manifest, sandbox_options
from content_studio.worker import parse_skill

enable_utf8_output()

HERE = Path(__file__).parent
#: One reports folder for the whole suite, one level up from this group.
REPORTS = HERE.parent / "reports"
ROOT = HERE.parents[2]


def expected() -> dict[str, Path]:
    """Every file that should exist in the container, keyed by its path there.

    Built from disk rather than from the manifest: a manifest that forgot a file
    would otherwise agree with a container that is missing it, and the report
    would be two wrongs cancelling out.
    """
    found: dict[str, Path] = {}
    for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            continue
        found[f"{SKILLS_PATH}/{folder.name}/SKILL.md"] = skill_md
        for path in sorted((folder / "references").glob("*.md")):
            found[f"{SKILLS_PATH}/{folder.name}/references/{path.name}"] = path
    return found


async def run() -> int:
    from agents.extensions.sandbox.e2b import E2BSandboxClient

    findings: list[dict] = []
    wanted = expected()
    if not wanted:
        print("No skill on disk - there is nothing to measure.")
        return 1

    client = E2BSandboxClient()
    session = await client.create(manifest=sandbox_manifest(), options=sandbox_options())
    await session.apply_manifest()
    try:
        root = session.state.manifest.root
        for where, path in wanted.items():
            # BYTES, NOT TEXT, on both sides. `read_text` opens in universal
            # newline mode, so on Windows it silently turns every CRLF into LF
            # and reports a file 298 characters shorter than the one that was
            # uploaded. The first run of this script called a perfectly good
            # mount broken for exactly that reason. Bytes are also the only way
            # the encoding half of the claim gets tested at all.
            on_disk = path.read_bytes()
            try:
                # `read` rather than `cat` through the shell: a shell would put
                # its own line endings and its own truncation between the file
                # and the comparison, which is what is being measured.
                handle = await session.read(f"{root}/{where}")
                in_box = handle.read()
            except Exception as exc:  # noqa: BLE001 - a missing file is a finding
                findings.append(
                    {"check": where, "ok": False, "chars": 0, "detail": type(exc).__name__}
                )
                continue
            detail = ""
            if in_box != on_disk:
                detail = f"pe disc {len(on_disk)} octeti"
            else:
                try:
                    in_box.decode("utf-8")
                except UnicodeDecodeError:
                    detail = "nu e UTF-8 valid in container"
            findings.append(
                {
                    "check": where,
                    "ok": in_box == on_disk and not detail,
                    "chars": len(in_box),
                    "detail": detail,
                }
            )

        # The frontmatter is what the platform renders the skills index from, so
        # a skill whose description did not survive the mount is a skill the
        # model has no reason to open - unreachable without anything failing.
        for folder in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
            skill_md = folder / "SKILL.md"
            if not skill_md.is_file():
                continue
            _, description, _ = parse_skill(skill_md)
            findings.append(
                {
                    "check": f"descriere:{folder.name}",
                    "ok": bool(description.strip()),
                    "chars": len(description),
                    "detail": "",
                }
            )
    finally:
        await session.aclose()

    failures = [f for f in findings if not f["ok"]]
    for f in findings:
        mark = "OK " if f["ok"] else "NU "
        print(mark, f"{f['check']:<52}", f"{f['chars']:>6} octeti", f["detail"])

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"fidelity-{stamp}.json"
    out.write_text(
        json.dumps({"generated_at": stamp, "findings": findings}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    passed = len(findings) - len(failures)
    print(f"\nfidelitate: {passed}/{len(findings)} · {out.relative_to(ROOT)}")
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
