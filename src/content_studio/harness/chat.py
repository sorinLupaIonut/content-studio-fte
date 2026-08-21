"""Streaming chat contracts and orchestration for the Studio UI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from agents import ModelSettings, Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig
from pydantic import Field, field_validator, model_validator

from content_studio.audit import Audit
from content_studio.config import CHAT_MODEL
from content_studio.harness.drafts import GenerationDraftClient
from content_studio.harness.generation import IdeaVariant, StreamEvent, StrictContract
from content_studio.harness.posts import SavedPostContent
from content_studio.language import DEFAULT_LANGUAGE, Language, normalise
from content_studio.worker import build_sandbox, build_worker, describe_request, read_profile

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
            "Nu există o țintă activă. Dacă mesajul cere o rescriere sau o "
            "modificare, cere-i să aleagă întâi o variantă; nu ghici."
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
    return f"""MOD CHAT UI STRUCTURAT D1B
{reply_line}
Textul pentru utilizatoare stă în `reply`. `patch` este null dacă nu rescrii
ținta. Nu include JSON, câmpuri tehnice sau explicații despre patch în `reply`.

CONTEXT ȚINTĂ:
{target}

MESAJUL UTILIZATOAREI:
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


class ChatCoordinator:
    """Run one streamed response per identity and apply only validated patches."""

    def __init__(
        self,
        data_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        internal_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        accounts: Any | None = None,
    ) -> None:
        self._data_mcp_factory = data_mcp_factory
        self._internal_mcp_factory = internal_mcp_factory
        # Optional so a test can build a coordinator without a meter behind it.
        self._accounts = accounts
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
    ) -> ChatRunAccepted:
        active_id = self._active.get(principal_id)
        active = self._runs.get(active_id) if active_id else None
        if active is not None and not active.terminal:
            raise ActiveChatError("Există deja un răspuns în curs. Oprește-l înainte.")

        session_id = self.session_id(principal_id)
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
        data_mcp = self._data_mcp_factory(state.session_id)
        internal_mcp = self._internal_mcp_factory(state.session_id)
        sandbox = None
        decoder = ReplyJsonStream()
        visible_reply = ""
        try:
            await asyncio.gather(data_mcp.connect(), internal_mcp.connect())
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
            client, options = build_sandbox()
            sandbox = await client.create(options=options)
            session = SQLAlchemySession(
                state.session_id, engine=engine, create_tables=True, ensure_ascii=False
            )
            result = Runner.run_streamed(
                worker,
                chat_prompt(message, target_context, state.language),
                session=session,
                run_config=RunConfig(
                    sandbox=SandboxRunConfig(client=client, session=sandbox),
                    group_id=state.session_id,
                ),
                max_turns=6,
            )
            state.result = result
            await state.publish("status", {"status": "streaming"})
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
            if sandbox is not None:
                await sandbox.aclose()
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
