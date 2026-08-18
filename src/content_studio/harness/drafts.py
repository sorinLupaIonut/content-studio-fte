"""Harness-side client for internal D1b operations on `content-data`."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from agents.mcp import MCPServerStreamableHttp

from content_studio.harness.generation import (
    GenerationBatchRequest,
    IdeaDetails,
    IdeaTitles,
    IdeaVariant,
    ProducedIdeaDetails,
    SilentReelDetails,
)


class DraftDataError(RuntimeError):
    """An internal typed `content-data` operation failed or returned bad data."""


_NO_DEFAULT = object()


def _result_field(result, snake: str, camel: str) -> Any:
    """Read one `CallToolResult` field under either spelling.

    MCP 2.0 renamed the wire fields to snake_case (`structured_content`,
    `is_error`); 1.x exposed them camelCase. Reading only one spelling fails
    silently rather than loudly — `getattr` with a default turns a renamed field
    into "absent", so a tool error reads as success and a structured payload
    reads as missing. That is the bug this closes, and the reason both spellings
    stay accepted: the harness has to work against whichever SDK the image ends
    up with.
    """

    value = getattr(result, snake, None)
    if value is None:
        value = getattr(result, camel, None)
    return value


def tool_payload(result, *, empty: Any = _NO_DEFAULT) -> Any:
    """Normalize MCP structured content and the text fallback into one value.

    An MCP tool that returns an empty collection comes back with **zero** content
    blocks and no structured content — there is nothing for the server to encode.
    That is indistinguishable on the wire from a tool that answered nothing at
    all, so this decoder refuses to guess. Callers that know an empty answer is
    legitimate say so by passing `empty=[]`; everyone else still gets the error.
    The bug this closes: a client with an empty post library could not generate,
    because `list_posts` returned nothing and the decoder read that as a fault.
    """

    if _result_field(result, "is_error", "isError"):
        messages = [
            str(getattr(item, "text", ""))
            for item in getattr(result, "content", [])
            if getattr(item, "type", None) == "text"
        ]
        detail = " ".join(message for message in messages if message).strip()
        raise DraftDataError(detail or "content-data returned an internal tool error")

    structured = _result_field(result, "structured_content", "structuredContent")
    if structured is not None:
        # MCP servers may wrap a non-object return under `result` when exposing a
        # structured channel. Our operations return objects, but accepting the
        # wrapper makes this decoder stable across MCP SDK versions.
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured

    text_items = [
        getattr(item, "text", "")
        for item in getattr(result, "content", [])
        if getattr(item, "type", None) == "text"
    ]
    if not text_items and empty is not _NO_DEFAULT:
        return empty
    if len(text_items) != 1:
        raise DraftDataError("content-data returned no unambiguous payload")
    try:
        return json.loads(text_items[0])
    except (TypeError, json.JSONDecodeError) as exc:
        raise DraftDataError("content-data returned invalid JSON") from exc


class GenerationDraftClient:
    """Exact-name calls hidden from the model by the agent's MCP tool filter."""

    def __init__(self, server: MCPServerStreamableHttp) -> None:
        self.server = server

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        return tool_payload(await self.server.call_tool(name, arguments))

    async def create(
        self,
        owner_principal_id: str,
        request: GenerationBatchRequest,
        source_packet: dict[str, Any],
    ) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        return await self._call(
            "ui_create_generation_batch",
            {
                "owner_principal_id": owner_principal_id,
                **payload,
                "source_packet": source_packet,
            },
        )

    async def put_titles(self, batch_id: UUID, value: IdeaTitles) -> dict[str, Any]:
        return await self._call(
            "ui_put_generation_titles",
            {"batch_id": str(batch_id), "ideas": value.model_dump(mode="json")["ideas"]},
        )

    async def start_idea(self, batch_id: UUID, ordinal: int) -> dict[str, Any]:
        return await self._call(
            "ui_start_generation_idea",
            {"batch_id": str(batch_id), "ordinal": ordinal},
        )

    async def complete_idea(
        self,
        batch_id: UUID,
        value: IdeaDetails | ProducedIdeaDetails | SilentReelDetails,
    ) -> dict[str, Any]:
        """Hand over whichever detail contract the batch's format produced.

        A silent reel dumps without `script` and `format_details`; the storage
        contract on the other side fills them in as absent.
        """
        return await self._call(
            "ui_complete_generation_idea",
            {"batch_id": str(batch_id), "idea": value.model_dump(mode="json")},
        )

    async def fail_idea(
        self,
        batch_id: UUID,
        ordinal: int,
        error: str,
        *,
        retryable: bool,
    ) -> dict[str, Any]:
        return await self._call(
            "ui_fail_generation_idea",
            {
                "batch_id": str(batch_id),
                "ordinal": ordinal,
                "error": error,
                "retryable": retryable,
            },
        )

    async def fail_batch(self, batch_id: UUID, error: str) -> dict[str, Any]:
        return await self._call(
            "ui_fail_generation_batch",
            {"batch_id": str(batch_id), "error": error},
        )

    async def select(self, variant_id: UUID, owner_principal_id: str) -> dict[str, Any]:
        return await self._call(
            "ui_select_generation_variant",
            {
                "variant_id": str(variant_id),
                "owner_principal_id": owner_principal_id,
            },
        )

    async def patch_variant(
        self,
        variant_id: UUID,
        owner_principal_id: str,
        content: IdeaVariant,
    ) -> dict[str, Any]:
        return await self._call(
            "ui_patch_generation_variant",
            {
                "variant_id": str(variant_id),
                "owner_principal_id": owner_principal_id,
                "content": content.model_dump(mode="json"),
            },
        )

    async def cancel(self, batch_id: UUID, owner_principal_id: str) -> dict[str, Any]:
        return await self._call(
            "ui_cancel_generation_batch",
            {
                "batch_id": str(batch_id),
                "owner_principal_id": owner_principal_id,
            },
        )

    async def get(self, batch_id: UUID) -> dict[str, Any]:
        return await self._call(
            "ui_get_generation_batch", {"batch_id": str(batch_id)}
        )

    async def current(self, owner_principal_id: str) -> dict[str, Any] | None:
        result = await self._call(
            "ui_get_current_generation_batch",
            {"owner_principal_id": owner_principal_id},
        )
        return result["batch"]

    async def library(self) -> list[dict[str, Any]]:
        result = await self._call("ui_list_library", {})
        return result["items"]


class SavedPostClient:
    """Read the client's studio-written posts for the browser.

    Reads only. Everything that changes `public.posts` goes through the two gated
    model-visible tools, so the browser can never write behind the approval gate.
    """

    def __init__(self, server: MCPServerStreamableHttp) -> None:
        self.server = server

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        return tool_payload(await self.server.call_tool(name, arguments))

    async def list(self, limit: int = 100) -> list[dict[str, Any]]:
        result = await self._call("ui_list_saved_posts", {"limit": limit})
        return result["items"]

    async def get(self, post_id: UUID) -> dict[str, Any]:
        result = await self._call("ui_get_saved_post", {"post_id": str(post_id)})
        return result["post"]
