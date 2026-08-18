"""Free tests for MCP payload normalization and exact internal tool calls."""

import json
import unittest
from types import SimpleNamespace
from uuid import UUID

from mcp_types import CallToolResult, TextContent

from content_studio.harness.drafts import (
    DraftDataError,
    GenerationDraftClient,
    tool_payload,
)
from content_studio.harness.generation import (
    FormatDetails,
    GenerationBatchRequest,
    IdeaVariant,
)

BATCH_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeServer:
    def __init__(self) -> None:
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            is_error=False,
            structured_content={"id": str(BATCH_ID), "status": "gathering"},
            content=[],
        )


class TestToolPayload(unittest.TestCase):
    def test_prefers_structured_content(self) -> None:
        result = SimpleNamespace(
            is_error=False, structured_content={"answer": 42}, content=[]
        )
        self.assertEqual(tool_payload(result), {"answer": 42})

    def test_decodes_text_fallback(self) -> None:
        result = SimpleNamespace(
            is_error=False,
            structured_content=None,
            content=[SimpleNamespace(type="text", text=json.dumps({"answer": 42}))],
        )
        self.assertEqual(tool_payload(result), {"answer": 42})

    def test_raises_a_safe_tool_error(self) -> None:
        result = SimpleNamespace(
            is_error=True,
            structured_content=None,
            content=[SimpleNamespace(type="text", text="batch not found")],
        )
        with self.assertRaisesRegex(DraftDataError, "batch not found"):
            tool_payload(result)


class TestDraftClient(unittest.IsolatedAsyncioTestCase):
    async def test_create_uses_the_internal_exact_name(self) -> None:
        server = FakeServer()
        client = GenerationDraftClient(server)
        request = GenerationBatchRequest(
            format="Reel", pillar="Conexiune", source="Memorie"
        )

        result = await client.create("principal-1", request, {"profile": "bounded"})

        self.assertEqual(result["id"], str(BATCH_ID))
        name, arguments = server.calls[0]
        self.assertEqual(name, "ui_create_generation_batch")
        self.assertEqual(arguments["owner_principal_id"], "principal-1")
        self.assertEqual(arguments["format"], "Reel")

    async def test_patch_uses_the_hidden_exact_name_and_complete_content(self) -> None:
        server = FakeServer()
        client = GenerationDraftClient(server)
        value = IdeaVariant(
            hook_type="PROVOCARE",
            hook="Hook nou",
            script="Script nou",
            caption="Caption nou",
            hashtags=["#unu", "#doi", "#trei"],
            cta="CTA nou",
            source="din memorie",
            format_details=FormatDetails(
                content_blocks=["Cadru"],
                visual_direction="Aproape",
                duration_or_count="30 secunde",
            ),
        )

        await client.patch_variant(BATCH_ID, "principal-1", value)

        name, arguments = server.calls[0]
        self.assertEqual(name, "ui_patch_generation_variant")
        self.assertEqual(arguments["owner_principal_id"], "principal-1")
        self.assertEqual(arguments["content"]["hook_type"], "PROVOCARE")


if __name__ == "__main__":
    unittest.main()


class EmptyPayloadTests(unittest.TestCase):
    """An empty collection is zero content blocks, which is not a failure."""

    @staticmethod
    def _result(**kwargs):
        return SimpleNamespace(
            is_error=False, structured_content=None, content=[], **kwargs
        )

    def test_empty_result_without_default_still_refuses(self):
        with self.assertRaises(DraftDataError):
            tool_payload(self._result())

    def test_empty_result_with_default_returns_it(self):
        self.assertEqual(tool_payload(self._result(), empty=[]), [])

    def test_default_does_not_mask_a_tool_error(self):
        error = SimpleNamespace(
            is_error=True,
            structured_content=None,
            content=[SimpleNamespace(type="text", text="boom")],
        )
        with self.assertRaises(DraftDataError):
            tool_payload(error, empty=[])

    def test_default_does_not_mask_an_ambiguous_payload(self):
        two = SimpleNamespace(
            is_error=False,
            structured_content=None,
            content=[
                SimpleNamespace(type="text", text="{}"),
                SimpleNamespace(type="text", text="{}"),
            ],
        )
        with self.assertRaises(DraftDataError):
            tool_payload(two, empty=[])


class RealResultTests(unittest.TestCase):
    """Against the SDK's own class, not a stand-in.

    The stand-ins above are written by hand, so a field the SDK renames stays
    spelled the old way on both sides and the suite keeps passing while the
    running harness fails. That is exactly what happened when MCP 2.0 moved to
    snake_case: `structuredContent` read as absent and `isError` as false, so a
    tool error surfaced as "no unambiguous payload". These two build the real
    `CallToolResult`, which cannot drift from the wire format.
    """

    def test_structured_content_is_read(self):
        result = CallToolResult(content=[], structured_content={"answer": 42})
        self.assertEqual(tool_payload(result), {"answer": 42})

    def test_tool_error_is_raised_not_swallowed(self):
        result = CallToolResult(
            content=[TextContent(type="text", text="batch not found")],
            is_error=True,
        )
        with self.assertRaisesRegex(DraftDataError, "batch not found"):
            tool_payload(result)
