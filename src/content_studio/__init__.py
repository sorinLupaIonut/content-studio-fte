"""Content Studio FTE — a digital content worker for one coaching business.

Layout:

    config          environment, paths, DATABASE_URL normalization
    worker          the agent and the conversation loop (entry point)
    audit           the replayable trail, on its own connection
    conversation    the cover sheet of a conversation: status and summary
    replay          reconstructs a past conversation without calling the model
    mcp_server      the `content-data` MCP server: five tools, one resource
    db              schema, migrations and the importers that fill it

Everything the model reads at runtime — the system prompt in `worker.py`, the
tool descriptions in `mcp_server/server.py`, and every file under `skills/` — is
written in Romanian, because the agent works in Romanian for a Romanian client.
Everything a developer reads is in English.
"""

from __future__ import annotations

import sys

__version__ = "0.1.0"


def enable_utf8_output() -> None:
    """Make stdout and stderr UTF-8, whatever the console default is.

    The Windows console is cp1252 and every answer this project prints is
    Romanian. Without this, the first "ș" in a proposal kills the run with
    `UnicodeEncodeError`. Called by each entry point, before anything prints.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
