"""The small contract between the worker and the MCP server."""

from content_studio.config import CLIENT_SLUG

# The conversation id is not a business argument and must not be filled in by the
# model. The worker puts it on the HTTP connection, and the server attaches it to
# the write and to the audit row of the same transaction.
CONVERSATION_HEADER = "X-Content-Conversation-ID"

# The profile is business data, but it has to reach the system prompt whole before
# the agent can work at all. It is read programmatically as an MCP resource: that
# way it does not become a sixth tool the model can call, and the worker still
# runs no SQL of its own.
PROFILE_URI = f"content-data://client/{CLIENT_SLUG}/profile"
