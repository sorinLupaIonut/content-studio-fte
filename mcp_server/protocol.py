"""Contractul mic dintre worker și serverul MCP."""

# ID-ul conversației nu e argument de business și nu trebuie completat de model.
# Worker-ul îl pune pe conexiunea HTTP, iar serverul îl atașează scrierii și
# auditului din aceeași tranzacție.
CONVERSATION_HEADER = "X-Content-Conversation-ID"

# Profilul este date de business, dar trebuie să intre întreg în system prompt
# înainte ca agentul să poată lucra. Îl citim programatic drept resursă MCP: nu
# devine a șasea unealtă pe care modelul o poate chema și worker-ul nu face SQL.
PROFIL_URI = "content-data://client/viorela/profil"
