"""D1 orchestration: HTTP requests around the existing agent and durable gate.

The harness is the control plane. E2B is only the execution plane, so this module
never creates a live sandbox session itself. Passing `client` and `options` lets
the Agents SDK serialize and later resume the sandbox together with `RunState`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agents import Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig
from agents.run_state import RunState
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from content_studio.audit import Audit, GateError
from content_studio.config import (
    MCP_TIMEOUT,
    MCP_URL,
    SKILLS_DIR,
    MissingConfig,
    database_url,
    has_e2b_key,
    has_openai_key,
)
from content_studio.harness.accounts import (
    CURRENT_CLIENT,
    AccountDirectory,
)
from content_studio.harness.chat import (
    ActiveChatError,
    ChatAccessError,
    ChatCoordinator,
    ChatRunAccepted,
    ChatRunRequest,
)
from content_studio.harness.drafts import SavedPostClient
from content_studio.harness.errors import CodedError
from content_studio.harness.generation import GenerationStartRequest
from content_studio.harness.generator import (
    ActiveBatchError,
    GenerationAccessError,
    GenerationCoordinator,
)
from content_studio.harness.models import (
    ApprovalDecision,
    BackendHealth,
    HealthResponse,
    PendingResponse,
    ProfileBlock,
    ProfileSectionsResponse,
    RunResponse,
    ToolApprovalRequest,
)
from content_studio.harness.posts import (
    PostUpdateRequest,
    SavePostsRequest,
    public_post,
)
from content_studio.harness.profile import (
    find_editable_section,
    parse_pillars,
    parse_profile,
    serialize_blocks,
)
from content_studio.language import DEFAULT_LANGUAGE, Language
from content_studio.mcp_server.protocol import (
    CLIENT_HEADER,
    CONVERSATION_HEADER,
    GENERATION_VISIBLE_TOOLS,
    MODEL_VISIBLE_TOOLS,
    OWNER_HEADER,
)
from content_studio.observability import record_agent_traces
from content_studio.worker import (
    GATED_TOOLS,
    build_sandbox,
    build_worker,
    describe_request,
    new_session_id,
    read_profile,
)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


# The generic `except Exception` handlers below answer the browser with a short
# Romanian sentence and the exception class name — deliberately, because the
# client must never read a stack trace. The operator still needs one, so every
# such handler logs it here. This is the first half of D7.
logger = logging.getLogger("content_studio.harness")

@dataclass(slots=True)
class HarnessError(RuntimeError):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def match_decisions(
    requests: list[dict[str, Any]], decisions: list[ApprovalDecision]
) -> dict[str, tuple[ApprovalDecision, dict[str, Any]]]:
    """Validate one and only one human decision for every interrupted call."""
    request_by_id = {str(item.get("call_id", "")): item for item in requests}
    if "" in request_by_id or len(request_by_id) != len(requests):
        raise HarnessError(500, "Starea salvată conține cereri de aprobare invalide.")

    decision_by_id: dict[str, ApprovalDecision] = {}
    for decision in decisions:
        if decision.call_id in decision_by_id:
            raise HarnessError(422, f"Decizia pentru {decision.call_id!r} apare de două ori.")
        decision_by_id[decision.call_id] = decision

    missing = request_by_id.keys() - decision_by_id.keys()
    extra = decision_by_id.keys() - request_by_id.keys()
    if missing or extra:
        details = []
        if missing:
            details.append("lipsesc: " + ", ".join(sorted(missing)))
        if extra:
            details.append("necunoscute: " + ", ".join(sorted(extra)))
        raise HarnessError(
            422,
            "Deciziile nu corespund cererilor pending (" + "; ".join(details) + ").",
        )

    return {
        call_id: (decision_by_id[call_id], request)
        for call_id, request in request_by_id.items()
    }


def validate_session_id(session_id: str) -> str:
    """Keep the public id safe to reuse as an HTTP header and database key."""
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HarnessError(422, "session_id conține caractere nepermise.")
    return session_id


def _client_header() -> dict[str, str]:
    """The current request's client, when one has been bound.

    Empty when nothing bound it - the CLI, a health probe, every existing test -
    and an absent header is what makes the MCP server fall back to `CLIENT_SLUG`.
    """
    slug = CURRENT_CLIENT.get()
    return {CLIENT_HEADER: slug} if slug else {}


class HarnessService:
    """Long-lived database handles plus one isolated MCP/sandbox run per request."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.trail: Audit | None = None
        self.database_error: str | None = None
        # Held so the garbage collector does not reclaim a write that nobody is
        # awaiting. Fire-and-forget still has to keep a reference until it fires.
        self._trace_writes: set[asyncio.Task] = set()
        # Built before the coordinators because both take it.
        self.accounts = AccountDirectory(self._internal_data_mcp)
        self.generator = GenerationCoordinator(
            self._generation_data_mcp, self._internal_data_mcp, self.accounts
        )
        self.chat = ChatCoordinator(
            self._data_mcp, self._internal_data_mcp, self.accounts
        )

    async def start(self) -> None:
        """Configure durable state without making import or boot depend on it."""
        try:
            url, connect_args = database_url()
            self.engine = create_async_engine(
                url, connect_args=connect_args, pool_pre_ping=True
            )
            self.trail = Audit(url, connect_args)
        except (MissingConfig, RuntimeError) as exc:
            self.database_error = str(exc).splitlines()[0]

        # Registered once the trail exists, and only then: without a database
        # there is nowhere for a trace to go, and a processor that drops
        # everything on the floor is worse than one that was never installed.
        if self.trail is not None:
            record_agent_traces(self._keep_trace)

    def _keep_trace(self, run_id: str, payload: dict[str, Any]) -> None:
        """Sink for the SDK's traces. Synchronous, non-blocking, never raises.

        Called from inside the agent's own execution, so it does the least
        possible: schedule the write and return. A failure to schedule is logged
        by the caller and the run continues - Neon is the durable record of
        *what* happened either way, through `runs` and `audit_log`; this row is
        the detail of how.
        """
        if self.trail is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Ended outside the event loop - nothing to schedule onto.
            return
        task = loop.create_task(self.trail.sdk_trace(run_id, payload))
        self._trace_writes.add(task)
        task.add_done_callback(self._trace_writes.discard)

    async def close(self) -> None:
        await self.chat.close()
        await self.generator.close()
        if self.trail is not None:
            await self.trail.close()
        if self.engine is not None:
            await self.engine.dispose()

    def _data_mcp(
        self, session_id: str, principal_id: str | None = None
    ) -> MCPServerStreamableHttp:
        # The owner header travels with the connection, never as a tool argument:
        # `save_posts_batch` is model-visible, and identity the model can type is
        # identity the model can get wrong. Connections without it — the CLI, the
        # generator, plain chat — simply cannot reach that tool's data.
        headers = {CONVERSATION_HEADER: session_id, **_client_header()}
        if principal_id:
            headers[OWNER_HEADER] = principal_id
        return MCPServerStreamableHttp(
            params={
                "url": MCP_URL,
                "headers": headers,
            },
            name="content-data",
            cache_tools_list=True,
            tool_filter={"allowed_tool_names": sorted(MODEL_VISIBLE_TOOLS)},
            client_session_timeout_seconds=MCP_TIMEOUT,
            require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
        )

    def _generation_data_mcp(self, session_id: str) -> MCPServerStreamableHttp:
        """The model's connection for unattended D1b generation: reads only.

        `_data_mcp` is right for chat, where a person is on the other end of an
        approval request. Nothing is on the other end here — `Runner.run` in
        generator.py has no approval loop, so an interruption is a hard failure
        of the whole batch (see the note on `GENERATION_VISIBLE_TOOLS`). None of
        these three tools are ever gated, so `require_approval` has nothing to
        list.
        """
        return MCPServerStreamableHttp(
            params={
                "url": MCP_URL,
                "headers": {CONVERSATION_HEADER: session_id, **_client_header()},
            },
            name="content-data",
            cache_tools_list=True,
            tool_filter={"allowed_tool_names": sorted(GENERATION_VISIBLE_TOOLS)},
            client_session_timeout_seconds=MCP_TIMEOUT,
        )

    def _internal_data_mcp(self, session_id: str) -> MCPServerStreamableHttp:
        """Unfiltered exact-name access for trusted D1b orchestration only."""
        return MCPServerStreamableHttp(
            params={
                "url": MCP_URL,
                "headers": {CONVERSATION_HEADER: session_id, **_client_header()},
            },
            name="content-data-internal",
            cache_tools_list=True,
            use_structured_content=True,
            client_session_timeout_seconds=MCP_TIMEOUT,
        )

    def _require_ready(self) -> tuple[AsyncEngine, Audit]:
        missing = []
        if not has_openai_key():
            missing.append("OPENAI_API_KEY")
        if not has_e2b_key():
            missing.append("E2B_API_KEY")
        if self.engine is None or self.trail is None:
            missing.append("DATABASE_URL")
        if not SKILLS_DIR.is_dir():
            missing.append("SKILLS_DIR")
        if missing:
            raise HarnessError(
                503,
                "Harness-ul nu poate porni un run; lipsesc: " + ", ".join(missing) + ".",
            )
        return self.engine, self.trail

    async def health(
        self, observability: dict[str, object] | None = None
    ) -> HealthResponse:
        openai_ok = has_openai_key()
        e2b_ok = has_e2b_key()
        skills_ok = SKILLS_DIR.is_dir()

        database_ok = False
        database_detail = self.database_error or "DATABASE_URL lipsește."
        if self.engine is not None:
            try:
                async with asyncio.timeout(3):
                    async with self.engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                database_ok = True
                database_detail = "Conexiunea Postgres răspunde."
            except Exception as exc:  # noqa: BLE001
                database_detail = f"Postgres nu răspunde ({type(exc).__name__})."

        mcp_ok = False
        mcp_detail = f"Configurat la {MCP_URL}, dar nu răspunde."
        probe = self._data_mcp("health-probe")
        try:
            async with asyncio.timeout(3):
                await probe.connect()
                tools = await probe.list_tools()
            mcp_ok = True
            mcp_detail = f"Conectat; {len(tools)} unelte disponibile."
        except Exception as exc:  # noqa: BLE001
            mcp_detail = f"MCP nu răspunde ({type(exc).__name__})."
        finally:
            await probe.cleanup()

        backends = {
            "openai": BackendHealth(
                configured=openai_ok,
                active=openai_ok,
                detail=(
                    "Cheie configurată; fără apel de model în health."
                    if openai_ok
                    else "OPENAI_API_KEY lipsește."
                ),
            ),
            "postgres": BackendHealth(
                configured=self.engine is not None,
                active=database_ok,
                detail=database_detail,
            ),
            "mcp": BackendHealth(configured=True, active=mcp_ok, detail=mcp_detail),
            "e2b": BackendHealth(
                configured=e2b_ok,
                active=e2b_ok and skills_ok,
                detail=(
                    "Cheie și skill-uri configurate; sandbox-ul se creează numai la run."
                    if e2b_ok and skills_ok
                    else "E2B_API_KEY sau folderul de skill-uri lipsește."
                ),
            ),
            "artifacts": BackendHealth(
                configured=False,
                active=False,
                detail=(
                    "Amânat explicit până la D5; postările rămân date de domeniu, "
                    "nu artifacts."
                ),
            ),
            # Reported, never required: a studio that cannot be watched still
            # works, and refusing to serve because a telemetry endpoint is down
            # would be the monitoring causing the outage.
            "observability": BackendHealth(
                configured=bool(observability and observability.get("ok")),
                active=bool(observability and observability.get("ok")),
                detail=str(
                    (observability or {}).get(
                        "detail", "Telemetria nu a fost inițializată."
                    )
                ),
            ),
            # Reported separately from Application Insights: they answer
            # different questions, and one being off says nothing about the
            # other. Neither is ever required.
            "phoenix": BackendHealth(
                configured=bool((observability or {}).get("phoenix", {}).get("ok")),
                active=bool((observability or {}).get("phoenix", {}).get("ok")),
                detail=str(
                    (observability or {})
                    .get("phoenix", {})
                    .get("detail", "Phoenix nu a fost inițializat.")
                ),
            ),
        }
        required = (openai_ok, database_ok, mcp_ok, e2b_ok, skills_ok)
        return HealthResponse(
            status="ready" if all(required) else "degraded", backends=backends
        )

    async def run(
        self,
        message: str,
        session_id: str | None = None,
        language: Language = DEFAULT_LANGUAGE,
    ) -> RunResponse:
        await self.accounts.require_budget()
        return await self._run_message(message, session_id, language=language)

    async def _run_message(
        self,
        message: str,
        session_id: str | None = None,
        principal_id: str | None = None,
        language: Language = DEFAULT_LANGUAGE,
    ) -> RunResponse:
        engine, trail = self._require_ready()
        session_id = validate_session_id(session_id or new_session_id())

        try:
            pending = await trail.pending_run(session_id)
        except GateError as exc:
            raise HarnessError(503, str(exc)) from exc
        if pending is not None:
            raise HarnessError(
                409,
                f"Sesiunea are deja run-ul {pending['id']} în așteptarea aprobării.",
            )

        run_id = await trail.open_run(session_id, message)
        if run_id is None:
            raise HarnessError(503, "Run-ul nu a putut fi deschis în starea durabilă.")

        data_mcp = self._data_mcp(session_id, principal_id)
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
            worker = build_worker(profile_md, data_mcp, language=language)
            session = SQLAlchemySession(
                session_id, engine=engine, create_tables=True, ensure_ascii=False
            )
            result = await Runner.run(
                worker,
                message,
                session=session,
                run_config=self._run_config(session_id),
            )
            return await self._finish(run_id, session_id, result, trail)
        except HarnessError:
            raise
        except Exception as exc:  # noqa: BLE001
            await trail.failed(run_id, exc)
            raise HarnessError(502, f"Run-ul a eșuat ({type(exc).__name__}).") from exc
        finally:
            await data_mcp.cleanup()

    async def profile_sections(self, principal_id: str) -> ProfileSectionsResponse:
        """Read the live profile through MCP and expose structured UI blocks."""

        session_id = self._identity_session("profile-read", principal_id)
        data_mcp = self._data_mcp(session_id)
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Profilul nu poate fi citit acum ({type(exc).__name__})."
            ) from exc
        finally:
            await data_mcp.cleanup()
        return ProfileSectionsResponse(
            sections=[*parse_profile(profile_md), *parse_pillars()]
        )

    async def prepare_profile_update(
        self,
        principal_id: str,
        section_key: str,
        blocks: list[ProfileBlock],
    ) -> RunResponse:
        """Ask the normal gated agent to prepare one exact `update_profile` call."""

        read_session = self._identity_session("profile-read", principal_id)
        data_mcp = self._data_mcp(read_session)
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Profilul nu poate fi citit acum ({type(exc).__name__})."
            ) from exc
        finally:
            await data_mcp.cleanup()

        section = find_editable_section(profile_md, section_key)
        if section is None or section.read_only:
            raise CodedError(
                404, "profile section unknown or read-only", "profile_section_unknown"
            )
        new_text = serialize_blocks(blocks)
        if not new_text:
            raise CodedError(422, "section must not be empty", "profile_section_empty")

        session_id = self._identity_session(
            "profile", f"{principal_id}-{uuid.uuid4().hex[:8]}"
        )
        message = (
            "Pregătește o singură actualizare de profil. Cheamă `update_profile` "
            "exact o dată cu secțiunea și textul de mai jos, fără să reformulezi. "
            "Nu chema altă unealtă și nu presupune că salvarea este aprobată; "
            "poarta aplicației va cere confirmarea utilizatoarei.\n\n"
            f"SECȚIUNE: {section.update_name}\n"
            "TEXT EXACT ÎNTRE DELIMITATOARE:\n"
            "<profile-section>\n"
            f"{new_text}\n"
            "</profile-section>"
        )
        result = await self.run(message, session_id)
        if result.status != "pending" or not result.requests:
            raise HarnessError(
                502, "Agentul nu a pregătit cererea de aprobare pentru profil."
            )
        return result

    async def saved_posts(self, principal_id: str) -> list[dict[str, Any]]:
        """The posts written in the studio, newest first."""

        session_id = self._identity_session("posts-read", principal_id)
        internal = self._internal_data_mcp(session_id)
        try:
            await internal.connect()
            items = await SavedPostClient(internal).list()
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Postările salvate nu pot fi citite ({type(exc).__name__})."
            ) from exc
        finally:
            await internal.cleanup()
        return [public_post(item) for item in items]

    async def saved_post(self, principal_id: str, post_id: UUID) -> dict[str, Any]:
        session_id = self._identity_session("posts-read", principal_id)
        internal = self._internal_data_mcp(session_id)
        try:
            await internal.connect()
            post = await SavedPostClient(internal).get(post_id)
        except Exception as exc:  # noqa: BLE001
            raise CodedError(404, "saved post not found", "post_not_found") from exc
        finally:
            await internal.cleanup()
        return public_post(post)

    async def saved_post_context(
        self, principal_id: str, post_id: UUID
    ) -> dict[str, Any]:
        """One server-verified saved post as bounded chat context."""

        post = await self.saved_post(principal_id, post_id)
        return {
            "kind": "saved_post",
            "target_id": str(post_id),
            "post": {
                key: post.get(key)
                for key in (
                    "title",
                    "pillar",
                    "format",
                    "hook",
                    "hook_type",
                    "script",
                    "caption",
                    "hashtags",
                    "cta",
                    "source",
                    "format_details",
                )
            },
        }

    async def prepare_batch_save(
        self, principal_id: str, request: SavePostsRequest
    ) -> RunResponse:
        """Ask the normal gated agent to prepare one exact `save_posts_batch`."""

        wanted = [str(value) for value in request.variant_ids]
        # Checked against the live batch before any model call: a save that could
        # never succeed should cost nothing, and the error should name the reason
        # rather than arrive as a failed tool call.
        batch = await self.generator.current(principal_id, public=False)
        if batch is None:
            raise CodedError(404, "no current batch to save from", "no_current_batch")
        chosen = {
            str(variant["id"])
            for idea in batch.get("ideas", [])
            for variant in idea.get("variants", [])
            if variant.get("is_selected") and variant.get("status") == "ready"
        }
        unknown = [value for value in wanted if value not in chosen]
        if unknown:
            raise HarnessError(
                422,
                "Aceste variante nu sunt alese sau nu sunt gata: "
                + ", ".join(unknown),
            )

        session_id = self._identity_session(
            "posts-save", f"{principal_id}-{uuid.uuid4().hex[:8]}"
        )
        message = (
            "Salvează definitiv postările alese de Viorela. Cheamă "
            "`save_posts_batch` exact o dată, cu exact lista de id-uri de mai jos, "
            "în aceeași ordine, fără să adaugi și fără să scoți vreunul. Nu chema "
            "altă unealtă și nu presupune că salvarea este aprobată; poarta "
            "aplicației va cere confirmarea ei.\n\n"
            f"VARIANT_IDS: {json.dumps(wanted, ensure_ascii=False)}"
        )
        return await self._prepared(
            message,
            session_id,
            principal_id,
            "save_posts_batch",
            {"variant_ids": wanted},
        )

    async def prepare_post_update(
        self, principal_id: str, post_id: UUID, content: PostUpdateRequest
    ) -> RunResponse:
        """Ask the normal gated agent to prepare one exact `update_post`."""

        await self.saved_post(principal_id, post_id)
        payload = content.model_dump(mode="json")
        session_id = self._identity_session(
            "posts-update", f"{principal_id}-{uuid.uuid4().hex[:8]}"
        )
        message = (
            "Înlocuiește postarea salvată de mai jos. Cheamă `update_post` exact o "
            "dată, cu `post_id` și cu conținutul COMPLET dintre delimitatoare, "
            "copiat literal, fără să reformulezi nimic și fără să completezi "
            "câmpuri de la tine. Nu chema altă unealtă; poarta aplicației va cere "
            "confirmarea ei.\n\n"
            f"POST_ID: {post_id}\n"
            "CONȚINUT EXACT ÎNTRE DELIMITATOARE:\n"
            "<post-json>\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            "</post-json>"
        )
        return await self._prepared(
            message,
            session_id,
            principal_id,
            "update_post",
            {"post_id": str(post_id), **payload},
        )

    async def _prepared(
        self,
        message: str,
        session_id: str,
        principal_id: str,
        tool_name: str,
        expected: dict[str, Any],
    ) -> RunResponse:
        """Run the agent and show the approval card only if it typed it exactly.

        The gate protects against an unwanted write, not against a write of the
        wrong thing: she would be approving `save_posts_batch` either way. So the
        prepared arguments are compared with what the application asked for, and a
        run that drifted is failed here rather than offered for approval.
        """
        result = await self._run_message(message, session_id, principal_id)
        mismatch = self._mismatch(result, tool_name, expected)
        if mismatch is None:
            return result

        _, trail = self._require_ready()
        await trail.failed(result.run_id, RuntimeError(mismatch))
        raise HarnessError(
            502,
            "Agentul nu a pregătit exact cererea aplicației, așa că nu îți cer "
            f"confirmarea pe ea ({mismatch}). Încearcă din nou.",
        )

    @staticmethod
    def _mismatch(
        result: RunResponse, tool_name: str, expected: dict[str, Any]
    ) -> str | None:
        if result.status != "pending" or len(result.requests) != 1:
            return "nu s-a oprit la poartă cu o singură cerere"
        request = result.requests[0]
        if request.tool_name != tool_name:
            return f"a cerut {request.tool_name!r} în loc de {tool_name!r}"
        for key, value in expected.items():
            if request.arguments.get(key) != value:
                return f"câmpul {key!r} a fost modificat"
        return None

    async def start_generation(
        self, principal_id: str, request: GenerationStartRequest
    ) -> dict[str, Any]:
        self._require_ready()
        # Before the batch, not during: one batch is a title call plus ten detail
        # calls, and an account already at its limit should be told so now rather
        # than eleven calls later. The generator checks again between ideas.
        await self.accounts.require_budget()
        try:
            return await self.generator.start(principal_id, request, self.trail)
        except ActiveBatchError as exc:
            raise HarnessError(409, str(exc)) from exc
        except ValueError as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("start_generation failed for %s", principal_id)
            raise HarnessError(
                502, f"Generatorul nu a putut porni ({type(exc).__name__})."
            ) from exc

    async def current_generation(
        self, principal_id: str
    ) -> dict[str, Any] | None:
        try:
            return await self.generator.current(principal_id)
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Lotul curent nu poate fi citit ({type(exc).__name__})."
            ) from exc

    async def generation_batch(
        self, principal_id: str, batch_id: UUID
    ) -> dict[str, Any]:
        try:
            return await self.generator.get(principal_id, batch_id)
        except GenerationAccessError as exc:
            raise HarnessError(404, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Lotul nu poate fi citit ({type(exc).__name__})."
            ) from exc

    async def generation_events(
        self, principal_id: str, batch_id: UUID, sequence: int
    ):
        await self.generation_batch(principal_id, batch_id)
        return self.generator.events(principal_id, batch_id, sequence)

    async def cancel_generation(
        self, principal_id: str, batch_id: UUID
    ) -> dict[str, Any]:
        try:
            return await self.generator.cancel(principal_id, batch_id)
        except GenerationAccessError as exc:
            raise HarnessError(404, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Lotul nu a putut fi oprit ({type(exc).__name__})."
            ) from exc

    async def select_generation_variant(
        self, principal_id: str, variant_id: UUID
    ) -> dict[str, Any]:
        try:
            return await self.generator.select(principal_id, variant_id)
        except ValueError as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Varianta nu a putut fi selectată ({type(exc).__name__})."
            ) from exc

    async def library(self, principal_id: str) -> list[dict[str, Any]]:
        try:
            return await self.generator.library(principal_id)
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Biblioteca nu poate fi citită ({type(exc).__name__})."
            ) from exc

    async def start_chat(
        self, principal_id: str, request: ChatRunRequest
    ) -> ChatRunAccepted:
        engine, trail = self._require_ready()
        await self.accounts.require_budget()
        try:
            target_context = None
            if request.target.kind == "generation_variant":
                target_context = await self.generator.variant_context(
                    principal_id, UUID(str(request.target.id))
                )
            elif request.target.kind == "saved_post":
                target_context = await self.saved_post_context(
                    principal_id, UUID(str(request.target.id))
                )
            elif request.target.kind != "general":
                raise ValueError("Această țintă de chat intră într-un pas ulterior.")
            return await self.chat.start(
                principal_id, request, target_context, engine, trail
            )
        except ActiveChatError as exc:
            raise HarnessError(409, str(exc)) from exc
        except (GenerationAccessError, ChatAccessError) as exc:
            raise HarnessError(404, str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"Chatul nu a putut porni ({type(exc).__name__})."
            ) from exc

    async def chat_events(self, principal_id: str, run_id: str, sequence: int):
        try:
            return self.chat.events(principal_id, run_id, sequence)
        except ChatAccessError as exc:
            raise HarnessError(404, str(exc)) from exc

    async def cancel_chat(self, principal_id: str, run_id: str) -> dict[str, str]:
        try:
            return await self.chat.cancel(principal_id, run_id)
        except ChatAccessError as exc:
            raise HarnessError(404, str(exc)) from exc

    async def pending(self, session_id: str) -> PendingResponse:
        _, trail = self._require_ready()
        session_id = validate_session_id(session_id)
        try:
            pending = await trail.pending_run(session_id)
        except GateError as exc:
            raise HarnessError(503, str(exc)) from exc
        if pending is None:
            raise HarnessError(404, "Sesiunea nu are niciun run în așteptarea aprobării.")
        return PendingResponse(
            run_id=str(pending["id"]),
            session_id=session_id,
            input_message=str(pending["input_message"]),
            requests=[
                ToolApprovalRequest.model_validate(item) for item in pending["requests"]
            ],
        )

    async def decide(
        self,
        run_id: str,
        session_id: str,
        decisions: list[ApprovalDecision],
        resolved_by: str,
        language: Language = DEFAULT_LANGUAGE,
    ) -> RunResponse:
        engine, trail = self._require_ready()
        session_id = validate_session_id(session_id)
        try:
            pending = await trail.pending_run(session_id)
        except GateError as exc:
            raise HarnessError(503, str(exc)) from exc
        if pending is None or str(pending["id"]) != run_id:
            raise HarnessError(404, "Run-ul nu mai așteaptă o decizie în această sesiune.")

        matched = match_decisions(pending["requests"], decisions)
        # The gate interrupts *before* the call, so the write happens here, on
        # resume. The owner header therefore has to be on this connection, not
        # only on the one that prepared the run.
        data_mcp = self._data_mcp(session_id, resolved_by)
        resumed = False
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
            # The run resumes with the language the browser is showing now,
            # which is the same one it was started in unless she switched
            # mid-run - in which case following the screen is the right call.
            worker = build_worker(profile_md, data_mcp, language=language)
            state = await RunState.from_string(worker, str(pending["state"]))

            runtime_requests = {
                describe_request(item)[2]: item for item in state.get_interruptions()
            }
            if runtime_requests.keys() != matched.keys():
                raise HarnessError(409, "Cererile din RunState nu mai corespund stării pending.")

            enriched: list[dict[str, Any]] = []
            rejected: list[tuple[str, str]] = []
            for call_id, (decision, stored) in matched.items():
                request = runtime_requests[call_id]
                tool_name = str(stored.get("tool_name", "?"))
                if decision.approved:
                    state.approve(request)
                else:
                    reason = decision.reason.strip() or (
                        "Viorela n-a aprobat scrierea. Nu insista; "
                        "întreab-o ce vrea schimbat."
                    )
                    state.reject(request, rejection_message=reason)
                    rejected.append((tool_name, call_id))
                enriched.append(
                    {
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "approved": decision.approved,
                        "reason": decision.reason,
                    }
                )

            await trail.resume_run(run_id, enriched, resolved_by)
            resumed = True
            for tool_name, call_id in rejected:
                await trail.capability_blocked(run_id, tool_name, call_id)

            session = SQLAlchemySession(
                session_id, engine=engine, create_tables=True, ensure_ascii=False
            )
            result = await Runner.run(
                worker,
                state,
                session=session,
                run_config=self._run_config(session_id),
            )
            return await self._finish(run_id, session_id, result, trail)
        except HarnessError:
            raise
        except Exception as exc:  # noqa: BLE001
            if resumed:
                await trail.failed(run_id, exc)
            raise HarnessError(502, f"Reluarea run-ului a eșuat ({type(exc).__name__}).") from exc
        finally:
            await data_mcp.cleanup()

    @staticmethod
    def _run_config(session_id: str) -> RunConfig:
        client, options = build_sandbox()
        return RunConfig(
            sandbox=SandboxRunConfig(client=client, options=options),
            group_id=session_id,
        )

    @staticmethod
    def _identity_session(prefix: str, principal_id: str) -> str:
        digest = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}"

    @staticmethod
    async def _finish(run_id: str, session_id: str, result, trail: Audit) -> RunResponse:
        if result.interruptions:
            requests = []
            for item in result.interruptions:
                tool_name, arguments, call_id = describe_request(item)
                requests.append(
                    {"call_id": call_id, "tool_name": tool_name, "arguments": arguments}
                )
            state = result.to_state()
            await trail.suspend_run(run_id, requests, state.to_string())
            return RunResponse(
                run_id=run_id,
                session_id=session_id,
                status="pending",
                requests=[
                    ToolApprovalRequest.model_validate(item) for item in requests
                ],
            )

        output = str(result.final_output or "")
        await trail.turn(run_id, result)
        await trail.close_run(run_id, output)
        return RunResponse(
            run_id=run_id,
            session_id=session_id,
            status="completed",
            output=output,
        )
