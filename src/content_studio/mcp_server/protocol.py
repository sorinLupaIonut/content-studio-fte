"""The small contract between the worker and the MCP server."""

from content_studio.config import CLIENT_SLUG

# The conversation id is not a business argument and must not be filled in by the
# model. The worker puts it on the HTTP connection, and the server attaches it to
# the write and to the audit row of the same transaction.
CONVERSATION_HEADER = "X-Content-Conversation-ID"

# Ownership of a generation batch is identity, not a business argument either.
# `save_posts_batch` is a model-visible tool, so the principal cannot travel as a
# parameter the model fills in; it rides the same trusted connection. The CLI
# never sets it, which is exactly why that tool refuses to run there.
OWNER_HEADER = "X-Content-Owner-Principal-ID"

# The profile is business data, but it has to reach the system prompt whole before
# the agent can work at all. It is read programmatically as an MCP resource: that
# way it does not become a sixth tool the model can call, and the worker still
# runs no SQL of its own.
PROFILE_URI = f"content-data://client/{CLIENT_SLUG}/profile"

# D1b adds internal persistence operations to the same purpose-built data server.
# The model still sees only the domain capabilities below; the harness invokes
# internal `ui_*` operations programmatically by exact name.
MODEL_VISIBLE_TOOLS = frozenset(
    {
        "search_books",
        "search_web",
        "list_posts",
        "save_post",
        "save_posts_batch",
        "update_post",
        "update_profile",
    }
)

# D1b's structured generation (titles, then five variants per idea) runs with
# nobody watching: `Runner.run` in generator.py treats any interruption as a
# hard failure of the whole batch, because there is no human on that path to
# answer an approval request. A write tool has no legitimate use during
# proposal-only generation anyway — saving is a separate, later phase the
# client confirms explicitly — so the safe fix is to never show one to the
# model here, rather than trust a cheap, low-effort model not to reach for it.
GENERATION_VISIBLE_TOOLS = frozenset(
    {
        "search_books",
        "search_web",
        "list_posts",
    }
)

INTERNAL_UI_TOOLS = frozenset(
    {
        "ui_create_generation_batch",
        "ui_put_generation_titles",
        "ui_start_generation_idea",
        "ui_complete_generation_idea",
        "ui_fail_generation_idea",
        "ui_fail_generation_batch",
        "ui_select_generation_variant",
        "ui_patch_generation_variant",
        "ui_cancel_generation_batch",
        "ui_get_generation_batch",
        "ui_get_current_generation_batch",
        "ui_list_library",
        "ui_list_saved_posts",
        "ui_get_saved_post",
    }
)
