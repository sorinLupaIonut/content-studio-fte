"""Durable state: runs, traces, the trail — and the approval gate.

Decision 8 built this as the action trail. D4 made it more than that: it now owns
every table the course's `state.py` owns, `public.runs` included, so this is the
state layer and not only the audit. The name stayed; the scope grew.

Architecture rule 2: the audit has its **own connection**, outside the MCP
boundary. So a separate engine from the worker's, not a borrowed one. The reason
is prosaic: if the business transaction dies, its trail has to survive.

TWO CLASSES OF WRITE, and the difference matters more than it looks.

*The trail* may fail. Every trail write sits inside a `try` and prints to stderr
if it cannot land: a lost row is damage, but a conversation that died because the
trail could not be written would be foolish.

*The gate* may NOT fail silently. `suspend_run` and `resume_run` do not catch
anything — if the state cannot be persisted, the caller has to know, because the
alternative is telling her "waiting for your answer" while the run it belongs to
no longer exists anywhere. Rule 6 is the one rule this project cannot fudge.

WHAT CHANGED AT D4, and what it costs.

The trail used to be one wide table: conversation_id, actor, action from a CHECK
of thirteen values, target, payload, result. It is now the course's pair of
tables — `runs` for the turn itself and `audit_log(run_id, event)` for what
happened inside it — and `event` is free text.

So the vocabulary below is a **convention, not a constraint**. Nothing in the
database rejects a typo any more; `replay.py` reads these same constants back,
and that shared import is the only thing keeping the two ends in agreement.

Arguments and results are no longer stored. A row now says `capability_invoked:
save_post`, not which post or what came back. Where detail survives, it survives
because another table holds it: the post is in `public.posts`, the message and
the answer are `runs.input_message` and `runs.output_message`.

One turn = one run:

    open_run()      her message, BEFORE the model is called
    …events…        skills opened, tools called, the gate asked and answered
    close_run()     the answer, plus the trace, plus `run_completed`

A run whose `output_message` is still NULL is a turn that died on the way. That
used to be inferred by counting `message_received` against `message_sent`; it is
now a column, which is a better place for it.

Nothing in this file is allowed to kill her turn: every write sits inside a
`try`. A lost trail row is damage; a conversation that died because the trail
could not be written would be foolish.
"""

from __future__ import annotations

import json
import re
import sys
import uuid

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio.observability import bind_run

#: The tools that cross the MCP boundary. The rest (`exec_command` and everything
#: sandbox-related) are system tools, not business capabilities.
MCP_TOOLS = {
    "search_books",
    "search_web",
    "list_posts",
    "save_post",
    "save_posts_batch",
    "update_post",
    "update_profile",
}

#: The event vocabulary. A CHECK constraint until D4, a shared constant since —
#: `replay.py` imports these, which is what keeps writer and reader in step.
#: `post_saved` and `profile_updated` are written by the MCP server instead, in
#: the same transaction as the write itself (rule 2, second half).
RUN_COMPLETED = "run_completed"          # the course's own event
MESSAGE_RECEIVED = "message_received"
SKILL_ACTIVATED = "skill_activated"
CAPABILITY_INVOKED = "capability_invoked"
CAPABILITY_BLOCKED = "capability_blocked"
POST_CHOSEN = "post_chosen"
POST_SAVED = "post_saved"
POST_UPDATED = "post_updated"
PROFILE_UPDATED = "profile_updated"
PROPOSALS_GENERATED = "proposals_generated"
GUARDRAIL_TRIPPED = "guardrail_tripped"
APPROVAL_REQUESTED = "approval_requested"
APPROVAL_GRANTED = "approval_granted"
APPROVAL_REJECTED = "approval_rejected"
CORPUS_SEEDED = "corpus_seeded"
GENERATION_BATCH_CREATED = "generation_batch_created"
GENERATION_BATCH_FAILED = "generation_batch_failed"
GENERATION_TITLES_READY = "generation_titles_ready"
GENERATION_IDEA_STARTED = "generation_idea_started"
GENERATION_IDEA_READY = "generation_idea_ready"
GENERATION_IDEA_FAILED = "generation_idea_failed"
GENERATION_VARIANT_SELECTED = "generation_variant_selected"
GENERATION_VARIANT_PATCHED = "generation_variant_patched"
GENERATION_CANCELLED = "generation_cancelled"

#: `event` carries an optional subject after ": " — `capability_invoked: save_post`.
#: One free-text column has to answer "what happened" and "to what"; a separator
#: the reader agrees on is the cheapest way to get both back out.
SEPARATOR = ": "

#: `.agents/propune-postari/SKILL.md` inside a shell command.
SKILL_PATTERN = re.compile(r"\.agents/([\w-]+)/SKILL\.md")

#: Ten proposals numbered at the start of a line.
NUMBERING_PATTERN = re.compile(r"^\s*(\d{1,2})[.)]", re.MULTILINE)

# Every statement names its schema: the pooled endpoint is PgBouncer in
# transaction mode and gives no guarantee about `search_path` (D4).
SESSION_SQL = """
INSERT INTO public.agent_sessions (session_id) VALUES ($1)
ON CONFLICT (session_id) DO NOTHING
"""

OPEN_RUN_SQL = """
INSERT INTO public.runs (id, session_id, input_message, used_sandbox)
VALUES ($1, $2, $3, $4)
"""

CLOSE_RUN_SQL = """
UPDATE public.runs SET output_message = $2, status = 'completed' WHERE id = $1
"""

FAIL_RUN_SQL = "UPDATE public.runs SET status = 'failed' WHERE id = $1"

TRACE_SQL = "INSERT INTO public.traces (run_id, payload) VALUES ($1, $2::jsonb)"

EVENT_SQL = "INSERT INTO public.audit_log (run_id, event) VALUES ($1, $2)"

SESSIONS_TABLE_SQL = "SELECT to_regclass('public.agent_sessions')"

# ---- the gate ---------------------------------------------------------------
# `AND status = 'running'` is not decoration: it makes suspending idempotent and
# stops a second interruption from overwriting a run that is already parked.
SUSPEND_SQL = """
UPDATE public.runs
   SET status = 'pending', requests = $2::jsonb, state = $3,
       decisions = NULL, resolved_at = NULL, resolved_by = NULL
 WHERE id = $1 AND status = 'running'
RETURNING id
"""

PENDING_SQL = """
SELECT id, requests, state, created_at, input_message
  FROM public.runs
 WHERE session_id = $1 AND status = 'pending'
"""

# Back to `running`, so a run that stops at the gate a second time can be
# suspended again. `state` comes back out so the caller can deserialize it.
RESUME_SQL = """
UPDATE public.runs
   SET status = 'running', decisions = $2::jsonb,
       resolved_at = NOW(), resolved_by = $3
 WHERE id = $1 AND status = 'pending'
RETURNING state
"""


class GateError(RuntimeError):
    """The gate's state could not be written or read back."""


def event_name(kind: str, subject: object = None) -> str:
    """`capability_invoked: save_post`, or just `run_completed`."""
    if subject is None:
        return kind
    text = " ".join(str(subject).split())
    return f"{kind}{SEPARATOR}{text}" if text else kind


def split_event(event: str) -> tuple[str, str]:
    """The inverse of `event_name`: (kind, subject)."""
    kind, separator, subject = event.partition(SEPARATOR)
    return kind, subject if separator else ""


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
    tool but not the arguments it was called with. The arguments no longer reach
    the database, but they are still read here — the skill a command opened and
    the post that was chosen are both found inside them.
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
        self._sessions_table: bool | None = None

    async def _write(self, sql: str, *parameters) -> None:
        try:
            async with self._engine.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                await raw.execute(sql, *parameters)
        except Exception as e:  # noqa: BLE001 — a lost trail row does not stop the turn
            print(f"[audit] could not write: {type(e).__name__}: {e}", file=sys.stderr)

    async def open_run(
        self, session_id: str, message: str, used_sandbox: bool = True
    ) -> str | None:
        """Start the run and return its id, or None if it could not be written.

        The row goes in BEFORE the model is called. An audit written only at the
        end misses exactly the turns that most deserve explaining — and here it
        also means every event of the turn has a run to hang off.

        `agent_sessions` is the SDK's table and the foreign key's target, so the
        session row is ensured first. On a database where the SDK has not created
        it yet there is nothing to ensure, and no foreign key either.
        """
        run_id = str(uuid.uuid4())
        try:
            async with self._engine.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection

                if self._sessions_table is None:
                    self._sessions_table = await raw.fetchval(SESSIONS_TABLE_SQL) is not None
                if self._sessions_table:
                    await raw.execute(SESSION_SQL, session_id)

                await raw.execute(OPEN_RUN_SQL, run_id, session_id, message, used_sandbox)
        except Exception as e:  # noqa: BLE001
            print(f"[audit] could not open the run: {type(e).__name__}: {e}", file=sys.stderr)
            return None

        # From here on, every log line and every span in this task carries the
        # id, without a single call site passing it along.
        bind_run(run_id)
        await self.event(run_id, MESSAGE_RECEIVED)
        return run_id

    async def close_run(self, run_id: str | None, reply: str) -> None:
        """The answer, the trace, and the course's `run_completed`."""
        if run_id is None:
            return
        await self._write(CLOSE_RUN_SQL, run_id, reply)
        await self._write(TRACE_SQL, run_id, _json({"output": reply}))
        await self.event(run_id, RUN_COMPLETED)

    async def event(self, run_id: str | None, kind: str, subject: object = None) -> None:
        """One row in the trail. `run_id` may be None for what happens outside a run."""
        await self._write(EVENT_SQL, run_id, event_name(kind, subject))

    async def failed(self, run_id: str | None, e: Exception) -> None:
        """The turn died. `output_message` stays NULL, which is the visible half."""
        if run_id is not None:
            await self._write(FAIL_RUN_SQL, run_id)
        await self.event(run_id, GUARDRAIL_TRIPPED, type(e).__name__)

    # ---- the approval gate --------------------------------------------------
    #
    # These three are what makes rule 6 survive a process that has no terminal.
    # Unlike everything above, they let their exceptions out: see the module
    # docstring.

    async def suspend_run(self, run_id: str, requests: list[dict], state: str) -> None:
        """Park an interrupted run: what it wants to do, and how to continue it.

        `requests` is one entry per interruption — a run can stop on several tool
        calls at once, and all of them have to be answered before it resumes.
        `state` is `RunState.to_string()`.

        Raises GateError if the row was not updated, which means either the run
        is not `running` (already parked, already finished) or it does not exist.
        Either way the caller must not tell her the agent is waiting.
        """
        try:
            async with self._engine.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                parked = await raw.fetchval(SUSPEND_SQL, run_id, _json(requests), state)
        except Exception as e:  # noqa: BLE001 — re-raised as our own, never swallowed
            raise GateError(f"could not park run {run_id}: {type(e).__name__}: {e}") from e

        if parked is None:
            raise GateError(
                f"run {run_id} was not in `running`, so it could not be parked at "
                "the gate. Nothing is waiting for an answer."
            )
        await self.event(run_id, APPROVAL_REQUESTED, ", ".join(
            str(r.get("tool_name", "?")) for r in requests
        ))

    async def pending_run(self, session_id: str) -> dict | None:
        """The one run of this session waiting at the gate, or None.

        At most one can exist: `idx_runs_one_open_per_session` is a unique index
        over `status = 'pending'`, so this is a fact about the database rather
        than a convention this code maintains.

        Returns a plain dict with `requests` already decoded. That last part is
        not politeness — it hides a trap. asyncpg on its own hands JSONB back as
        a **string**, but SQLAlchemy's asyncpg dialect registers a JSON codec on
        every connection it manages, so the same column comes back as a **list**
        here. Code written against one and run against the other breaks on a
        `json.loads` that suddenly gets a list. Callers get the decoded value
        either way.
        """
        try:
            async with self._engine.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                row = await raw.fetchrow(PENDING_SQL, session_id)
        except Exception as e:  # noqa: BLE001
            raise GateError(f"could not read the gate: {type(e).__name__}: {e}") from e

        if row is None:
            return None
        return dict(row) | {"requests": _load(row["requests"]) or []}

    async def resume_run(
        self, run_id: str, decisions: list[dict], resolved_by: str
    ) -> str:
        """Record her answer and hand back the state string to continue from.

        `decisions` is one entry per request: `{call_id, approved, reason}`. The
        run goes back to `running`, so it can stop at the gate again later in the
        same turn — which is the normal case when the agent wants two writes.
        """
        try:
            async with self._engine.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                state = await raw.fetchval(
                    RESUME_SQL, run_id, _json(decisions), resolved_by
                )
        except Exception as e:  # noqa: BLE001
            raise GateError(f"could not resume run {run_id}: {type(e).__name__}: {e}") from e

        if state is None:
            raise GateError(
                f"run {run_id} was not waiting at the gate — already answered, or gone."
            )

        for decision in decisions:
            await self.event(
                run_id,
                APPROVAL_GRANTED if decision.get("approved") else APPROVAL_REJECTED,
                decision.get("tool_name"),
            )
        return state

    async def capability_blocked(self, run_id: str | None, name: str, call_id: str) -> None:
        """Record the refused attempt and exclude it from the successful calls.

        The reason the gate gave is no longer stored — the old table had a
        `result` column for it and this one does not. What survives is that the
        call was refused, and which tool it was.
        """
        self._blocked_calls.add((str(run_id), call_id))
        await self.event(run_id, CAPABILITY_BLOCKED, name)

    async def turn(self, run_id: str | None, result) -> None:
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

            if (str(run_id), call["call_id"]) in self._blocked_calls:
                self._blocked_calls.discard((str(run_id), call["call_id"]))
                continue

            await self.event(run_id, CAPABILITY_INVOKED, name)

            # Which proposal she chose out of the ten. The title is all that fits
            # now, and it is the part you would look for anyway.
            if name == "save_post" and isinstance(arguments, dict):
                await self.event(run_id, POST_CHOSEN, arguments.get("title"))

        for skill in sorted(skills):
            await self.event(run_id, SKILL_ACTIVATED, skill)

        # The nine refused proposals are the best signal about her taste in the
        # whole system. Their text lives in `runs.output_message`; this row is the
        # marker that says the turn was a proposal round.
        text = str(getattr(result, "final_output", "") or "")
        numbers = {int(n) for n in NUMBERING_PATTERN.findall(text) if 1 <= int(n) <= 10}
        if len(numbers) >= 8:
            await self.event(run_id, PROPOSALS_GENERATED, len(numbers))

    async def close(self) -> None:
        await self._engine.dispose()
