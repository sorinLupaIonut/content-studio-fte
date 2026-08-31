"""The method as files, in a container the model may read but not change.

WHY THIS SHAPE. Rule 4 says the method lives in `skills/<name>/SKILL.md` plus
`references/`, edited without touching code. Between 2026-08-24 and 2026-08-27
it was *delivered* two other ways - one tool per skill plus a `citeste-referinta`
tool, and, on the generation path, assembled into the prompt ahead of the call.
Both worked. Both were ours to maintain, and the second one duplicated a table
the skill body already carried ("o ceri de fiecare data la Reel"), which is the
kind of second copy this project has already paid for once.

Sorin chose the standard shape on 2026-08-27: the SDK's own `Skills` capability,
skills as real directories under `.agents/`, discovered and opened by the model
itself. Nothing here invents a tool. The three steps of progressive disclosure
are the platform's now:

  1. the frontmatter `description` of every skill is rendered into the system
     prompt as an index, by `Skills.instructions`;
  2. the model opens `SKILL.md` with the shell when the task matches;
  3. the body names a `references/` file and the model opens that too.

WHAT IT COSTS, MEASURED 2026-08-27 on gpt-5-mini, five hooks for one Reel idea:
11 requests and 87,302 input tokens, against 26,250 input and one request for
the same shape preloaded. The container is a real bill and the turns are a real
bill. That is the trade, made with the numbers on the table.

WHAT IT BUYS BACK. Everything the model can reach is in `skills/`, and it is
reached the way the file is written - so a reference the body stops mentioning
stops being read, without a Python table having to be edited to agree.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agents.extensions.sandbox.e2b import E2BSandboxClient, E2BSandboxClientOptions
from agents.run_config import SandboxRunConfig
from agents.sandbox import Manifest
from agents.sandbox.capabilities import Shell, Skills
from agents.sandbox.entries import LocalDir

from content_studio.config import (
    E2B_API_KEY,
    SANDBOX_TIMEOUT_SECONDS,
    SKILLS_DIR,
    MissingConfig,
)

logger = logging.getLogger("content_studio.sandbox")

#: Where the skills land inside the container. `.agents` is the SDK's own
#: auto-discovery root; the model is told the path by `Skills.instructions`, so
#: nothing this project writes needs to repeat it.
SKILLS_PATH = ".agents"

#: The SDK's shell tool. Since the method moved back into the sandbox on
#: 2026-08-27 this is the ONLY way a `SKILL.md` or a `references/` file reaches
#: the model, which makes it the only call name worth reading when the question
#: is "did this run open the method".
#:
#: It lives here rather than in the eval that first needed it, because three
#: readers now ask that question - `audit.py` for the trail, `generator.py` for
#: its warning, and `evals/route/` for the grade - and the day they disagree
#: about the name is the day one of them silently answers "no" forever.
SHELL_TOOL_NAME = "exec_command"


#: What replaces the SDK's default sandbox prompt, and it is not an optimisation.
#: `agents/sandbox/instructions/prompt.md` is Codex's coding-agent prompt - 16.9 KB
#: of personality, "AGENTS.md spec", preamble messages, "presenting your work",
#: final-answer style guidelines. Handed to an agent that writes Instagram posts
#: for a Romanian life coach and answers through a structured contract, it does
#: not merely waste ~4.2k tokens a request: it actively instructs the opposite of
#: what `BASE_INSTRUCTIONS` and the generation schemas ask for.
#:
#: Romanian and untranslated, like everything the model reads. Short on purpose -
#: the Shell capability appends its own note about `exec_command`, and the runtime
#: appends the filesystem tree, so this only has to say what those two cannot:
#: that the container is a library, not a workshop.
#:
#: `cat`, AND THE EXAMPLE IS THE WHOLE POINT. Until 2026-08-28 this said "de
#: exemplu `sed -n '1,200p' fișier`" - and the model copied it verbatim, every
#: run. That was harmless while `propune-postari/SKILL.md` was 226 lines and
#: cost nothing to notice, because it truncated below the end of the file. The
#: same day the file grew to 245 lines and a live run read `1,200p`: steps 5, 6
#: and 7 never reached the model - the focus rule, "fără hook-uri în faza asta",
#: and "înainte să le predai, numără. Zece, nu nouă". NOTHING RAISED. The batch
#: came back with ten well-formed proposals because the schema enforces the ten
#: and the archetypes, so the only visible trace of a half-read method was the
#: line range in the span. An example that teaches a truncating command is a
#: bug with a very long fuse.
SANDBOX_INSTRUCTIONS = """\
You are working inside a Linux container. Your method is there, in files, under
`.agents/` — one folder per skill, with `SKILL.md` and, where there is one,
`references/`.

You read them with `exec_command`, like this: `cat file`. WHOLE, in one go. You
do not read a range of lines and you do not stop at a round number — a file read
halfway is method applied halfway, and the missing part does not announce that
it is missing. You do not go looking for it across the container and you do not
guess what it says.

You ask for everything you need AT ONCE, in the same turn. Several files fit in
one command — `cat file1 file2` — and the tools go out in parallel with the
reading and with each other. What you have to fetch you know from the request,
from the start: do not wait for the first thing to come back before asking for
the second. Every extra turn is an extra trip, and the trips run out before your
patience does — a model that fetches one at a time ends up writing with half the
material.

The container is a library, not a workshop: you do not write files, you do not
install anything, you do not run programs. You have no internet there — you
reach data through your tools, never from the shell.

You write no preambles, you do not announce what you are about to do, and you do
not summarise your work at the end. You answer exactly what was asked, in the
form asked for."""


def skills_capability() -> Skills:
    """The skill tree, mounted from disk.

    `from_` rather than `lazy_from`: lazy mode buys a `load_skill` round trip to
    avoid materialising folders that may not be used, and this project has two
    skills totalling 114 KB. Paying a turn to defer a copy that costs nothing is
    the same bad trade the preloaded path was removed for, pointing the other
    way. Read at call time, so a skill edited on disk reaches the next sandbox
    without a restart - the contract rule 4 has always had.
    """
    if not SKILLS_DIR.is_dir():
        raise MissingConfig(f"The skills folder does not exist: {SKILLS_DIR}")
    return Skills(from_=LocalDir(src=SKILLS_DIR), skills_path=SKILLS_PATH)


def capabilities() -> list[Shell | Skills]:
    """Shell and Skills, and deliberately nothing else.

    `Capabilities.default()` is Filesystem + Shell + Compaction. Filesystem
    contributes `view_image` and `apply_patch` - an agent that writes captions
    has no use for either, and `apply_patch` would let it edit the method it is
    supposed to be reading. Compaction summarises long histories, which the
    generation runs do not have (they are stateless) and the chat path handles
    its own way. Shell is what reads a file; Skills is what indexes them.
    """
    return [Shell(), skills_capability()]


def sandbox_manifest() -> Manifest:
    """The container's filesystem, with the skills already in it.

    NOT OPTIONAL, AND THE FAILURE IS SILENT. The runtime only runs the
    capabilities' `process_manifest` when a manifest exists - agent default, or
    run config. With neither, the sandbox comes up empty, the skills index is
    absent from the prompt, and the model spends its turns running `find` over
    an empty `/workspace` before answering from memory. That is exactly what the
    first spike on 2026-08-27 did, and nothing raised.
    """
    manifest = Manifest()
    for capability in capabilities():
        manifest = capability.process_manifest(manifest)
    return manifest


def sandbox_options() -> E2BSandboxClientOptions:
    """How the container is created.

    `allow_internet_access=False` because nothing inside needs it: the books,
    the profile and the posts are reached by THIS process through the
    `content-data` MCP server (rule 1), never from the shell. A sandbox that can
    reach the network is a shell the model can post from.
    """
    return E2BSandboxClientOptions(
        sandbox_type="e2b",
        timeout=SANDBOX_TIMEOUT_SECONDS,
        allow_internet_access=False,
        secure=True,
    )


@asynccontextmanager
async def sandbox_run_config(label: str) -> AsyncIterator[SandboxRunConfig]:
    """One container, for as many runs as the caller puts inside the block.

    This used to say "a batch is eleven runs - one for the titles, ten for the
    details - and they share this one". It is not, and has not been since the
    details became lazy: a batch IS the titles run, and each detail is a separate
    run minutes or days later, with its own container. `generator._run_agent`
    opens the block per run for exactly that reason. The block still takes more
    than one run where a caller has more than one - the end-to-end check walks
    five turns inside a single container - which is why this is a context manager
    rather than a decorator on the run.

    Measured 2026-08-27: a container comes up in 0.35-1.17s and closes in 0.25s,
    which is small next to the model call it serves.

    The session is passed live rather than as `client` + `options`, which is what
    makes the runtime reuse it instead of creating its own; `owns_session=False`
    then keeps `Runner` from closing what it did not open.
    """
    if not E2B_API_KEY:
        raise MissingConfig(
            "E2B_API_KEY is missing: the method is read from a sandbox, and"
            " without the key none can be started."
        )
    client = E2BSandboxClient()
    session = await client.create(manifest=sandbox_manifest(), options=sandbox_options())
    # `create` builds the container and records the manifest; it does NOT copy
    # the files in. The runtime does that when it attaches a live session, so a
    # run would work without this line - and anything that touches the container
    # without going through `Runner` would find it empty, which is how
    # `evals/route/fidelity.py` first reported ten missing files against a mount that
    # was fine. Furnishing it here means the container is only ever handed over
    # in one state: ready.
    await session.apply_manifest()
    logger.info("sandbox %s: pornit", label)
    try:
        yield SandboxRunConfig(session=session)
    finally:
        # Never let closing a container fail a batch that already produced its
        # posts. The container expires on its own timeout anyway; a raise here
        # would turn a cleanup problem into a lost lot.
        try:
            await session.aclose()
            logger.info("sandbox %s: inchis", label)
        except Exception:  # noqa: BLE001 - cleanup must not mask the real result
            logger.warning("sandbox %s: nu s-a putut inchide", label, exc_info=True)
