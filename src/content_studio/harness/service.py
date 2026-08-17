"""D1 orchestration: HTTP requests around the existing agent and durable gate.

The harness is the control plane. E2B is only the execution plane, so this module
never creates a live sandbox session itself. Passing `client` and `options` lets
the Agents SDK serialize and later resume the sandbox together with `RunState`.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

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
from content_studio.harness.models import (
    ApprovalDecision,
    BackendHealth,
    HealthResponse,
    PendingResponse,
    RunResponse,
    ToolApprovalRequest,
)
from content_studio.mcp_server.protocol import CONVERSATION_HEADER
from content_studio.worker import (
    GATED_TOOLS,
    build_sandbox,
    build_worker,
    describe_request,
    new_session_id,
    read_profile,
)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


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


class HarnessService:
    """Long-lived database handles plus one isolated MCP/sandbox run per request."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.trail: Audit | None = None
        self.database_error: str | None = None

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

    async def close(self) -> None:
        if self.trail is not None:
            await self.trail.close()
        if self.engine is not None:
            await self.engine.dispose()

    def _data_mcp(self, session_id: str) -> MCPServerStreamableHttp:
        return MCPServerStreamableHttp(
            params={
                "url": MCP_URL,
                "headers": {CONVERSATION_HEADER: session_id},
            },
            name="content-data",
            cache_tools_list=True,
            client_session_timeout_seconds=MCP_TIMEOUT,
            require_approval={"always": {"tool_names": list(GATED_TOOLS)}},
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

    async def health(self) -> HealthResponse:
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
        }
        required = (openai_ok, database_ok, mcp_ok, e2b_ok, skills_ok)
        return HealthResponse(
            status="ready" if all(required) else "degraded", backends=backends
        )

    async def run(self, message: str, session_id: str | None = None) -> RunResponse:
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

        data_mcp = self._data_mcp(session_id)
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
            worker = build_worker(profile_md, data_mcp)
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
        data_mcp = self._data_mcp(session_id)
        resumed = False
        try:
            await data_mcp.connect()
            _, profile_md = await read_profile(data_mcp)
            worker = build_worker(profile_md, data_mcp)
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
