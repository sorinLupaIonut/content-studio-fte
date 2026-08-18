"""Optional debugger attachment, for the processes an editor cannot launch.

Locally you do not need this: VS Code starts the harness and the MCP server
itself, so `F5` already owns the process and breakpoints just work. This module
exists for the two cases where the debugger cannot be the launcher — a service
already running in a terminal, and, the one this project is heading towards, a
service running inside a container.

The listener is opt-in and silent by default: with no `DEBUGPY_PORT` in the
environment `attach_if_requested` returns after one `os.getenv`, which is why it
is safe to leave in the startup path of both entry points rather than wrapping
each call site in a condition.

    docker run -e DEBUGPY_PORT=5678 -p 5678:5678 …

then pick **Attach to a running process** in the editor. Add `DEBUGPY_WAIT=1`
when the bug is in startup itself and the process would otherwise be past it
before you connect.

One flag belongs on the interpreter, not here: start it as `python -X
frozen_modules=off -m …`. CPython ships frozen copies of the import machinery,
and a breakpoint in a module reached through them can silently fail to bind.
The warning debugpy prints about it is easy to read as noise; it is not.
"""

from __future__ import annotations

import os

#: The port the listener binds. Absent — the normal case — means no listener.
DEBUGPY_PORT_VAR = "DEBUGPY_PORT"

#: Block the process until the editor attaches. Only useful for startup bugs.
DEBUGPY_WAIT_VAR = "DEBUGPY_WAIT"

_TRUTHY = {"1", "true", "yes", "da"}


def attach_if_requested(label: str) -> bool:
    """Open a debugpy listener if the environment asked for one.

    Returns whether a listener is now running. Every failure is reported and
    then swallowed: a typo in an env var must not take down a service that was
    going to run fine without a debugger.
    """

    port = os.getenv(DEBUGPY_PORT_VAR, "").strip()
    if not port:
        return False

    try:
        import debugpy
    except ModuleNotFoundError:
        print(f"{label}: {DEBUGPY_PORT_VAR} is set but debugpy is not installed "
              f"(uv sync --dev). Starting without a debugger.", flush=True)
        return False

    try:
        # Bound on every interface, not on loopback. Inside a container the
        # editor sits on the other side of a published port, and a listener on
        # 127.0.0.1 is unreachable from there. The port is only as exposed as
        # you chose to publish it.
        debugpy.listen(("0.0.0.0", int(port)))
    except Exception as exc:  # noqa: BLE001 - never fatal, see the docstring
        print(f"{label}: could not open the debug port {port} "
              f"({type(exc).__name__}). Starting without a debugger.", flush=True)
        return False

    # `flush` on every line: stdout is a pipe under a container runtime and under
    # a launcher, and a buffered "waiting for the editor" message arrives after the
    # wait it was meant to announce.
    print(f"{label}: debugger listening on port {port}.", flush=True)
    if os.getenv(DEBUGPY_WAIT_VAR, "").strip().lower() in _TRUTHY:
        print(f"{label}: waiting for the editor to attach…", flush=True)
        debugpy.wait_for_client()
        print(f"{label}: editor attached.", flush=True)
    return True
