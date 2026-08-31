"""One conversation per lot: dictated messages and the verbatim transcript.

The rule this module serves (2026-08-27): the studio has ONE conversation, and
the buttons are a way of speaking into it. A press composes a Romanian sentence,
that exact string becomes the user item in the agent's session, and the same
string is what the transcript shows — there is no separate "pretty" rendering
that could drift from what the model actually received. Sorin tests by
copy-paste: a dictated message typed by hand must behave identically.

Three layers, deliberately separable:

  · the composers — pure functions, string in, string out, unit-tested exactly;
  · the transcript renderer — pure, maps stored session items to display rows
    (dialogue verbatim, tool calls as collapsed rows, plumbing skipped);
  · `ConversationLog` — the stateful part: resolves the active conversation
    through `content-data` (rule 1: no SQL from here) and writes witness items
    into the SDK's own session storage.

Messages the client reads are Romanian; identifiers are English, as everywhere.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.mcp import MCPServerStreamableHttp

from content_studio.harness.drafts import tool_payload
from content_studio.language import DEFAULT_LANGUAGE, Language, normalise

logger = logging.getLogger("content_studio.harness.conversations")

#: Longest argument/output excerpt a transcript tool row carries. The full value
#: stays in the session storage and in `public.traces`; the transcript is the
#: dialogue window, not the deep one.
TOOL_EXCERPT_LIMIT = 2_000

#: The section of a chat turn that holds her actual words. `chat_prompt` wraps
#: the typed message in target context before it reaches the session, and the
#: transcript shows the words while keeping the whole wrapper in `detail` —
#: display convenience on top of the verbatim record, never instead of it.
USER_MESSAGE_MARKER = "MESAJUL UTILIZATOAREI:"


# ---- the composers ----------------------------------------------------------
# One function per button. The exact string is the contract: it is shown in the
# chat as her message, stored in the session, and later typed by hand in tests.
#
# TWO LANGUAGES, ONE FUNCTION, since 2026-08-31, and for the reason `Copy.cs`
# gives for keeping both on one line: split them and they drift silently. These
# were Romanian only, so a studio running in English filled its chat with
# Romanian the moment anybody pressed a button - `Vreau 10 idei de postare` under
# an English interface, in a conversation the reader could not read. Dictation is
# what she WOULD have typed, and what she would have typed is in the language she
# is working in.
#
# The default stays Romanian, so every caller that names no language - the evals,
# the dataset builder, `test_conversations.py` - keeps the exact string it
# asserted before. The contract is per language, not weaker.
#
# THE VALUES INSIDE DO NOT TRANSLATE, in either branch: `Reel`, `Educatie`,
# `Memorie` and the hook types are identifiers the tools match on, not words on a
# screen. Same rule `language.py` states for structured output.


def dictated_batch_request(
    format: str,
    pillar: str,
    source: str,
    focus: str | None = None,
    language: Language = DEFAULT_LANGUAGE,
) -> str:
    if normalise(language) == "en":
        text = (
            f"I want 10 post ideas: format {format}, pillar {pillar}, "
            f"source {source}."
        )
    else:
        text = (
            f"Vreau 10 idei de postare: format {format}, pilon {pillar}, "
            f"sursă {source}."
        )
    if focus:
        text += f" Focus: {focus}."
    return text


def dictated_develop(
    ordinal: int, title: str, language: Language = DEFAULT_LANGUAGE
) -> str:
    if normalise(language) == "en":
        return f"Develop idea {ordinal}: “{title}”."
    return f"Dezvoltă ideea {ordinal}: „{title}”."


def dictated_select(
    ordinal: int, hook_type: str, language: Language = DEFAULT_LANGUAGE
) -> str:
    if normalise(language) == "en":
        return f"I pick the {hook_type} hook variant from idea {ordinal}."
    return f"Aleg varianta cu hook {hook_type} de la ideea {ordinal}."


def rendered_titles(
    ideas: list[dict[str, Any]], language: Language = DEFAULT_LANGUAGE
) -> str:
    """The ten, in the exact conversational shape `propune-postari` teaches."""

    lines = []
    for idea in ideas:
        lines.append(f"{idea['ordinal']}. {idea['title']}")
        lines.append(f"   {idea['angle']}")
    lines.append("")
    lines.append(
        "Which proposal shall we develop?"
        if normalise(language) == "en"
        else "Care propunere o dezvoltăm?"
    )
    return "\n".join(lines)


def rendered_variants(
    ordinal: int,
    title: str,
    variants: list[dict[str, Any]],
    language: Language = DEFAULT_LANGUAGE,
) -> str:
    """The five variants, numbered by hook type, hooks in full.

    Compact on purpose: scripts and captions live in the tables and on the
    cards; the conversation needs enough to choose by — the hook is what a
    variant is chosen by.
    """

    english = normalise(language) == "en"
    lines = [
        f"The five variants for idea {ordinal} — “{title}”:"
        if english
        else f"Cele cinci variante pentru ideea {ordinal} — „{title}”:",
        "",
    ]
    for index, variant in enumerate(variants, start=1):
        hook = str(variant.get("hook") or "").strip()
        lines.append(f"{index}. {variant['hook_type']}: {hook}")
    lines.append("")
    lines.append(
        "Which variant do you pick? The full text of each one is in the app."
        if english
        else "Care variantă alegi? Textul complet al fiecăreia e în aplicație."
    )
    return "\n".join(lines)


# ---- the transcript renderer ------------------------------------------------


def _message_text(content: Any) -> str:
    """The text of a stored message item, whichever shape the SDK stored."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _structured_reply(text: str) -> str | None:
    """The `reply` of a structured chat turn, when the text is one.

    The chat agent answers through `ChatTurnOutput`, so the stored assistant
    item is a JSON document. The transcript shows the reply and keeps the raw
    document in `detail` — display convenience, never a second source of truth.
    """

    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    reply = payload.get("reply") if isinstance(payload, dict) else None
    return reply if isinstance(reply, str) else None


def _excerpt(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:TOOL_EXCERPT_LIMIT]


def render_transcript(items: list[Any]) -> list[dict[str, Any]]:
    """Stored session items → display rows: dialogue verbatim, tools collapsed.

    Skipped on purpose: reasoning items (not dialogue) and anything unknown a
    future SDK might store (better absent than mis-shown). Function outputs are
    folded onto the call row by `call_id`, so one tool use is one row.
    """

    rows: list[dict[str, Any]] = []
    call_rows: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        role = item.get("role")
        if role in {"user", "assistant"} and (item_type in {None, "message"}):
            text = _message_text(item.get("content"))
            if not text.strip():
                continue
            row: dict[str, Any] = {"kind": role, "text": text}
            if role == "assistant":
                reply = _structured_reply(text)
                if reply is not None:
                    row["text"] = reply
                    row["detail"] = text
            elif USER_MESSAGE_MARKER in text:
                _, _, spoken = text.partition(USER_MESSAGE_MARKER)
                if spoken.strip():
                    row["text"] = spoken.strip()
                    row["detail"] = text
            rows.append(row)
        elif item_type == "function_call":
            row = {
                "kind": "tool",
                "name": str(item.get("name") or "?"),
                "text": _excerpt(item.get("arguments") or ""),
            }
            rows.append(row)
            call_id = item.get("call_id")
            if isinstance(call_id, str):
                call_rows[call_id] = row
        elif item_type == "function_call_output":
            call_id = item.get("call_id")
            row = call_rows.get(call_id) if isinstance(call_id, str) else None
            if row is not None:
                row["detail"] = _excerpt(item.get("output") or "")
    return rows


# ---- the stateful part ------------------------------------------------------


class ConversationLog:
    """The active conversation of an account, and the witness that writes it.

    Data goes through `content-data` (rule 1); witness items go into the SDK's
    own session storage, because the transcript IS that storage — writing them
    anywhere else would create the second copy this design exists to avoid.
    """

    def __init__(
        self,
        internal_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        engine_getter: Callable[[], Any],
    ) -> None:
        self._internal_mcp_factory = internal_mcp_factory
        self._engine = engine_getter

    async def _call(self, owner: str, name: str, arguments: dict[str, Any]) -> Any:
        digest = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:20]
        server = self._internal_mcp_factory(f"conversation-{digest}")
        try:
            await server.connect()
            return tool_payload(await server.call_tool(name, arguments))
        finally:
            await server.cleanup()

    async def active(self, owner: str) -> dict[str, Any]:
        result = await self._call(
            owner, "ui_current_conversation", {"owner_principal_id": owner}
        )
        return result["conversation"]

    async def begin_new(self, owner: str) -> dict[str, Any]:
        result = await self._call(
            owner, "ui_new_conversation", {"owner_principal_id": owner}
        )
        return result["conversation"]

    async def bind_batch(self, owner: str, batch_id: str) -> dict[str, Any]:
        result = await self._call(
            owner,
            "ui_bind_conversation_batch",
            {"owner_principal_id": owner, "batch_id": str(batch_id)},
        )
        return result["conversation"]

    async def session_for_batch(self, owner: str, batch_id: str) -> str | None:
        """The active conversation's session, only if this batch was born in it.

        None otherwise, and callers stay silent then: the witness speaks only
        into the conversation a lot belongs to, never across an archive line.
        """

        conversation = await self.active(owner)
        if str(conversation.get("batch_id")) != str(batch_id):
            return None
        return str(conversation["session_id"])

    def _session(self, session_id: str) -> SQLAlchemySession:
        engine = self._engine()
        if engine is None:
            raise RuntimeError("conversation storage needs the database engine")
        return SQLAlchemySession(
            session_id, engine=engine, create_tables=True, ensure_ascii=False
        )

    async def say_user(self, session_id: str, text: str) -> None:
        await self._session(session_id).add_items(
            [{"role": "user", "content": text}]
        )

    async def say_assistant(self, session_id: str, text: str) -> None:
        await self._session(session_id).add_items(
            [{"role": "assistant", "content": text}]
        )

    async def items(self, session_id: str) -> list[Any]:
        return await self._session(session_id).get_items()

    async def witness(self, session_id: str | None, role: str, text: str) -> None:
        """Best-effort witness: a failed write is logged, never raised.

        The witness documents the work; it must not be able to fail it. A batch
        that generated but was not spoken into the chat is a display gap, and a
        batch that failed because the chat write broke would be a product bug.
        """

        if session_id is None:
            return
        try:
            if role == "user":
                await self.say_user(session_id, text)
            else:
                await self.say_assistant(session_id, text)
        except Exception:  # noqa: BLE001 - witness must never fail the work
            logger.exception("conversation witness failed for %s", session_id)
