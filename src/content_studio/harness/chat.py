"""Streaming chat contracts and orchestration for the Studio UI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from agents import ModelSettings, Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig
from pydantic import Field, field_validator, model_validator

from content_studio.audit import Audit
from content_studio.config import CHAT_MODEL
from content_studio.harness.conversations import USER_MESSAGE_MARKER
from content_studio.harness.drafts import GenerationDraftClient
from content_studio.harness.generation import IdeaVariant, StreamEvent, StrictContract
from content_studio.harness.posts import SavedPostContent
from content_studio.language import DEFAULT_LANGUAGE, Language, normalise
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import (
    build_worker,
    describe_request,
    read_profile,
)

logger = logging.getLogger("content_studio.harness.chat")

ChatTargetKind = Literal[
    "general",
    "generation_variant",
    "saved_post",
    "profile_section",
    "library_document",
]


class ChatTarget(StrictContract):
    kind: ChatTargetKind = "general"
    id: UUID | str | None = None

    @model_validator(mode="after")
    def target_id_matches_kind(self) -> ChatTarget:
        if self.kind == "general" and self.id is not None:
            raise ValueError("general chat cannot carry a target id")
        if self.kind != "general" and self.id is None:
            raise ValueError("a typed chat target requires an id")
        return self


class ChatRunRequest(StrictContract):
    message: str = Field(min_length=1, max_length=50_000)
    target: ChatTarget = Field(default_factory=ChatTarget)
    language: Language = DEFAULT_LANGUAGE

    @field_validator("message")
    @classmethod
    def message_is_not_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ChatRunAccepted(StrictContract):
    run_id: str
    session_id: str
    status: Literal["running"] = "running"
    target: ChatTarget


class GenerationVariantPatch(StrictContract):
    target_id: UUID
    content: IdeaVariant


class ChatTurnOutput(StrictContract):
    reply: str = Field(min_length=1, max_length=50_000)
    patch: GenerationVariantPatch | None = None


class SavedPostPatch(StrictContract):
    target_id: UUID
    content: SavedPostContent


class SavedPostChatOutput(StrictContract):
    """The same turn shape for an already-saved post.

    A separate strict contract rather than a union inside `ChatTurnOutput`: the
    model does better with one exact schema per situation, and the two targets do
    not carry the same fields — a saved post owns its title, pillar and format,
    a generated variant inherits them from its batch.
    """

    reply: str = Field(min_length=1, max_length=50_000)
    patch: SavedPostPatch | None = None


#: Which strict contract each chat target is answered through.
CHAT_OUTPUTS: dict[str, type[StrictContract]] = {
    "saved_post": SavedPostChatOutput,
}


class ReplyJsonStream:
    """Expose only the `reply` JSON string while structured output is incomplete.

    The model streams the strict `ChatTurnOutput` JSON document. The browser must
    see the answer quickly, but it must never see or apply a half-written patch.
    This decoder emits complete characters from the first-level `reply` string;
    the Pydantic result validates the complete patch only after streaming ends.
    """

    _reply_start = re.compile(r'"reply"\s*:\s*"')

    def __init__(self) -> None:
        self._raw = ""
        self._emitted = 0

    def feed(self, delta: str) -> str:
        self._raw += delta
        match = self._reply_start.search(self._raw)
        if match is None:
            return ""
        decoded = self._decode_partial(self._raw, match.end())
        fresh = decoded[self._emitted :]
        self._emitted = len(decoded)
        return fresh

    @staticmethod
    def _decode_partial(raw: str, start: int) -> str:
        result: list[str] = []
        index = start
        escapes = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        while index < len(raw):
            char = raw[index]
            if char == '"':
                break
            if char != "\\":
                result.append(char)
                index += 1
                continue
            if index + 1 >= len(raw):
                break
            escaped = raw[index + 1]
            if escaped == "u":
                if index + 6 > len(raw):
                    break
                code = raw[index + 2 : index + 6]
                try:
                    result.append(chr(int(code, 16)))
                except ValueError:
                    break
                index += 6
                continue
            replacement = escapes.get(escaped)
            if replacement is None:
                break
            result.append(replacement)
            index += 2
        return "".join(result)


#: Appended for a verified target that has no script. The patch contract has to
#: read back both shapes, so it cannot forbid one; this is what stops the model
#: from growing a script onto a silent reel. `content-data` refuses such a patch
#: anyway — saying it here means the rewrite succeeds instead of being rejected.
SILENT_REEL_TARGET = (
    " Ținta este un reel mut: nu are script și nu are bloc de producție. "
    "Lasă `script` și `format_details` absente; tot ce ar fi fost spus stă în "
    "`caption`, care rămâne lung."
)


def _silent(target_context: dict[str, Any] | None) -> str:
    """The note above, when the verified target is one without a script."""

    if target_context is None:
        return ""
    content = target_context.get("variant") or target_context
    return SILENT_REEL_TARGET if content.get("script") is None else ""


def chat_prompt(
    message: str,
    target_context: dict[str, Any] | None,
    language: Language = DEFAULT_LANGUAGE,
) -> str:
    """Bind the user's message to one server-verified target, never a label."""

    if target_context is None:
        target = (
            "Nu există o țintă selectată în interfață. Fluxul de producție "
            "trece prin unelte, nu prin scrisul tău: idei noi → "
            "`start_generation`; „dezvoltă a treia” → `develop_idea`; „aleg "
            "varianta cu CIFRA” / „a doua” → `select_variant`. Nu scrie tu "
            "liste, variante sau postări în locul lor — aplicația le "
            "generează și le arată. Dacă cere modificarea unei postări deja "
            "salvate, cere-i să o deschidă întâi în aplicație; nu ghici."
        )
    elif target_context.get("kind") == "saved_post":
        target = (
            "Ținta activă este o postare deja salvată, verificată de aplicație. "
            "Dacă utilizatoarea cere rescrierea, întoarce în `patch` conținutul "
            "COMPLET al aceleiași postări, inclusiv câmpurile neschimbate. "
            "`target_id` rămâne identic. Nu chema o unealtă de scriere: modificarea "
            "rămâne o ciornă în browser până când ea apasă „Salvează modificările” "
            "și confirmă la poartă."
            + _silent(target_context)
            + "\n"
            + json.dumps(target_context, ensure_ascii=False)
        )
    else:
        target = (
            "Ținta activă a fost verificată de aplicație. Poți răspunde despre ea. "
            "Dacă utilizatoarea cere rescrierea, întoarce în `patch` conținutul "
            "COMPLET al aceleiași variante, inclusiv câmpurile neschimbate. "
            "`target_id` și `hook_type` rămân identice. Nu chema o unealtă de "
            "scriere: acesta este încă un draft nesalvat."
            + _silent(target_context)
            + "\n"
            + json.dumps(target_context, ensure_ascii=False)
        )
    # This line used to say "în română" unconditionally, and being inside the
    # user message it beat the system prompt outright - the first English chat
    # came back Romanian because of exactly this.
    reply_line = (
        "Răspunde natural, în română, prin contractul structurat cerut de aplicație."
        if normalise(language) == "ro"
        else "Reply naturally, IN ENGLISH, through the structured contract the "
        "application requires. The Romanian below is the method and the source "
        "material, not the language of your answer."
    )
    return f"""{reply_line}
Textul pentru utilizatoare stă în `reply`. `patch` este null dacă nu rescrii
ținta. Nu include JSON, câmpuri tehnice sau explicații despre patch în `reply`.

CONTEXT ȚINTĂ:
{target}

{USER_MESSAGE_MARKER}
{message}
"""


@dataclass(slots=True)
class _LiveChatRun:
    principal_id: str
    run_id: str
    session_id: str
    target: ChatTarget
    language: Language = DEFAULT_LANGUAGE
    events: list[StreamEvent] = field(default_factory=list)
    sequence: int = 0
    terminal: bool = False
    cancel_requested: bool = False
    result: Any | None = None
    task: asyncio.Task[None] | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def publish(self, event: str, payload: dict[str, Any] | None = None) -> None:
        async with self.condition:
            self.sequence += 1
            self.events.append(
                StreamEvent(
                    sequence=self.sequence,
                    event=event,
                    run_id=self.run_id,
                    payload=payload or {},
                )
            )
            if event in {"completed", "cancelled", "error", "approval.required"}:
                self.terminal = True
            self.condition.notify_all()


class ChatAccessError(RuntimeError):
    """A run does not belong to the authenticated principal."""


class ActiveChatError(RuntimeError):
    """One identity already has a response streaming."""


#: The model-visible tools that record an intent the harness must execute. The
#: tool answers "accepted" inside the run; the actual model work — the same
#: pipeline the buttons use — starts here, after the reply, in the background.
#: How many times the chat agent may go round before it has to answer.
#:
#: Six was enough when the method came back from one tool call. Since the method
#: moved into the sandbox it is opened file by file with the shell, and a Reel
#: question took ten `exec_command` calls before the first written line - so six
#: would cut her off mid-method and report a broken chat. Twenty is above
#: anything measured on 2026-08-27 and still bounded.
CHAT_MAX_TURNS = 20

#: How long one chat turn may take before it is abandoned. Shorter than the
#: generation ceiling on purpose: somebody is sitting in front of this one, and
#: a reply that takes five minutes has already failed even if it arrives.
CHAT_TIMEOUT_SECONDS = 300

TRIGGER_TOOLS = frozenset({"start_generation", "develop_idea"})


def trigger_calls(result: Any) -> list[tuple[str, dict[str, Any], str]]:
    """(name, arguments, output_text) for every trigger tool call of a run.

    The output text rides along because it is how a rejected call is told from
    an accepted one: a tool that raised put its refusal there, and executing a
    refused intent would do exactly what the refusal prevented.
    """

    calls: list[tuple[str, dict[str, Any], str | None]] = []
    outputs: dict[str, str] = {}
    for item in getattr(result, "new_items", []) or []:
        raw = getattr(item, "raw_item", None)
        kind = getattr(item, "type", "")
        if kind == "tool_call_item":
            name = str(getattr(raw, "name", "") or "")
            if name not in TRIGGER_TOOLS:
                continue
            arguments = getattr(raw, "arguments", None)
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else {}
            except json.JSONDecodeError:
                parsed = {}
            call_id = getattr(raw, "call_id", None)
            calls.append((name, parsed, call_id))
        elif kind == "tool_call_output_item":
            if isinstance(raw, dict):
                call_id, output = raw.get("call_id"), raw.get("output")
            else:
                call_id = getattr(raw, "call_id", None)
                output = getattr(raw, "output", None)
            if isinstance(call_id, str):
                outputs[call_id] = str(output)
    return [
        (name, parsed, outputs.get(call_id, "") if call_id else "")
        for name, parsed, call_id in calls
    ]


class ChatCoordinator:
    """Run one streamed response per identity and apply only validated patches."""

    def __init__(
        self,
        data_mcp_factory: Callable[..., MCPServerStreamableHttp],
        internal_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        accounts: Any | None = None,
        orchestrator: Callable[..., Any] | None = None,
    ) -> None:
        self._data_mcp_factory = data_mcp_factory
        self._internal_mcp_factory = internal_mcp_factory
        # Optional so a test can build a coordinator without a meter behind it.
        self._accounts = accounts
        # `async (principal_id, name, arguments, language) -> None`, provided by
        # the service. Executes an accepted trigger through the same pipeline
        # the buttons use. Optional for the same testability reason.
        self._orchestrator = orchestrator
        self._runs: dict[str, _LiveChatRun] = {}
        self._active: dict[str, str] = {}

    async def close(self) -> None:
        tasks = [state.task for state in self._runs.values() if state.task is not None]
        for state in self._runs.values():
            if state.result is not None:
                state.result.cancel()
            if state.task is not None:
                state.task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runs.clear()
        self._active.clear()

    async def start(
        self,
        principal_id: str,
        request: ChatRunRequest,
        target_context: dict[str, Any] | None,
        engine,
        trail: Audit,
        session_id: str | None = None,
    ) -> ChatRunAccepted:
        active_id = self._active.get(principal_id)
        active = self._runs.get(active_id) if active_id else None
        if active is not None and not active.terminal:
            raise ActiveChatError("Există deja un răspuns în curs. Oprește-l înainte.")

        # Since 2026-08-27 the harness passes the active conversation's session,
        # so chat and buttons share one thread. The per-principal digest stays
        # as the fallback for callers that predate the conversations ledger.
        session_id = session_id or self.session_id(principal_id)
        run_id = await trail.open_run(session_id, request.message)
        if run_id is None:
            raise RuntimeError("run-ul de chat nu a putut primi un ID durabil")
        state = _LiveChatRun(
            principal_id=principal_id,
            run_id=run_id,
            session_id=session_id,
            target=request.target,
            language=request.language,
        )
        self._runs[run_id] = state
        self._active[principal_id] = run_id
        await state.publish("status", {"status": "queued"})
        state.task = asyncio.create_task(
            self._run(state, request.message, target_context, engine, trail),
            name=f"chat-{run_id}",
        )
        state.task.add_done_callback(
            lambda done, owner=principal_id, value=run_id: self._task_done(
                owner, value, done
            )
        )
        return ChatRunAccepted(
            run_id=run_id,
            session_id=session_id,
            target=request.target,
        )

    def events(
        self, principal_id: str, run_id: str, sequence: int = 0
    ) -> AsyncIterator[StreamEvent]:
        state = self._owned(principal_id, run_id)

        async def stream() -> AsyncIterator[StreamEvent]:
            cursor = sequence
            while True:
                pending = [event for event in state.events if event.sequence > cursor]
                if pending:
                    for event in pending:
                        cursor = event.sequence
                        yield event
                    if state.terminal:
                        return
                    continue
                if state.terminal:
                    return
                try:
                    async with state.condition:
                        await asyncio.wait_for(state.condition.wait(), timeout=15)
                except TimeoutError:
                    await state.publish("heartbeat")

        return stream()

    async def cancel(self, principal_id: str, run_id: str) -> dict[str, str]:
        state = self._owned(principal_id, run_id)
        if state.terminal:
            return {"run_id": run_id, "status": "finished"}
        state.cancel_requested = True
        if state.result is not None:
            state.result.cancel()
        return {"run_id": run_id, "status": "stopping"}

    async def _run(
        self,
        state: _LiveChatRun,
        message: str,
        target_context: dict[str, Any] | None,
        engine,
        trail: Audit,
    ) -> None:
        """One turn, inside one container.

        The container is this turn's, not this conversation's. A conversation
        can sit open for a day between two questions, and an E2B sandbox left
        running is billed for that day; the method inside it is read-only and
        identical every time, so there is nothing in it worth keeping warm.
        Measured 2026-08-27: it comes up in about a second.

        THE CONTAINER IS OPENED INSIDE THE ERROR BOUNDARY, not around it. The
        first version of this wrapped `_run_in_sandbox` in the context manager
        from out here, and that put the one thing most likely to fail - talking
        to a third-party API over the network - outside the only code that turns
        a failure into a message. A sandbox that refused would then leave the
        audit row `running` for ever and the browser waiting on a stream that
        was never going to arrive.
        """

        await self._run_in_sandbox(
            state,
            message,
            target_context,
            engine,
            trail,
            sandbox_run_config(f"chat-{state.run_id[:8]}"),
        )

    async def _run_in_sandbox(
        self,
        state: _LiveChatRun,
        message: str,
        target_context: dict[str, Any] | None,
        engine,
        trail: Audit,
        sandbox_cm,
    ) -> None:
        # The principal rides the connection so the trigger tools can verify an
        # identity exists (`owner_of`); the tools never take it as an argument.
        data_mcp = self._data_mcp_factory(state.session_id, state.principal_id)
        internal_mcp = self._internal_mcp_factory(state.session_id)
        decoder = ReplyJsonStream()
        visible_reply = ""
        # The container joins the same stack the connections are cleaned up on,
        # so it is opened under the `except` below and closed by the `finally`.
        stack = AsyncExitStack()
        try:
            await asyncio.gather(data_mcp.connect(), internal_mcp.connect())
            sandbox = await stack.enter_async_context(sandbox_cm)
            _, profile_md = await read_profile(data_mcp)
            output_type = CHAT_OUTPUTS.get(state.target.kind, ChatTurnOutput)
            worker = build_worker(
                profile_md,
                data_mcp,
                model=CHAT_MODEL,
                output_type=output_type,
                language=state.language,
                model_settings=ModelSettings(
                    reasoning={"effort": "low"},
                    verbosity="low",
                    max_tokens=12_000,
                ),
            )
            session = SQLAlchemySession(
                state.session_id, engine=engine, create_tables=True, ensure_ascii=False
            )
            result = Runner.run_streamed(
                worker,
                chat_prompt(message, target_context, state.language),
                session=session,
                run_config=RunConfig(
                    # Named for Phoenix, where an unnamed run shows up as the
                    # SDK default "Agent workflow" - the same title as every
                    # other unnamed run anybody has ever made.
                    workflow_name=f"Chat {state.session_id[:16]}",
                    group_id=state.session_id,
                    sandbox=sandbox,
                ),
                max_turns=CHAT_MAX_TURNS,
            )
            state.result = result
            await state.publish("status", {"status": "streaming"})

            async def pump() -> None:
                nonlocal visible_reply
                async for event in result.stream_events():
                    if state.cancel_requested:
                        result.cancel()
                    if event.type != "raw_response_event":
                        continue
                    data = event.data
                    if getattr(data, "type", None) != "response.output_text.delta":
                        continue
                    delta = decoder.feed(str(getattr(data, "delta", "")))
                    if delta:
                        visible_reply += delta
                        await state.publish("text.delta", {"delta": delta})

            # A CEILING, WHICH THIS PATH DID NOT HAVE. Generation has always
            # wrapped its run in `wait_for`; chat did not, because six turns
            # against one tool call could not run long. Since the method moved
            # into the sandbox a turn can be a file read, twenty of them are
            # allowed, and a run that stalls now leaves the audit row `running`
            # and the browser waiting on a stream that never ends. Measured
            # 2026-08-27: a method question took over twelve minutes with no
            # ceiling at all.
            await asyncio.wait_for(pump(), timeout=CHAT_TIMEOUT_SECONDS)

            if state.cancel_requested:
                await trail.failed(state.run_id, RuntimeError("chat cancelled"))
                await state.publish(
                    "cancelled", {"partial": visible_reply, "status": "stopped"}
                )
                return

            if result.interruptions:
                requests = []
                for item in result.interruptions:
                    tool_name, arguments, call_id = describe_request(item)
                    requests.append(
                        {
                            "call_id": call_id,
                            "tool_name": tool_name,
                            "arguments": arguments,
                        }
                    )
                await trail.suspend_run(
                    state.run_id, requests, result.to_state().to_string()
                )
                await state.publish("approval.required", {"requests": requests})
                return

            output = result.final_output_as(output_type, raise_if_incorrect_type=True)
            remainder = output.reply[len(visible_reply) :]
            if remainder:
                visible_reply += remainder
                await state.publish("text.delta", {"delta": remainder})

            patch_payload = None
            if output.patch is not None:
                patch_payload = await self._patch(state, output.patch, internal_mcp)
                await state.publish("ui.patch", patch_payload)

            await trail.turn(state.run_id, result)
            # After the answer is complete and before it is announced: the meter
            # never stands between the user and a reply they already paid for.
            if self._accounts is not None:
                await self._accounts.record_run("chat", CHAT_MODEL, result)
            await trail.close_run(state.run_id, output.reply)

            # Accepted trigger intents start their pipelines now, after the
            # reply. A refusal in the tool's own output is honoured, and a
            # failure here is logged, never surfaced as a broken chat: the
            # generation pipeline reports its own failures into the batch.
            if self._orchestrator is not None:
                for name, arguments, tool_output in trigger_calls(result):
                    if '"accepted"' not in tool_output:
                        continue
                    try:
                        await self._orchestrator(
                            state.principal_id, name, arguments, state.language
                        )
                    except Exception:  # noqa: BLE001 - background boundary
                        logger.exception("chat trigger %s failed", name)

            await state.publish(
                "completed", {"output": output.reply, "patch": patch_payload}
            )
        except asyncio.CancelledError:
            if state.result is not None:
                state.result.cancel()
            raise
        except Exception as exc:  # noqa: BLE001 - background stream boundary
            await trail.failed(state.run_id, exc)
            await state.publish(
                "error",
                {"detail": f"Răspunsul nu a putut fi terminat ({type(exc).__name__})."},
            )
        finally:
            state.result = None
            await stack.aclose()
            await asyncio.gather(
                data_mcp.cleanup(), internal_mcp.cleanup(), return_exceptions=True
            )

    @staticmethod
    async def _patch(
        state: _LiveChatRun,
        patch: GenerationVariantPatch | SavedPostPatch,
        internal_mcp: MCPServerStreamableHttp,
    ) -> dict[str, Any]:
        """Turn a validated rewrite into either a draft write or a browser draft."""

        if state.target.kind not in {"generation_variant", "saved_post"}:
            raise ValueError("the model returned a patch without a rewritable target")
        if str(patch.target_id) != str(state.target.id):
            raise ValueError("the model changed the verified patch target")

        if state.target.kind == "saved_post":
            # Deliberately not written here. A saved post is the client's own
            # published work: a rewrite stays a draft in her browser until she
            # presses save and answers the gate, which is what `update_post` is.
            return {
                "target_kind": "saved_post",
                "target_id": str(patch.target_id),
                "persisted": False,
                "content": patch.content.model_dump(mode="json"),
            }

        applied = await GenerationDraftClient(internal_mcp).patch_variant(
            patch.target_id, state.principal_id, patch.content
        )
        return {
            "target_kind": "generation_variant",
            "target_id": str(patch.target_id),
            "persisted": True,
            **applied,
        }

    def _owned(self, principal_id: str, run_id: str) -> _LiveChatRun:
        state = self._runs.get(run_id)
        if state is None or state.principal_id != principal_id:
            raise ChatAccessError("Run-ul de chat nu aparține contului autentificat.")
        return state

    def _task_done(
        self, principal_id: str, run_id: str, task: asyncio.Task[None]
    ) -> None:
        if self._active.get(principal_id) == run_id:
            self._active.pop(principal_id, None)
        if not task.cancelled():
            task.exception()

    @staticmethod
    def session_id(principal_id: str) -> str:
        digest = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:24]
        return f"chat-{digest}"
