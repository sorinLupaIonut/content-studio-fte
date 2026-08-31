"""D1 orchestration: HTTP requests around the existing agent and durable gate.

The harness is the control plane: it owns the database handles and the audit, and
opens one isolated MCP run per request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agents import Runner
from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig
from agents.run_state import RunState
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from content_studio.audit import Audit, GateError
from content_studio.config import (
    E2B_API_KEY,
    MCP_TIMEOUT,
    MCP_URL,
    SKILLS_DIR,
    MissingConfig,
    database_url,
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
from content_studio.harness.conversations import (
    ConversationLog,
    dictated_batch_request,
    render_transcript,
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
from content_studio.sandbox import sandbox_run_config
from content_studio.worker import (
    GATED_TOOLS,
    build_worker,
    describe_request,
    new_session_id,
    read_profile,
)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

#: What each backend probe in `/health` gets before it is called unreachable.
#:
#: THREE SECONDS WAS A WARM-PATH BUDGET ON A STACK THAT IS DESIGNED TO BE COLD.
#: Everything here scales to zero on purpose - ACA replicas, and Neon's compute,
#: which suspends after a few idle minutes - so the FIRST probe after a quiet
#: hour pays every cold start at once, and that is exactly the probe somebody is
#: watching.
#:
#: Both halves were measured failing on 2026-08-31:
#:
#: · Live on Azure, `/health` reported `mcp: does not answer (TimeoutError)` and
#:   returned in 3.6s while the MCP container's own log showed every
#:   `POST /mcp` answered `200 OK`. The probe opens a NEW streamable-HTTP
#:   session each time - DNS, TCP, TLS, `initialize`,
#:   `notifications/initialized`, `tools/list` - across the environment's
#:   internal ingress. The server was never the problem; the budget was.
#: · Locally, the first probe against a suspended Neon compute reported
#:   `Postgres does not answer (TimeoutError)`; the second, warm, said `ready`.
#:
#: A studio that works reporting itself `degraded` is worse than a slow page:
#: `/health` is the first thing anyone looks at, and `deploy.ps1`'s own health
#: gate fails on it.
#:
#: The two probes run CONCURRENTLY now, so the endpoint costs the slower of them
#: rather than their sum. That is what makes six affordable: the liveness probe
#: in `infra/main.bicep` allows 10 seconds, and sequential 6 + 6 would restart a
#: healthy container.
HEALTH_PROBE_SECONDS = 6


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
        raise HarnessError(500, "the saved state holds invalid approval requests")

    decision_by_id: dict[str, ApprovalDecision] = {}
    for decision in decisions:
        if decision.call_id in decision_by_id:
            raise HarnessError(422, f"two decisions arrived for {decision.call_id!r}")
        decision_by_id[decision.call_id] = decision

    missing = request_by_id.keys() - decision_by_id.keys()
    extra = decision_by_id.keys() - request_by_id.keys()
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(sorted(missing)))
        if extra:
            details.append("unknown: " + ", ".join(sorted(extra)))
        raise HarnessError(
            422,
            "the decisions do not match the pending requests (" + "; ".join(details) + ")",
        )

    return {
        call_id: (decision_by_id[call_id], request)
        for call_id, request in request_by_id.items()
    }


def validate_session_id(session_id: str) -> str:
    """Keep the public id safe to reuse as an HTTP header and database key."""
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HarnessError(422, "session_id holds characters that are not allowed")
    return session_id


def _client_header() -> dict[str, str]:
    """The current request's client, when one has been bound.

    Empty when nothing bound it - the CLI, a health probe, every existing test -
    and an absent header is what makes the MCP server fall back to `CLIENT_SLUG`.
    """
    slug = CURRENT_CLIENT.get()
    return {CLIENT_HEADER: slug} if slug else {}


class HarnessService:
    """Long-lived database handles plus one isolated MCP run per request."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.trail: Audit | None = None
        self.database_error: str | None = None
        # Held so the garbage collector does not reclaim a write that nobody is
        # awaiting. Fire-and-forget still has to keep a reference until it fires.
        self._trace_writes: set[asyncio.Task] = set()
        # Built before the coordinators because both take it.
        self.accounts = AccountDirectory(self._internal_data_mcp)
        # The one-conversation-per-lot ledger (2026-08-27). Built before the
        # generator because the generator speaks every batch step into it.
        # The engine getter is a lambda because `start()` creates the engine
        # after this constructor has already run.
        self.conversations = ConversationLog(
            self._internal_data_mcp, lambda: self.engine
        )
        self.generator = GenerationCoordinator(
            self._generation_data_mcp,
            self._internal_data_mcp,
            self.accounts,
            conversations=self.conversations,
        )
        self.chat = ChatCoordinator(
            self._data_mcp,
            self._internal_data_mcp,
            self.accounts,
            orchestrator=self._execute_chat_trigger,
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
        if self.engine is None or self.trail is None:
            missing.append("DATABASE_URL")
        if not SKILLS_DIR.is_dir():
            missing.append("SKILLS_DIR")
        # The folder being on disk is half the answer. Since 2026-08-27 the
        # method reaches the model only through a container, so no key means no
        # method - and the failure lands as a MissingConfig traceback deep in the
        # run rather than as a refusal to start it. Named here, it is one line.
        if not E2B_API_KEY:
            missing.append("E2B_API_KEY")
        if missing:
            raise HarnessError(
                503,
                "the harness cannot start a run; missing: " + ", ".join(missing),
            )
        return self.engine, self.trail

    async def health(
        self, observability: dict[str, object] | None = None
    ) -> HealthResponse:
        openai_ok = has_openai_key()
        skills_ok = SKILLS_DIR.is_dir()
        sandbox_ok = bool(E2B_API_KEY)

        # A TIMEOUT AND A REFUSAL ARE NOT THE SAME NEWS, and the first probe after
        # a quiet hour is almost always the first. Both backends sleep on purpose
        # - the MCP container scales to zero, Neon suspends its compute - and
        # waking either takes longer than any budget this endpoint can afford,
        # because `/health` has to answer inside the liveness probe's 10 seconds.
        # Measured 2026-08-31 on the live deployment: one probe `degraded`, the
        # next three `ready` in 0.6s. Saying "does not answer" for that is a false
        # alarm on the one page an operator reads first.
        def asleep_or_broken(exc: BaseException, what: str) -> str:
            if isinstance(exc, TimeoutError):
                return (
                    f"{what} did not answer within {HEALTH_PROBE_SECONDS}s. Most"
                    " likely asleep (scale-to-zero) - a real request wakes it, given"
                    " patience. If a second check says the same, it really is down."
                )
            return f"{what} does not answer ({type(exc).__name__})."

        async def probe_database() -> tuple[bool, str]:
            if self.engine is None:
                return False, self.database_error or "DATABASE_URL is missing."
            try:
                async with asyncio.timeout(HEALTH_PROBE_SECONDS):
                    async with self.engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                return True, "The Postgres connection answers."
            except Exception as exc:  # noqa: BLE001
                return False, asleep_or_broken(exc, "Postgres")

        async def probe_mcp() -> tuple[bool, str]:
            probe = self._data_mcp("health-probe")
            try:
                async with asyncio.timeout(HEALTH_PROBE_SECONDS):
                    await probe.connect()
                    tools = await probe.list_tools()
                return True, f"Connected; {len(tools)} tools available."
            except Exception as exc:  # noqa: BLE001
                return False, asleep_or_broken(exc, "The MCP server")
            finally:
                await probe.cleanup()

        # Concurrent on purpose - see the note on the two budgets above. Neither
        # coroutine raises, so `gather` cannot fail here; each returns its own
        # verdict and its own sentence.
        (database_ok, database_detail), (mcp_ok, mcp_detail) = await asyncio.gather(
            probe_database(), probe_mcp()
        )

        backends = {
            "openai": BackendHealth(
                configured=openai_ok,
                active=openai_ok,
                detail=(
                    "Key configured; no model call is made in health."
                    if openai_ok
                    else "OPENAI_API_KEY is missing."
                ),
            ),
            "postgres": BackendHealth(
                configured=self.engine is not None,
                active=database_ok,
                detail=database_detail,
            ),
            "mcp": BackendHealth(configured=True, active=mcp_ok, detail=mcp_detail),
            "skills": BackendHealth(
                configured=skills_ok,
                active=skills_ok,
                detail=(
                    "The skills folder is where it should be."
                    if skills_ok
                    else "The skills folder is not on disk."
                ),
            ),
            # THIS ENDPOINT SAID `ready` THROUGH A COMPLETE OUTAGE. From the
            # day the sandbox came back (2026-08-27) until 2026-08-31 the
            # deployed harness had no E2B_API_KEY: every batch died in a third
            # of a second, and the page an operator reads first reported four
            # green backends, because `skills` checks that the folder is on
            # disk and nothing checked that it could be delivered. The folder
            # and the door to it are two facts, so they are two rows.
            "sandbox": BackendHealth(
                configured=sandbox_ok,
                active=sandbox_ok,
                detail=(
                    "Key configured; no container is started in health."
                    if sandbox_ok
                    else "E2B_API_KEY is missing: the method cannot reach the model."
                ),
            ),
            "artifacts": BackendHealth(
                configured=False,
                active=False,
                detail=(
                    "Deferred to D5 on purpose; posts stay domain data, "
                    "not artifacts."
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
                        "detail", "Telemetry was never initialised."
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
                    .get("detail", "Phoenix was never initialised.")
                ),
            ),
        }
        required = (openai_ok, database_ok, mcp_ok, skills_ok, sandbox_ok)
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
                f"the session already has run {pending['id']} waiting for approval",
            )

        run_id = await trail.open_run(session_id, message)
        if run_id is None:
            raise HarnessError(503, "the run could not be opened in durable state")

        data_mcp = self._data_mcp(session_id, principal_id)
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
            worker = build_worker(profile_md, data_mcp, language=language)
            sandbox_cm = sandbox_run_config(f"run-{run_id[:8]}")
            session = SQLAlchemySession(
                session_id, engine=engine, create_tables=True, ensure_ascii=False
            )
            async with sandbox_cm as sandbox:
                result = await Runner.run(
                    worker,
                    message,
                    session=session,
                    run_config=self._run_config(session_id, sandbox),
                )
            return await self._finish(run_id, session_id, result, trail)
        except HarnessError:
            raise
        except Exception as exc:  # noqa: BLE001
            await trail.failed(run_id, exc)
            raise HarnessError(502, f"the run failed ({type(exc).__name__})") from exc
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
                502, f"the profile cannot be read right now ({type(exc).__name__})"
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
                502, f"the profile cannot be read right now ({type(exc).__name__})"
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
            "Prepare a single profile update. Call `update_profile` exactly once "
            "with the section and the text below, without rephrasing. Do not "
            "call another tool and do not assume the save is approved; the "
            "application's gate will ask the user to confirm.\n\n"
            f"SECTION: {section.update_name}\n"
            "EXACT TEXT BETWEEN THE DELIMITERS:\n"
            "<profile-section>\n"
            f"{new_text}\n"
            "</profile-section>"
        )
        result = await self.run(message, session_id)
        if result.status != "pending" or not result.requests:
            raise HarnessError(
                502, "the agent did not prepare the profile approval request"
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
            raise CodedError(
                502,
                f"the saved posts cannot be read ({type(exc).__name__})",
                "saved_posts_unreadable",
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
                "these variants are not chosen, or are not ready: "
                + ", ".join(unknown),
            )

        session_id = self._identity_session(
            "posts-save", f"{principal_id}-{uuid.uuid4().hex[:8]}"
        )
        message = (
            "Save for good the posts Viorela chose. Call `save_posts_batch` "
            "exactly once, with exactly the list of ids below, in the same "
            "order, without adding or removing any. Do not call another tool "
            "and do not assume the save is approved; the application's gate "
            "will ask her to confirm.\n\n"
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
            "Replace the saved post below. Call `update_post` exactly once, with "
            "`post_id` and with the COMPLETE content between the delimiters, "
            "copied literally, without rephrasing anything and without filling "
            "in fields of your own. Do not call another tool; the application's "
            "gate will ask her to confirm.\n\n"
            f"POST_ID: {post_id}\n"
            "EXACT CONTENT BETWEEN THE DELIMITERS:\n"
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
        raise CodedError(
            502,
            f"the agent did not prepare the application's exact request ({mismatch})",
            "gate_mismatch",
        )

    @staticmethod
    def _mismatch(
        result: RunResponse, tool_name: str, expected: dict[str, Any]
    ) -> str | None:
        if result.status != "pending" or len(result.requests) != 1:
            return "did not stop at the gate with a single request"
        request = result.requests[0]
        if request.tool_name != tool_name:
            return f"asked for {request.tool_name!r} instead of {tool_name!r}"
        for key, value in expected.items():
            if request.arguments.get(key) != value:
                return f"the field {key!r} was modified"
        return None

    async def start_generation(
        self,
        principal_id: str,
        request: GenerationStartRequest,
        *,
        dictate: bool = True,
    ) -> dict[str, Any]:
        """Launch a batch into the active conversation.

        `dictate` is True on the buttons door, where the press becomes her
        sentence in the transcript. The chat door passes False — her actual
        words are already in the session — except when the conversation rolls,
        because the words then sit in the archived one.
        """
        self._require_ready()
        # Before the batch, not during: one batch is a title call plus ten detail
        # calls, and an account already at its limit should be told so now rather
        # than eleven calls later. The generator checks again between ideas.
        await self.accounts.require_budget()
        try:
            # One conversation carries at most one lot (2026-08-27). A second
            # lot rolls the conversation automatically — no confirmation, per
            # the product decision — and the old lot leaves the interface in
            # the same transaction.
            conversation = await self.conversations.active(principal_id)
            rolled = False
            if conversation.get("batch_id") is not None:
                conversation = await self.conversations.begin_new(principal_id)
                rolled = True
            session_id = str(conversation["session_id"])
            if dictate or rolled:
                await self.conversations.witness(
                    session_id,
                    "user",
                    dictated_batch_request(
                        request.format,
                        request.pillar,
                        request.source,
                        request.focus,
                    ),
                )
            batch = await self.generator.start(
                principal_id,
                request,
                self.trail,
                conversation_session_id=session_id,
            )
            with suppress(Exception):
                await self.conversations.bind_batch(
                    principal_id, str(batch["id"])
                )
            return batch
        except ActiveBatchError as exc:
            raise CodedError(409, exc.detail, exc.code) from exc
        except ValueError as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("start_generation failed for %s", principal_id)
            raise CodedError(
                502,
                f"the generator could not start ({type(exc).__name__})",
                "generation_start_failed",
            ) from exc

    async def current_generation(
        self, principal_id: str
    ) -> dict[str, Any] | None:
        try:
            current = await self.generator.current(principal_id)
            if current is not None:
                # A batch created before the conversations ledger existed is
                # adopted into the active conversation on first read, so the
                # two pointers cannot stay in disagreement.
                with suppress(Exception):
                    conversation = await self.conversations.active(principal_id)
                    if conversation.get("batch_id") is None:
                        await self.conversations.bind_batch(
                            principal_id, str(current["id"])
                        )
            return current
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                502, f"the current batch cannot be read ({type(exc).__name__})"
            ) from exc

    async def conversation_transcript(self, principal_id: str) -> dict[str, Any]:
        """The active conversation, verbatim: what the agent's session holds.

        Dialogue items come back whole, tool calls as collapsed rows — the
        three-tier display decision of 2026-08-27. Read straight off the SDK's
        session storage so the window cannot drift from the model's input.
        """
        self._require_ready()
        try:
            conversation = await self.conversations.active(principal_id)
            items = await self.conversations.items(
                str(conversation["session_id"])
            )
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the conversation cannot be read ({type(exc).__name__})",
                "conversation_unreadable",
            ) from exc
        return {
            "session_id": str(conversation["session_id"]),
            "batch_id": conversation.get("batch_id"),
            "items": render_transcript(items),
        }

    async def new_conversation(self, principal_id: str) -> dict[str, Any]:
        """Archive the conversation and start fresh; the old lot goes with it."""
        self._require_ready()
        try:
            conversation = await self.conversations.active(principal_id)
            batch_id = conversation.get("batch_id")
            if batch_id is not None:
                # A lot still generating is stopped before its conversation is
                # archived; a finished one simply leaves the interface.
                with suppress(Exception):
                    await self.generator.cancel(principal_id, UUID(str(batch_id)))
            fresh = await self.conversations.begin_new(principal_id)
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the new conversation could not start ({type(exc).__name__})",
                "conversation_start_failed",
            ) from exc
        return {"session_id": str(fresh["session_id"])}

    async def generation_batch(
        self, principal_id: str, batch_id: UUID
    ) -> dict[str, Any]:
        try:
            return await self.generator.get(principal_id, batch_id)
        except GenerationAccessError as exc:
            raise CodedError(404, exc.detail, exc.code) from exc
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the batch cannot be read ({type(exc).__name__})",
                "batch_unreadable",
            ) from exc

    async def generation_events(
        self, principal_id: str, batch_id: UUID, sequence: int
    ):
        await self.generation_batch(principal_id, batch_id)
        return self.generator.events(principal_id, batch_id, sequence)

    async def develop_generation_idea(
        self,
        principal_id: str,
        batch_id: UUID,
        ordinal: int,
        *,
        language: Language = DEFAULT_LANGUAGE,
        dictate: bool = True,
    ) -> dict[str, Any]:
        """Start the five variants for one idea. Returns immediately, 202.

        `language` is a parameter and not a default because it was a default
        until 2026-08-31, and that was a bug with one visible symptom: a batch
        of ten titles came back in English - `start_generation` carries the
        language - and the post itself came back in Romanian, because THIS call
        never carried it and fell to `DEFAULT_LANGUAGE`. The whole cost of a
        run is in the detail phase, so the half that was wrong was the half
        worth paying for. Both doors are fixed together: the click stamps it in
        `StudioApiClient`, and the chat trigger below passes the language of the
        conversation it was asked in.

        The budget is checked here AND again inside the task, for the same
        reason `start_generation` checks before a batch: this endpoint is the
        moment a person decides to spend, and it should refuse then rather than
        after the money is gone. `dictate` follows the same rule as on
        `start_generation`: the click speaks, the chat already spoke.
        """
        self._require_ready()
        await self.accounts.require_budget()
        try:
            return await self.generator.develop(
                principal_id,
                batch_id,
                ordinal,
                language=language,
                trail=self.trail,
                dictate=dictate,
            )
        except GenerationAccessError as exc:
            raise CodedError(404, exc.detail, exc.code) from exc
        except ValueError as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the idea could not be developed ({type(exc).__name__})",
                "idea_develop_failed",
            ) from exc

    async def cancel_generation(
        self, principal_id: str, batch_id: UUID
    ) -> dict[str, Any]:
        try:
            return await self.generator.cancel(principal_id, batch_id)
        except GenerationAccessError as exc:
            raise CodedError(404, exc.detail, exc.code) from exc
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the batch could not be stopped ({type(exc).__name__})",
                "batch_cancel_failed",
            ) from exc

    async def select_generation_variant(
        self, principal_id: str, variant_id: UUID
    ) -> dict[str, Any]:
        try:
            return await self.generator.select(principal_id, variant_id)
        except ValueError as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the variant could not be selected ({type(exc).__name__})",
                "variant_select_failed",
            ) from exc

    async def library(self, principal_id: str) -> list[dict[str, Any]]:
        try:
            return await self.generator.library(principal_id)
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the library cannot be read ({type(exc).__name__})",
                "library_unreadable",
            ) from exc

    async def _execute_chat_trigger(
        self,
        principal_id: str,
        name: str,
        arguments: dict[str, Any],
        language: Language,
    ) -> None:
        """Execute one accepted trigger intent through the buttons' pipeline.

        Called by the chat coordinator after a run in which the model called
        `start_generation` or `develop_idea` and the tool accepted. The tool
        only recorded and validated; the model work happens here, under the
        authenticated principal — never one the model named.
        """
        if name == "start_generation":
            request = GenerationStartRequest.model_validate(
                {
                    "format": arguments.get("format"),
                    "pillar": arguments.get("pillar"),
                    "source": arguments.get("source"),
                    "focus": arguments.get("focus"),
                    "replace_current": True,
                    "language": language,
                }
            )
            await self.start_generation(principal_id, request, dictate=False)
        elif name == "develop_idea":
            current = await self.generator.current(principal_id, public=False)
            if current is None:
                return
            await self.develop_generation_idea(
                principal_id,
                UUID(str(current["id"])),
                int(arguments.get("idea", 0)),
                language=language,
                dictate=False,
            )

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
                raise ValueError("this chat target belongs to a later step")
            # The chat writes into the SAME session the buttons dictate into:
            # one conversation, two ways of speaking (2026-08-27).
            conversation = await self.conversations.active(principal_id)
            return await self.chat.start(
                principal_id,
                request,
                target_context,
                engine,
                trail,
                session_id=str(conversation["session_id"]),
            )
        except ActiveChatError as exc:
            raise CodedError(409, exc.detail, exc.code) from exc
        except (GenerationAccessError, ChatAccessError) as exc:
            raise CodedError(404, exc.detail, exc.code) from exc
        except (TypeError, ValueError) as exc:
            raise HarnessError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise CodedError(
                502,
                f"the chat could not start ({type(exc).__name__})",
                "chat_start_failed",
            ) from exc

    async def chat_events(self, principal_id: str, run_id: str, sequence: int):
        try:
            return self.chat.events(principal_id, run_id, sequence)
        except ChatAccessError as exc:
            raise CodedError(404, exc.detail, exc.code) from exc

    async def cancel_chat(self, principal_id: str, run_id: str) -> dict[str, str]:
        try:
            return await self.chat.cancel(principal_id, run_id)
        except ChatAccessError as exc:
            raise CodedError(404, exc.detail, exc.code) from exc

    async def pending(self, session_id: str) -> PendingResponse:
        _, trail = self._require_ready()
        session_id = validate_session_id(session_id)
        try:
            pending = await trail.pending_run(session_id)
        except GateError as exc:
            raise HarnessError(503, str(exc)) from exc
        if pending is None:
            raise HarnessError(404, "the session has no run waiting for approval")
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
            raise HarnessError(404, "the run no longer waits for a decision in this session")

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
            sandbox_cm = sandbox_run_config(f"resume-{run_id[:8]}")
            state = await RunState.from_string(worker, str(pending["state"]))

            runtime_requests = {
                describe_request(item)[2]: item for item in state.get_interruptions()
            }
            if runtime_requests.keys() != matched.keys():
                raise HarnessError(409, "the RunState requests no longer match the pending state")

            enriched: list[dict[str, Any]] = []
            rejected: list[tuple[str, str]] = []
            for call_id, (decision, stored) in matched.items():
                request = runtime_requests[call_id]
                tool_name = str(stored.get("tool_name", "?"))
                if decision.approved:
                    state.approve(request)
                else:
                    reason = decision.reason.strip() or (
                        "Viorela did not approve the write. Do not insist; "
                        "ask her what she wants changed."
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
            async with sandbox_cm as sandbox:
                result = await Runner.run(
                    worker,
                    state,
                    session=session,
                    run_config=self._run_config(session_id, sandbox),
                )
            return await self._finish(run_id, session_id, result, trail)
        except HarnessError:
            raise
        except Exception as exc:  # noqa: BLE001
            if resumed:
                await trail.failed(run_id, exc)
            raise HarnessError(502, f"resuming the run failed ({type(exc).__name__})") from exc
        finally:
            await data_mcp.cleanup()

    @staticmethod
    def _run_config(session_id: str, sandbox) -> RunConfig:
        # Named, so Phoenix can tell one conversation from another; see the note
        # on `workflow_name` in generator.py.
        #
        # `sandbox` is required rather than optional: the worker is a
        # `SandboxAgent` and its method lives in a container, so a run config
        # built without one is a run that cannot start. Making it a parameter
        # with no default is what stops the next caller from finding that out
        # in production.
        return RunConfig(
            workflow_name=f"Conversation {session_id[:16]}",
            group_id=session_id,
            sandbox=sandbox,
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
