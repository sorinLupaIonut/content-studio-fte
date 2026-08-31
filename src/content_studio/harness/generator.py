"""Title-first generation with durable MCP drafts and bounded concurrency."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import unicodedata
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from agents import ModelSettings, RunHooks, Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig

from content_studio.audit import Audit, calls_in
from content_studio.config import (
    GENERATION_TITLE_MODEL,
    MODEL,
    MissingConfig,
)
from content_studio.harness.conversations import (
    ConversationLog,
    dictated_develop,
    dictated_select,
    rendered_titles,
    rendered_variants,
)
from content_studio.harness.drafts import GenerationDraftClient
from content_studio.harness.errors import RefusalError
from content_studio.harness.generation import (
    GenerationBatchRequest,
    GenerationStartRequest,
    IdeaTitle,
    ProposedIdeas,
    StreamEvent,
    detail_output_type,
    detail_prompt,
    public_batch,
    title_prompt,
)
from content_studio.language import DEFAULT_LANGUAGE, Language
from content_studio.observability import bind_run
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import (
    build_worker,
    read_profile,
)

#: How long one generation run may take before it is abandoned.
#:
#: Ten minutes was right when the method arrived preloaded and the run was a
#: single call. It is not right now: a Reel detail run opens SKILL.md and the
#: four references the body names, reads them in chunks, and only then writes
#: five variants with 900-1400 character captions. Measured 2026-08-27, the
#: first live one on this shape hit 600s, was abandoned, and succeeded on the
#: retry - so the timeout was costing a whole run's tokens and then paying for
#: a second one. Twenty minutes is above what was measured and still bounded.
RUN_TIMEOUT_SECONDS = 1_200

#: Every run in a batch - the title pass, the ten detail passes and any retry -
#: carries this workflow name and the batch id as its group. The runs already
#: shared one trace, because the trace context propagates into the tasks spawned
#: under it; what they did not share was a name, so a lot read as a dozen nested
#: spans all called "Agent workflow" and there was no way to tell a lot from the
#: run of a single idea. Note that `group_id` does NOT become Phoenix's
#: `session.id` - checked on 2026-08-23, Sessions stayed at 0 - it is a
#: correlation field, nothing more. Read by whoever is debugging, so English.
GENERATION_WORKFLOW = "Generation batch"


def workflow_name(batch_id: str) -> str:
    """`Generation batch 8e99b137` - one name per batch, shared by its 11 runs.

    A constant name was the whole story in Phoenix: every batch anybody had ever
    run appeared under the same title, so telling this morning's from this
    afternoon's meant opening traces one by one and reading timestamps. The batch
    id is the only thing that separates them, and `group_id` does not carry it
    into Phoenix - see the note above. So it goes in the name.

    Short prefix rather than the whole UUID: eight hex characters are unique
    enough among a day's batches and still fit in a list column. The same
    truncation is what `evals/route/references.py` and the audit print, so the id you
    read in Phoenix is the id you paste into a query.
    """

    return f"{GENERATION_WORKFLOW} {batch_id[:8]}"

#: The prompt cache is MATCHED on the prefix but ROUTED on this key, and the
#: routing was the actual leak. Measured on 2026-08-23: four detail calls fired
#: 175ms apart, before any of them had returned. Two landed on a machine that
#: still held the prefix from a batch thirty-one minutes earlier and read 64%
#: and 97% of it; two landed cold and paid full price for ~18k tokens each. That
#: is a lottery, not a cold start, and a stable key ends it.
#:
#: Stable ACROSS batches, deliberately. A key built from the batch id would send
#: every batch to a fresh machine and throw away exactly the half-hour-old warmth
#: the measurement found.
#:
#: KEYED ON THE MODEL, not on the phase. A cache entry belongs to one model's
#: weights, so two phases on different models can never share one - but since a
#: skill became a tool the two phases build the SAME instructions, and on the
#: same model that is one prefix, written once and read eleven times. Keying by
#: phase would have split it back in two and paid the cold miss twice.
#:
#: THE KNOWN TENSION, so nobody has to rediscover it: the documented guidance is
#: roughly fifteen requests per minute per key, and a batch does about forty
#: three. Above that some requests may miss. One key is still the right first
#: move - it is the only arrangement in which a cold batch pays for ONE miss
#: rather than one per machine - and it is now measurable, because
#: `usage_events.cached_input_tokens` records what actually happened. If the hit
#: rate falls below the 94.8% measured here, partition: one key per slot index,
#: still stable across batches.
def cache_key(model: str, shape: str = "") -> str:
    """The prompt-cache routing key for one model's generation calls.

    `shape` names what else the prefix depends on, and since 2026-08-27 nothing
    does: the method is read from files inside the sandbox, so the system prompt
    is identity + notes + skills index + profile, byte-identical for both phases
    and all three formats. One key per model is therefore the widest prefix that
    can be shared - the opposite of the preloaded shape, where a Reel batch and
    a Carusel batch on one key each evicted the other. The parameter stays
    because the callers know which phase they are, and a key that silently
    ignored a shape would be worse than one that never took it.
    """
    suffix = f"-{shape}" if shape else ""
    return f"content-studio-generation-{model}{suffix}"

#: How many times the model may go round before it has to answer.
#:
#: Six was right when the method arrived preloaded: read the prompt, write. It
#: is not right now. A Reel detail run opens `SKILL.md` and then the four
#: references the body names, and it reads them in chunks - measured 2026-08-27,
#: ten `exec_command` calls before the first line of a caption. A limit that
#: cuts the run off mid-method turns a cost into a failure, which is the worst
#: of both. Twenty is above anything measured and still bounded.
GENERATION_MAX_TURNS = 20

#: What a shell command has to mention for the method to count as opened. Asked
#: while the run is still in hand; the half that asked it afterwards off
#: `public.traces` (`evals/runs/`) was removed on 2026-08-30, so this is the only
#: place the question is asked today.
METHOD_MARKERS = ("SKILL.md", "references/")


# `safe_generation_error` deliberately hands the client a short code and, where
# there is nothing better to say, the exception class name - she must never read
# a stack trace. The operator still needs one, so both boundaries below log it
# here. Second half of D7; the first was the 502 handler in service.py.
#
# IT RETURNS A CODE AND NOT A SENTENCE, and that is the one thing to keep. The
# value is written to `generation_ideas.last_error` and the card prints that
# column verbatim - the only client-facing string in the harness with no
# language safety net in front of it. A Romanian sentence stored there in
# March is still Romanian when an English page reads it in June. A code
# survives the round trip through the database; a sentence does not.
# `Values.GenerationError` chooses the words, and passes an unrecognised value
# through unchanged, which is what keeps the rows written before 2026-08-31
# readable.
logger = logging.getLogger("content_studio.harness.generator")


class ActiveBatchError(RefusalError):
    """A principal must explicitly replace their current draft."""


class GenerationAccessError(RefusalError):
    """A batch or variant does not belong to the authenticated principal."""


def safe_generation_error(exc: BaseException) -> str:
    """Return a stable code for the failure, naming no account, prompt or source."""

    name = type(exc).__name__
    message = str(exc).lower()
    if "rate limit" in message or name == "RateLimitError":
        return "rate_limit"
    if "invalid json" in message or "structured output" in message:
        return "structured_output"
    if "max turns" in message:
        return "max_turns"
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    # She read `Generarea a eșuat (MissingConfig)` on 2026-08-31 and it told her
    # nothing: not what broke, not whether it was her doing, not whether trying
    # again would help. It is the one failure here that no retry can clear.
    if isinstance(exc, MissingConfig):
        return "missing_config"
    return f"failed:{name}"


def retryable_generation_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("rate limit", "invalid json", "structured output", "timeout")
    ) or isinstance(exc, asyncio.TimeoutError)


#: The punctuation a model swaps without meaning to. A title written
#: `„Ritualul de 60 de secunde"` and sent back as `"Ritualul de 60 de secunde"`
#: is the same title; the strict equality that guarded this until 2026-08-31
#: called it a different idea and threw away five variants that had already been
#: written and paid for. It happened once in production, on a Carusel.
#:
#: THE ORDINAL IS THE IDENTITY; THE TITLE IS AN ECHO. `idea_ordinal` says which
#: of the ten this is, and it stays exact - a wrong one means the model developed
#: the wrong idea, which is a real fault worth losing the run over. The title is
#: the same string handed back, so it is worth checking that the model did not
#: invent a different idea for the slot, and not worth losing the run over a
#: quotation mark. Both halves of that sentence are the reason this is a fold and
#: not a `==`, and the reason it is not simply deleted either.
_TYPOGRAPHY = (
    {ord(ch): '"' for ch in "\u201e\u201c\u201d\u00ab\u00bb"}
    | {ord(ch): "'" for ch in "\u2018\u2019"}
    | {ord(ch): "-" for ch in "\u2013\u2014\u2212"}
    | {ord("\u2026"): "..."}
)


def same_title(written: str, stored: str) -> bool:
    """The same title, allowing for punctuation the model re-typed its own way."""

    def fold(text: str) -> str:
        folded = unicodedata.normalize("NFC", text).translate(_TYPOGRAPHY)
        return " ".join(folded.split()).casefold()

    return fold(written) == fold(stored)


def describe_batch(request: GenerationBatchRequest) -> str:
    """What was asked for, as one line, for `runs.input_message`.

    Romanian and readable, because this is the column a person reads in
    `replay.py` when they want to know what a run was even about.
    """
    parts = [f"10 idei · {request.pillar} · {request.source} · {request.format}"]
    if request.focus:
        parts.append(f"focus: {request.focus}")
    return " — ".join(parts)


#: What the interface calls each errand. The tool NAMES are the contract with
#: the model and never move; these are what a person reads, so they are codes
#: and `Copy.cs` chooses the words - the same rule as a refusal she reads.
ACTIVITY_CODES = {
    "search_books": "books",
    "search_web": "web",
    "exec_command": "method",
    "write_stdin": "method",
}


class ActivityLog:
    """The errands of one batch, while they happen. Append-only, and forgotten.

    Two rows per errand rather than one mutated row: a reader asks for
    everything after a sequence number, so a line that changed in place would
    never be sent again. `done` carries `of`, the sequence of the `running` line
    it finishes, and the interface pairs them.

    Bounded because it must be: a batch that somehow never ends must not grow a
    list until the process dies. Old lines fall off the front; the interface has
    already drawn them.
    """

    def __init__(self, keep: int = 60) -> None:
        self._lines: deque[dict[str, Any]] = deque(maxlen=keep)
        self._sequence = 0

    def started(self, tool_name: str) -> int:
        self._sequence += 1
        self._lines.append(
            {
                "seq": self._sequence,
                "code": ACTIVITY_CODES.get(tool_name, "tool"),
                "tool": tool_name,
                "state": "running",
            }
        )
        return self._sequence

    def finished(self, of: int, *, empty: bool) -> None:
        self._sequence += 1
        self._lines.append(
            {
                "seq": self._sequence,
                "of": of,
                "state": "done",
                "empty": empty,
            }
        )

    def since(self, sequence: int) -> list[dict[str, Any]]:
        return [line for line in self._lines if line["seq"] > sequence]

    @property
    def sequence(self) -> int:
        return self._sequence


class _MeteredRun(RunHooks):
    """Keep hold of the run context so a FAILED run can still be metered.

    WHY NOT `exception.run_data`. That is where the SDK puts the context when a
    run raises, and it is where this started. It does not survive: for a
    structured-output failure `Runner.run` takes the redaction branch - see
    `agents/run.py`, `raise redacted_error from None` - which detaches
    `run_data` before the exception reaches any caller. Verified on 2026-08-24
    against a live batch: the handler fired on all six failures and found
    `run_data` None every time.

    The hook is called on every model response, before anything can fail, and
    `context` is the same `RunContextWrapper` the success path reads `usage`
    off. So this holds the object rather than a copy of the numbers, and
    whatever the run managed to spend before it broke is on it.

    """

    def __init__(self, activity: ActivityLog | None = None) -> None:
        self.context: Any | None = None
        self._activity = activity
        # Keyed by the tool object: the SDK hands back the same instance on end,
        # and a run makes several calls to one tool - `search_books` twice is two
        # rows, so a name would collide where an identity does not.
        self._open: dict[int, int] = {}

    async def on_llm_start(self, context, agent, *args, **kwargs) -> None:  # noqa: ARG002
        self.context = context

    async def on_llm_end(self, context, agent, response) -> None:  # noqa: ARG002
        self.context = context

    async def on_agent_start(self, context, agent) -> None:  # noqa: ARG002
        self.context = context

    async def on_agent_end(self, context, agent, output) -> None:  # noqa: ARG002
        self.context = context

    async def on_tool_start(self, context, agent, tool) -> None:  # noqa: ARG002
        if self._activity is not None:
            self._open[id(tool)] = self._activity.started(getattr(tool, "name", "tool"))

    async def on_tool_end(self, context, agent, tool, result) -> None:  # noqa: ARG002
        if self._activity is None:
            return
        started = self._open.pop(id(tool), None)
        if started is None:
            return
        # "Came back with nothing" is worth showing: a search that returned no
        # passage is the difference between a run that had material and one that
        # wrote from memory, and it is invisible in a spinner.
        self._activity.finished(started, empty=not str(result or "").strip())

    def spent(self) -> Any | None:
        """Something shaped like a run result, for `Accounts.record_run`.

        A shim rather than a second metering path: `record_run` reads
        `result.context_wrapper.usage`, and giving it exactly that keeps one
        place deciding how a token becomes a micro-dollar.
        """
        if self.context is None:
            return None
        return SimpleNamespace(context_wrapper=self.context)


class GenerationCoordinator:
    """Own background batch tasks while all durable state remains in MCP."""

    def __init__(
        self,
        data_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        internal_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        accounts: Any | None = None,
        conversations: ConversationLog | None = None,
    ) -> None:
        self._data_mcp_factory = data_mcp_factory
        self._internal_mcp_factory = internal_mcp_factory
        # Optional so a test can build a coordinator without a meter behind it.
        self._accounts = accounts
        # Optional for the same reason. When present, every step of a batch is
        # spoken into the conversation the lot belongs to — the dictated user
        # sentence and the rendered result — so the chat window shows exactly
        # what the buttons did. Best-effort by contract: see `ConversationLog.witness`.
        self._conversations = conversations
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._principal_tasks: dict[str, UUID] = {}
        # One in-flight detail run per idea. A double click on a card is the
        # obvious way to pay twice for one idea, and the database status alone
        # does not stop it: both requests read `waiting` before either writes
        # `generating`.
        self._idea_tasks: dict[tuple[UUID, int], asyncio.Task[None]] = {}
        #: One activity log per batch, live only - see `ActivityLog`. Bounded
        #: in `activity_for`, because a process that never restarts would
        #: otherwise keep one entry per batch ever generated.
        self._activity: dict[str, ActivityLog] = {}

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for detail in list(self._idea_tasks.values()):
            detail.cancel()
        if self._idea_tasks:
            await asyncio.gather(*self._idea_tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._principal_tasks.clear()
        self._idea_tasks.clear()

    async def start(
        self,
        principal_id: str,
        start_request: GenerationStartRequest,
        trail: Audit | None = None,
        conversation_session_id: str | None = None,
    ) -> dict[str, Any]:
        request = GenerationBatchRequest.model_validate(
            start_request.model_dump(exclude={"replace_current", "language"})
        )
        # Resolved BEFORE the row is written, because the row is the record of
        # which model wrote the batch and neither door names one any more: the
        # chat agent never could, and the interface stopped choosing when the
        # picker came down. An unresolved `None` would reach
        # `generation_batches.model` and leave the batch attributable only to
        # whatever the deployment happened to default to that day.
        request = request.model_copy(update={"model": self._batch_model(request)})
        current = await self.current(principal_id, public=False)
        if current is not None and not start_request.replace_current:
            raise ActiveBatchError(
                "a current batch already exists; replacing it must be confirmed",
                "active_batch",
            )

        if start_request.replace_current:
            await self._cancel_principal_task(principal_id)

        session_id = self._session_id("generation", principal_id)
        data_mcp = self._data_mcp_factory(session_id)
        internal_mcp = self._internal_mcp_factory(session_id)
        try:
            await asyncio.gather(data_mcp.connect(), internal_mcp.connect())
            _, profile_md = await read_profile(data_mcp)
            drafts = GenerationDraftClient(internal_mcp)
            # Nothing is pre-collected or pre-resolved since 2026-08-27: the
            # agent brings its own material and picks its own books, with its
            # tools, following the skill. The column keeps its jsonb shape for
            # the old batches that were born with full packets.
            batch = await drafts.create(principal_id, request, {})
        finally:
            await asyncio.gather(
                data_mcp.cleanup(), internal_mcp.cleanup(), return_exceptions=True
            )

        batch_id = UUID(str(batch["id"]))

        # The run is opened HERE, before the task exists, for the same reason
        # `open_run` writes its row before the model is called: the id has to
        # exist for anything to hang off it. `open_run` also calls `bind_run`,
        # and `asyncio.create_task` copies the current context - so the
        # background task and every task it spawns inherit the id without a
        # single call site passing it. `_generate` binds again anyway; see there.
        #
        # Until 2026-08-23 this path opened no run at all. Costs were metered, so
        # budgets were right, but there was no `runs` row, no `public.traces`
        # (the processor drops a trace whose run is "-"), and `replay.py` could
        # not reconstruct a generation. Chat was covered; the product's main
        # feature was not.
        run_id = None
        if trail is not None:
            run_id = await trail.open_run(session_id, describe_batch(request))

        task = asyncio.create_task(
            self._generate(
                batch_id,
                principal_id,
                session_id,
                request,
                profile_md,
                start_request.language,
                trail,
                run_id,
                conversation_session_id,
            ),
            name=f"generation-{batch_id}",
        )
        self._tasks[batch_id] = task
        self._principal_tasks[principal_id] = batch_id
        task.add_done_callback(
            lambda done, value=batch_id, owner=principal_id: self._task_done(
                value, owner, done
            )
        )
        return public_batch(batch)

    async def current(
        self, principal_id: str, *, public: bool = True
    ) -> dict[str, Any] | None:
        session_id = self._session_id("generation-read", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            value = await GenerationDraftClient(internal).current(principal_id)
        finally:
            await internal.cleanup()
        return public_batch(value) if public and value is not None else value

    async def get(self, principal_id: str, batch_id: UUID) -> dict[str, Any]:
        raw = await self._get_raw(principal_id, batch_id)
        return public_batch(raw)

    async def library(self, principal_id: str) -> list[dict[str, Any]]:
        session_id = self._session_id("library", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            return await GenerationDraftClient(internal).library()
        finally:
            await internal.cleanup()

    async def select(
        self, principal_id: str, variant_id: UUID
    ) -> dict[str, Any]:
        session_id = self._session_id("generation-select", principal_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            result = await GenerationDraftClient(internal).select(
                variant_id, principal_id
            )
        finally:
            await internal.cleanup()

        # Her click, spoken into the conversation as the sentence she would
        # have typed. The store returns the idea's place and the hook's name
        # for exactly this line.
        if self._conversations is not None:
            batch_id = None
            with suppress(Exception):
                current = await self.current(principal_id, public=False)
                batch_id = None if current is None else str(current["id"])
            if batch_id is not None:
                conversation_session = None
                with suppress(Exception):
                    conversation_session = (
                        await self._conversations.session_for_batch(
                            principal_id, batch_id
                        )
                    )
                await self._conversations.witness(
                    conversation_session,
                    "user",
                    dictated_select(
                        int(result["idea_ordinal"]), str(result["hook_type"])
                    ),
                )
        return result

    async def variant_context(
        self, principal_id: str, variant_id: UUID
    ) -> dict[str, Any]:
        """Return one server-verified active variant as bounded chat context."""

        batch = await self.current(principal_id, public=False)
        if batch is None:
            raise GenerationAccessError(
                "there is no current batch for this target", "no_current_batch"
            )
        for idea in batch.get("ideas", []):
            for variant in idea.get("variants", []):
                if str(variant.get("id")) != str(variant_id):
                    continue
                if variant.get("status") != "ready":
                    raise GenerationAccessError(
                        "the chosen variant is not ready yet", "variant_not_ready"
                    )
                return {
                    "kind": "generation_variant",
                    "target_id": str(variant_id),
                    "batch_id": str(batch["id"]),
                    "format": batch["format"],
                    "pillar": batch["pillar"],
                    "source_mode": batch["source"],
                    "idea": {
                        "ordinal": idea["ordinal"],
                        "title": idea["title"],
                        "angle": idea["angle"],
                    },
                    "variant": {
                        key: variant.get(key)
                        for key in (
                            "hook_type",
                            "hook",
                            "script",
                            "caption",
                            "hashtags",
                            "cta",
                            "source",
                            "format_details",
                        )
                    },
                }
        raise GenerationAccessError(
            "the variant does not belong to the account's current batch",
            "variant_not_in_batch",
        )

    async def develop(
        self,
        principal_id: str,
        batch_id: UUID,
        ordinal: int,
        language: Language = DEFAULT_LANGUAGE,
        trail: Audit | None = None,
        dictate: bool = True,
    ) -> dict[str, Any]:
        """Write the five variants for ONE idea, because she asked for it.

        The batch used to write all ten as soon as the titles landed. That is
        the whole cost of a run - $0.0733 of a $0.0770 batch, measured on
        2026-08-24 - and she develops one. The other nine were paid for, stored,
        and never opened.

        Everything the run needs is read back off the batch rather than held in
        memory: the request and the model she
        chose. This can be called days later, from a different replica, and it
        has to produce the same thing the batch would have produced then.

        Returns the batch as the interface reads it, so the caller can render
        the new state without a second round trip.
        """
        raw = await self._get_raw(principal_id, batch_id)
        key = (batch_id, ordinal)
        running = self._idea_tasks.get(key)
        if running is not None and not running.done():
            # Not an error: a second click on a card that is already working is
            # a person being impatient, not a fault. Give back the current state.
            return public_batch(raw)

        idea = next(
            (
                item
                for item in raw.get("ideas", [])
                if int(item.get("ordinal", -1)) == ordinal
            ),
            None,
        )
        if idea is None:
            raise GenerationAccessError(f"the batch has no idea {ordinal}", "idea_not_in_batch")
        if idea.get("status") == "ready":
            return public_batch(raw)

        request = GenerationBatchRequest.model_validate(
            {
                "format": raw["format"],
                "pillar": raw["pillar"],
                "source": raw["source"],
                "focus": raw.get("focus"),
                "model": raw.get("model"),
            }
        )
        title = IdeaTitle(
            ordinal=ordinal,
            title=str(idea["title"]),
            angle=str(idea.get("angle") or idea["title"]),
        )

        run_id = None
        if trail is not None:
            run_id = await trail.open_run(
                self._session_id("generation-detail", principal_id),
                f"develop idea {ordinal} of batch {str(batch_id)[:8]}",
            )

        # The click becomes a sentence in the conversation, before the work
        # starts, exactly as if she had typed it. Only into the conversation
        # this batch was born in — an old batch developed late stays silent —
        # and only when a click asked (`dictate`): a chat request already put
        # her own words in the session.
        conversation_session = None
        if self._conversations is not None:
            with suppress(Exception):
                conversation_session = await self._conversations.session_for_batch(
                    principal_id, str(batch_id)
                )
            if dictate:
                await self._conversations.witness(
                    conversation_session,
                    "user",
                    dictated_develop(ordinal, title.title),
                )

        task = asyncio.create_task(
            self._develop_one(
                batch_id,
                principal_id,
                request,
                title,
                language,
                trail,
                run_id,
                conversation_session,
            ),
            name=f"generation-{batch_id}-idea-{ordinal}",
        )
        self._idea_tasks[key] = task
        task.add_done_callback(lambda _t, k=key: self._idea_tasks.pop(k, None))
        return public_batch(raw)

    async def _develop_one(
        self,
        batch_id: UUID,
        principal_id: str,
        request: GenerationBatchRequest,
        idea: IdeaTitle,
        language: Language,
        trail: Audit | None,
        run_id: str | None,
        conversation_session: str | None = None,
    ) -> None:
        if run_id is not None:
            bind_run(run_id)
        session_id = self._session_id("generation-detail", principal_id)
        data_mcp = self._data_mcp_factory(session_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await asyncio.gather(data_mcp.connect(), internal.connect())
            # Checked here rather than only when the batch starts: ten ideas
            # opened one at a time over an afternoon is ten separate decisions
            # to spend, and the gate has to stand in front of each of them.
            if self._accounts is not None:
                await self._accounts.require_budget()
            _, profile_md = await read_profile(data_mcp)
            agent = self._detail_agent(
                profile_md, data_mcp, request, language, batch_id
            )
            written = await self._generate_one_detail(
                batch_id,
                request,
                profile_md,
                idea,
                agent,
                GenerationDraftClient(internal),
                language,
                conversation_session,
            )
            # `_generate_one_detail` handles its own failure - it marks the idea
            # and tells the conversation - so nothing is raised here, and until
            # 2026-08-31 that meant the run was closed as `completed` while the
            # idea it produced said `failed`. The run log was the one place a
            # person looks to find out what happened, and it was answering with
            # the opposite of what happened.
            if trail is not None:
                with suppress(Exception):
                    if written:
                        await trail.close_run(run_id, idea.title)
                    else:
                        await trail.failed(
                            run_id, RuntimeError("the detail phase wrote nothing")
                        )
        except asyncio.CancelledError:
            if trail is not None:
                with suppress(Exception):
                    await trail.failed(run_id, RuntimeError("detail cancelled"))
            raise
        except BaseException as exc:  # noqa: BLE001 - background task boundary
            logger.exception("idea %s of batch %s failed", idea.ordinal, batch_id)
            if trail is not None:
                with suppress(Exception):
                    await trail.failed(run_id, exc)
            with suppress(Exception):
                await GenerationDraftClient(internal).fail_idea(
                    batch_id, idea.ordinal, safe_generation_error(exc), retryable=False
                )
        finally:
            await asyncio.gather(
                data_mcp.cleanup(), internal.cleanup(), return_exceptions=True
            )

    async def cancel(self, principal_id: str, batch_id: UUID) -> dict[str, Any]:
        await self._get_raw(principal_id, batch_id)
        session_id = self._session_id("generation-cancel", principal_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            result = await GenerationDraftClient(internal).cancel(
                batch_id, principal_id
            )
        finally:
            await internal.cleanup()

        task = self._tasks.get(batch_id)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return result

    async def events(
        self,
        principal_id: str,
        batch_id: UUID,
        sequence: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        session_id = self._session_id("generation-events", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        await internal.connect()
        drafts = GenerationDraftClient(internal)
        last_signature: str | None = None
        seen_ideas: dict[str, str] = {}
        last_heartbeat = time.monotonic()
        activity_at = 0
        try:
            while True:
                # Drained BEFORE the batch is read, so the last errands of a
                # run still go out on the pass that sees it finish and
                # returns. `.get`, never `activity_for`: a reader must not
                # bring a log into existence for a batch nothing is running.
                log = self._activity.get(str(batch_id))
                if log is not None and log.sequence > activity_at:
                    for line in log.since(activity_at):
                        sequence += 1
                        yield StreamEvent(
                            sequence=sequence,
                            event="activity",
                            batch_id=batch_id,
                            payload=line,
                        )
                    activity_at = log.sequence
                raw = await drafts.get(batch_id)
                self._ensure_owner(raw, principal_id)
                public = public_batch(raw)
                signature = self._batch_signature(public)
                if signature != last_signature:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event="status",
                        batch_id=batch_id,
                        payload={"batch": public},
                    )
                    last_signature = signature

                ideas = public.get("ideas", [])
                if ideas and not seen_ideas:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event="titles.ready",
                        batch_id=batch_id,
                        payload={"batch": public},
                    )

                for idea in ideas:
                    idea_id = str(idea["id"])
                    status = str(idea["status"])
                    previous = seen_ideas.get(idea_id)
                    seen_ideas[idea_id] = status
                    if status == previous:
                        continue
                    event = {
                        "ready": "idea.ready",
                        "failed": "idea.failed",
                    }.get(status)
                    if event is not None:
                        sequence += 1
                        yield StreamEvent(
                            sequence=sequence,
                            event=event,
                            batch_id=batch_id,
                            idea_id=UUID(idea_id),
                            payload={"idea": idea},
                        )

                batch_status = str(public.get("status"))
                terminal_event = {
                    "ready": "completed",
                    "failed": "error",
                    "cancelled": "cancelled",
                    "replaced": "cancelled",
                }.get(batch_status)
                # A BATCH IS `ready` LONG BEFORE THE WORK IS. It flips as soon as
                # the titles and a few details are in, and she develops the rest
                # afterwards - so closing here left every later idea with no
                # stream at all: no `idea.ready`, no activity, a card that sits
                # on "generating" until the page is reloaded by hand. Found in
                # the browser on 2026-08-31, with idea 5 writing and nothing
                # able to say so. The stream ends when nothing is running, not
                # when a status word says so.
                if terminal_event is not None and any(
                    str(idea.get("status")) in {"generating", "retrying"}
                    for idea in ideas
                ):
                    terminal_event = None
                if terminal_event is not None:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event=terminal_event,
                        batch_id=batch_id,
                        payload={"batch": public},
                    )
                    return

                if time.monotonic() - last_heartbeat >= 15:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event="heartbeat",
                        batch_id=batch_id,
                    )
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.8)
        finally:
            await internal.cleanup()

    async def _generate(
        self,
        batch_id: UUID,
        principal_id: str,
        session_id: str,
        request: GenerationBatchRequest,
        profile_md: str,
        language: Language = DEFAULT_LANGUAGE,
        trail: Audit | None = None,
        run_id: str | None = None,
        conversation_session_id: str | None = None,
    ) -> None:
        # Redundant with the context this task inherited, and kept anyway: the
        # guarantee is then local to the task that actually runs the agent,
        # instead of resting on where `create_task` happened to be called.
        if run_id is not None:
            bind_run(run_id)

        data_mcp = self._data_mcp_factory(session_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await asyncio.gather(data_mcp.connect(), internal.connect())
            drafts = GenerationDraftClient(internal)
            title_agent = self._title_agent(
                profile_md, data_mcp, request, language, batch_id
            )
            proposed = await self._run_isolated(
                title_agent,
                title_prompt(request, profile_md, language),
                ProposedIdeas,
                f"{batch_id}-titles",
                str(batch_id),
            )
            # The archetype exists to make the ten different from each other
            # while they are being written; nothing downstream needs it, so it
            # is dropped here rather than carried through the store, the DTOs
            # and the interface for no reader.
            await drafts.put_titles(batch_id, proposed.to_titles())
            if self._conversations is not None:
                titles = proposed.to_titles().ideas
                await self._conversations.witness(
                    conversation_session_id,
                    "assistant",
                    rendered_titles(
                        [
                            {
                                "ordinal": idea.ordinal,
                                "title": idea.title,
                                "angle": idea.angle,
                            }
                            for idea in titles
                        ]
                    ),
                )
            # AND THAT IS THE WHOLE BATCH. The ten details used to be written
            # here, eagerly, and they are the entire cost of a run: measured on
            # 2026-08-24, titles were $0.0037 of a $0.0770 batch and the ten
            # detail passes were the other $0.0733. She develops one idea. The
            # other nine were written, stored, and never opened.
            #
            # So they are written when she opens one - `develop` below. The
            # cached prefix is what makes this affordable a second time: the
            # method and the profile are identical for every idea in the batch,
            # so the second idea she opens reads a prefix the first one wrote.
            if trail is not None:
                # The titles are what the batch is judged on; the details are
                # rows of their own. One readable line, same as chat's reply.
                with suppress(Exception):
                    await trail.close_run(
                        run_id, "; ".join(idea.title for idea in proposed.ideas)
                    )
        except asyncio.CancelledError:
            # A cancelled batch is not a fault, but leaving its run `running`
            # for ever makes every later question about open runs meaningless.
            if trail is not None:
                with suppress(Exception):
                    await trail.failed(run_id, RuntimeError("generation cancelled"))
            raise
        except BaseException as exc:  # noqa: BLE001 - background task boundary
            logger.exception("generation batch %s failed", batch_id)
            if trail is not None:
                with suppress(Exception):
                    await trail.failed(run_id, exc)
            with suppress(Exception):
                await GenerationDraftClient(internal).fail_batch(
                    batch_id, safe_generation_error(exc)
                )
            # The conversation reflects the failure too: a chat that shows the
            # request and then silence would read as an agent that ignored her.
            if self._conversations is not None:
                await self._conversations.witness(
                    conversation_session_id, "assistant", safe_generation_error(exc)
                )
        finally:
            await asyncio.gather(
                data_mcp.cleanup(), internal.cleanup(), return_exceptions=True
            )

    # ---- the two agents, built in one place -----------------------------------
    # Both phases are built from the same four things - the profile, the request,
    # the language and the model on the batch - and the detail agent is now built
    # twice: once for a batch that runs its titles, and again, minutes or days
    # later, when she opens an idea. Two copies of this would drift, and the way
    # they would drift is the cache key: a prefix built one way in one place and
    # another way in the other is a cold read on every idea she opens.

    @staticmethod
    def _batch_model(request: GenerationBatchRequest) -> str:
        """The model for this batch. Chosen in the interface, stored on the row.

        Both phases get it. A batch whose titles and details came from different
        models is a batch nobody can reason about the cost or the quality of
        afterwards.
        """
        return request.model or GENERATION_TITLE_MODEL

    def _title_agent(self, profile_md, data_mcp, request, language, batch_id):
        model = self._batch_model(request)
        logger.info("batch %s titles: model=%s", batch_id, model)
        return self._phase_agent(
            profile_md,
            data_mcp,
            "propune-postari",
            language,
            model=model,
            # THE AGENT'S output_type IS THE SCHEMA THE MODEL SEES.
            # `_run_agent`'s own `output_type` argument only casts the result
            # afterwards, so leaving `IdeaTitles` here would send a schema with
            # no `angle_type` and then demand one back.
            output_type=ProposedIdeas,
            model_settings=ModelSettings(
                reasoning={"effort": "minimal"},
                verbosity="low",
                # EXPLICIT, BECAUSE None OMITS THE FIELD. Measured 2026-08-28 on
                # 24 phase-2 runs: the model takes three model turns before it
                # writes - read the skill, do ONE more thing, answer - so the
                # format's reference file and the source's tool compete for a
                # single slot, and 15 of 16 runs did one and skipped the other.
                # Batching is what buys the second errand back.
                max_tokens=4_000,
                parallel_tool_calls=True,
                extra_args={
                    "prompt_cache_key": cache_key(model)
                },
            ),
        )

    def _detail_agent(self, profile_md, data_mcp, request, language, batch_id):
        model = self._batch_model(request)
        logger.info("batch %s detail: model=%s", batch_id, model)
        return self._phase_agent(
            profile_md,
            data_mcp,
            "dezvolta-postarea",
            language,
            model=model,
            output_type=detail_output_type(request.format),
            model_settings=ModelSettings(
                # "low", NOT "minimal", AND ONLY ON THIS PHASE. At "minimal" the
                # model plans as little as it is allowed to, and 24 measured runs
                # show what that buys: three model turns, always - read the
                # skill, do ONE more thing, write. The format's file and the
                # source's tool then compete for one slot. Phase 1 stays minimal:
                # it opens no files, scores 11-12/12 on tools, and has nothing to
                # buy with the extra reasoning tokens.
                reasoning={"effort": "low"},
                verbosity="low",
                max_tokens=24_000,
                # See the note on the title agent: this is the phase the turn
                # budget was measured on.
                parallel_tool_calls=True,
                extra_args={
                    "prompt_cache_key": cache_key(model)
                },
            ),
        )

    async def _generate_one_detail(
        self,
        batch_id: UUID,
        request: GenerationBatchRequest,
        profile_md: str,
        idea: IdeaTitle,
        agent,
        drafts: GenerationDraftClient,
        language: Language = DEFAULT_LANGUAGE,
        conversation_session: str | None = None,
    ) -> bool:
        """True when the five variants were stored; False when the idea failed.

        Failure is handled here rather than raised: the idea is marked, the
        conversation is told, and the caller decides what that means for the
        run. Returning it is what lets the caller stop lying about the run.
        """
        for attempt in (1, 2):
            await drafts.start_idea(batch_id, idea.ordinal)
            try:
                value = await self._run_agent(
                    agent,
                    detail_prompt(request, idea, profile_md, language),
                    detail_output_type(request.format),
                    f"{batch_id}-idea-{idea.ordinal}-attempt-{attempt}",
                    str(batch_id),
                )
                if value.idea_ordinal != idea.ordinal or not same_title(
                    value.title, idea.title
                ):
                    raise ValueError("detail output changed the persisted idea identity")
                # The stored title wins. It matched apart from punctuation, and
                # the row should keep the string the batch was written with
                # rather than the model's re-typing of it.
                value = value.model_copy(update={"title": idea.title})
                await drafts.complete_idea(batch_id, value)
                if self._conversations is not None:
                    await self._conversations.witness(
                        conversation_session,
                        "assistant",
                        rendered_variants(
                            idea.ordinal,
                            idea.title,
                            [
                                variant.model_dump(mode="json")
                                for variant in value.variants
                            ],
                        ),
                    )
                return
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - per-idea isolation
                logger.exception("idea %s of batch %s failed", idea.ordinal, batch_id)
                retryable = attempt == 1 and retryable_generation_error(exc)
                await drafts.fail_idea(
                    batch_id,
                    idea.ordinal,
                    safe_generation_error(exc),
                    retryable=retryable,
                )
                if not retryable:
                    if self._conversations is not None:
                        await self._conversations.witness(
                            conversation_session,
                            "assistant",
                            safe_generation_error(exc),
                        )
                    return False
                await asyncio.sleep(2)
        # Both attempts were retryable and both failed: the loop simply ends.
        return False

    @staticmethod
    def _phase_agent(profile_md, data_mcp, skill: str, language, **kwargs):
        """The agent for one generation phase.

        `skill` is not passed on: both shapes of the worker carry every skill and
        let the model pick by description. It stays in the signature because the
        call site is the one place that knows which phase this is, and losing that
        would make the next reader guess.
        """
        return build_worker(profile_md, data_mcp, language=language, **kwargs)

    async def _run_isolated(
        self, agent, prompt: str, output_type, label: str, group: str
    ):
        return await self._run_agent(agent, prompt, output_type, label, group)

    #: How many batches keep an activity log. Only the current one is ever read
    #: - the stream closes with its batch - so this is a floor for "the reader
    #: is a little behind", not a history anybody browses.
    ACTIVITY_LOGS_KEPT = 8

    def activity_for(self, group: str) -> ActivityLog:
        """The log of one batch, made on first use and eventually dropped."""
        if group not in self._activity:
            while len(self._activity) >= self.ACTIVITY_LOGS_KEPT:
                self._activity.pop(next(iter(self._activity)))
            self._activity[group] = ActivityLog()
        return self._activity[group]

    async def _run_agent(
        self,
        agent,
        prompt: str,
        output_type,
        label: str,
        group: str,
    ):
        # ONE CONTAINER PER RUN, opened here rather than by the callers, because
        # this is the only place a generation run reaches the model. A
        # `SandboxAgent` without one does not answer from memory - the runtime
        # refuses the run - but the caller who forgets is then a caller whose
        # feature is dead, and there are three of them. Opened here, there is
        # nothing to forget.
        #
        # Per run, not per batch, and that is not a compromise: since the ten
        # details became lazy the batch IS one run, and the details are separate
        # runs minutes or days apart. Measured 2026-08-27: a container comes up
        # in 0.35-1.17s and closes in 0.25s, which is cheap next to the model.
        async with sandbox_run_config(label) as sandbox:
            return await self._run_in_sandbox(
                agent, prompt, output_type, label, group, sandbox
            )

    async def _run_in_sandbox(
        self,
        agent,
        prompt: str,
        output_type,
        label: str,
        group: str,
        sandbox,
    ):
        run_config = RunConfig(
            workflow_name=workflow_name(group),
            group_id=group,
            sandbox=sandbox,
        )
        # A RUN THAT FAILED STILL SPENT THE MONEY. Metering used to live only
        # after this call returned, so every run that raised - a missed
        # structured contract, a turn limit - burned its tokens at the provider
        # and left no row. Measured on 2026-08-24 against `public.traces`, which
        # records spans whether or not the run survived: batch e83360cc consumed
        # $0.0195 and recorded $0.0061, and the mini batch beside it consumed
        # $0.1019 and recorded $0.0770. The gap scales with the failure rate,
        # which is exactly backwards for a budget meant to stop runaway
        # spending: the worse an account behaves, the less of it the gate sees.
        metered = _MeteredRun(self.activity_for(group))
        try:
            result = await asyncio.wait_for(
                Runner.run(
                    agent,
                    prompt,
                    run_config=run_config,
                    max_turns=GENERATION_MAX_TURNS,
                    hooks=metered,
                ),
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except BaseException:
            # BaseException, not Exception: a cancelled batch spent its tokens
            # too, and `CancelledError` does not inherit from `Exception`.
            if self._accounts is not None:
                spent = metered.spent()
                if spent is not None:
                    model = getattr(agent, "model", None)
                    with suppress(Exception):
                        await self._accounts.record_run(
                            label, model if isinstance(model, str) else MODEL, spent
                        )
            raise
        # Metered before the interruption check below, because a run that ends
        # in an unexpected approval request still burned the tokens.
        if self._accounts is not None:
            model = getattr(agent, "model", None)
            await self._accounts.record_run(
                label, model if isinstance(model, str) else MODEL, result
            )

        if result.interruptions:
            # Naming the tools matters: this path is reached only when the model
            # reached for a gated write while producing a structured draft, and
            # which write it was decides whether the prompt or the gate is wrong.
            requested = sorted(
                {
                    getattr(getattr(item, "raw_item", None), "name", None) or "?"
                    for item in result.interruptions
                }
            )
            raise RuntimeError(
                f"structured generation unexpectedly requested approval for: "
                f"{', '.join(requested)}"
            )
        self._warn_if_the_method_was_never_opened(agent, label, result)
        return result.final_output_as(output_type, raise_if_incorrect_type=True)

    @staticmethod
    def _warn_if_the_method_was_never_opened(agent, label: str, result) -> None:
        """Say so when a run wrote without reading the method.

        BECAUSE THIS FAILURE IS SILENT, and became more likely when the method
        moved into the sandbox. The model has to decide to open a file; if it
        does not, nothing raises - it writes ten plausible titles from memory
        and the batch looks healthy. Measured 2026-08-27 on the first live run
        of this shape: gpt-5-nano called `exec_command` twice with the command
        `bash`, read nothing, and produced a full set of titles. gpt-5-mini, the
        same request minutes later, ran `sed -n '1,200p'` over the whole
        SKILL.md.

        A warning rather than a failure. The titles were still written, and
        throwing them away would turn a quality problem into a lost batch for
        the client - but nobody should have to read a trace to find out which
        kind of batch this was.
        """
        opened = [
            call
            for call in calls_in(result)
            if any(
                marker in json.dumps(call.get("arguments") or {}, ensure_ascii=False)
                for marker in METHOD_MARKERS
            )
        ]
        if opened:
            return
        logger.warning(
            "run %s (%s): wrote WITHOUT opening the method - no file under"
            " skills/ was read",
            label,
            getattr(agent, "model", "?"),
        )

    async def _get_raw(
        self, principal_id: str, batch_id: UUID
    ) -> dict[str, Any]:
        session_id = self._session_id("generation-read", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            raw = await GenerationDraftClient(internal).get(batch_id)
        finally:
            await internal.cleanup()
        self._ensure_owner(raw, principal_id)
        return raw

    async def _cancel_principal_task(self, principal_id: str) -> None:
        batch_id = self._principal_tasks.get(principal_id)
        task = self._tasks.get(batch_id) if batch_id is not None else None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _task_done(
        self, batch_id: UUID, principal_id: str, task: asyncio.Task[None]
    ) -> None:
        self._tasks.pop(batch_id, None)
        if self._principal_tasks.get(principal_id) == batch_id:
            self._principal_tasks.pop(principal_id, None)
        with suppress(asyncio.CancelledError):
            task.exception()

    @staticmethod
    def _ensure_owner(batch: dict[str, Any], principal_id: str) -> None:
        if str(batch.get("owner_principal_id")) != principal_id:
            raise GenerationAccessError(
                "the batch does not belong to the authenticated principal", "batch_not_owned"
            )

    @staticmethod
    def _batch_signature(batch: dict[str, Any]) -> str:
        payload = {
            "status": batch.get("status"),
            "updated_at": batch.get("updated_at"),
            "ideas": [
                {
                    "id": idea.get("id"),
                    "status": idea.get("status"),
                    "updated_at": idea.get("updated_at"),
                    "selected": [
                        item.get("id")
                        for item in idea.get("variants", [])
                        if item.get("is_selected")
                    ],
                }
                for idea in batch.get("ideas", [])
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _session_id(prefix: str, principal_id: str, *, unique: bool = True) -> str:
        digest = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:20]
        suffix = f"-{uuid.uuid4().hex[:8]}" if unique else ""
        return f"{prefix}-{digest}{suffix}"
