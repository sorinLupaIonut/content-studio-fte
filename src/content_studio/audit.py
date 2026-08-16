"""The action trail — Decision 8.

Architecture rule 2: the audit has its **own connection**, outside the MCP
boundary. So a separate engine from the worker's, not a borrowed one. The reason
is prosaic: if the business transaction dies, its trail has to survive.

What gets written, and where each row comes from:

    message_received     her message, before the run
    skill_activated      from the shell commands that open a SKILL.md
    capability_invoked   every MCP tool call, with arguments and result
    post_chosen          from the arguments of save_post
    proposals_generated  the turn that produced ten numbered proposals
    guardrail_tripped    the exception around Runner.run
    message_sent         the answer, after the run

`post_saved` is NOT written here — the MCP server writes it, in the same
transaction as the INSERT (rule 2, second half).

Nothing in this file is allowed to kill her turn: every write sits inside a `try`.
A lost trail row is damage; a conversation that died because the trail could not
be written would be foolish.
"""

from __future__ import annotations

import json
import re
import sys

from sqlalchemy.ext.asyncio import create_async_engine

#: The tools that cross the MCP boundary. The rest (`exec_command` and everything
#: sandbox-related) are system tools, not business capabilities.
MCP_TOOLS = {
    "search_books",
    "search_web",
    "list_posts",
    "save_post",
    "update_profile",
}

#: `.agents/propune-postari/SKILL.md` inside a shell command.
SKILL_PATTERN = re.compile(r"\.agents/([\w-]+)/SKILL\.md")

#: Ten proposals numbered at the start of a line.
NUMBERING_PATTERN = re.compile(r"^\s*(\d{1,2})[.)]", re.MULTILINE)

AUDIT_SQL = """
INSERT INTO audit_log (conversation_id, actor, action, target, payload, result)
VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
"""

CAPABILITY_SQL = """
INSERT INTO capability_invocations
       (conversation_id, capability, arguments, result, status)
VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
"""


def _json(x: object) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def _load(text: object) -> object:
    """Tool arguments arrive as a JSON string. If it is not JSON, keep it as is."""
    if isinstance(text, str):
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}
    return text if text is not None else {}


def calls_in(result) -> list[dict]:
    """The tool calls of one turn, with their arguments and results.

    Taken from `new_items` rather than from `RunHooks`: the hooks give you the
    tool but not the arguments it was called with, and a trail without arguments
    cannot be replayed.
    """
    calls: dict[str, dict] = {}
    order: list[str] = []

    for item in getattr(result, "new_items", []):
        raw = getattr(item, "raw_item", None)
        kind = getattr(item, "type", "")
        call_id = getattr(raw, "call_id", None) or getattr(raw, "id", None) or str(id(raw))

        if kind == "tool_call_item" and hasattr(raw, "name"):
            calls[call_id] = {
                "call_id": call_id,
                "name": raw.name,
                "arguments": _load(getattr(raw, "arguments", None)),
                "result": None,
            }
            order.append(call_id)
        elif kind == "tool_call_output_item" and call_id in calls:
            calls[call_id]["result"] = getattr(item, "output", None)

    return [calls[i] for i in order]


class Audit:
    """The audit connection. Opened once, when the worker starts."""

    def __init__(self, url: str, connect_args: dict) -> None:
        # `pool_pre_ping`: the trail is written rarely and far apart in time, which
        # makes it the most exposed to a connection Neon closed between two
        # messages. And a lost trail row does not come back.
        self._engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
        self._blocked_calls: set[tuple[str, str]] = set()

    async def _write(self, sql: str, *parameters) -> None:
        try:
            async with self._engine.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                await raw.execute(sql, *parameters)
        except Exception as e:  # noqa: BLE001 — a lost trail row does not stop the turn
            print(f"[audit] could not write: {type(e).__name__}: {e}", file=sys.stderr)

    async def action(
        self,
        conversation: str,
        action: str,
        target: str | None = None,
        payload: object = None,
        result: object = None,
        actor: str = "worker:content-studio",
    ) -> None:
        await self._write(
            AUDIT_SQL,
            conversation,
            actor,
            action,
            target,
            _json(payload if payload is not None else {}),
            _json(result) if result is not None else None,
        )

    async def message_received(self, conversation: str, message: str) -> None:
        await self.action(
            conversation, "message_received", "conversations", {"text": message}, actor="viorela"
        )

    async def message_sent(self, conversation: str, text: str) -> None:
        await self.action(conversation, "message_sent", "conversations", {"text": text})

    async def failed(self, conversation: str, e: Exception) -> None:
        await self.action(
            conversation,
            "guardrail_tripped",
            "Runner.run",
            {"type": type(e).__name__, "message": str(e)},
        )

    async def capability_blocked(
        self,
        conversation: str,
        name: str,
        arguments: object,
        reason: str,
        call_id: str,
    ) -> None:
        """Record the refused attempt and exclude it from the successful calls."""
        self._blocked_calls.add((conversation, call_id))
        result = {"status": "blocked", "reason": reason}
        await self.action(
            conversation, "capability_invoked", name, arguments, result
        )
        await self._write(
            CAPABILITY_SQL,
            conversation,
            f"tool:{name}",
            _json(arguments),
            _json(result),
            "blocked",
        )

    async def turn(self, conversation: str, result) -> None:
        """Everything that happened in one turn: skills opened, tools called."""
        skills = set()

        for call in calls_in(result):
            name, arguments = call["name"], call["arguments"]

            # Skills have no tool of their own: they are opened with shell, from
            # inside the sandbox. So activation is read from the command that ran,
            # not from a hook.
            for found in SKILL_PATTERN.finditer(_json(arguments)):
                skills.add(found.group(1))

            if name not in MCP_TOOLS:
                continue

            call_id = call["call_id"]
            if (conversation, call_id) in self._blocked_calls:
                self._blocked_calls.discard((conversation, call_id))
                continue

            await self.action(
                conversation, "capability_invoked", name, arguments, call["result"]
            )
            await self._write(
                CAPABILITY_SQL,
                conversation,
                f"tool:{name}",
                _json(arguments),
                _json(call["result"]),
                "ok",
            )

            # Which proposal she chose out of the ten — visible in what got saved.
            if name == "save_post" and isinstance(arguments, dict):
                await self.action(
                    conversation,
                    "post_chosen",
                    "posts",
                    {
                        "title": arguments.get("title"),
                        "hook_type": arguments.get("hook_type"),
                        "hook": arguments.get("hook"),
                    },
                )

        for skill in sorted(skills):
            await self.action(conversation, "skill_activated", skill, {"skill": skill})

        # The nine refused proposals are the best signal about her taste in the
        # whole system. Today they are lost on every run; here they stay.
        text = str(getattr(result, "final_output", "") or "")
        numbers = {int(n) for n in NUMBERING_PATTERN.findall(text) if 1 <= int(n) <= 10}
        if len(numbers) >= 8:
            await self.action(
                conversation,
                "proposals_generated",
                "propune-postari",
                {"proposals": text, "count": len(numbers)},
            )

    async def close(self) -> None:
        await self._engine.dispose()
