"""Contractul mic dintre worker și serverul MCP."""

# ID-ul conversației nu e argument de business și nu trebuie completat de model.
# Worker-ul îl pune pe conexiunea HTTP, iar serverul îl atașează scrierii și
# auditului din aceeași tranzacție.
CONVERSATION_HEADER = "X-Content-Conversation-ID"
