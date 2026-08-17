"""The public HTTP contract of the harness."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class BackendHealth(BaseModel):
    configured: bool
    active: bool
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ready", "degraded"]
    backends: dict[str, BackendHealth]


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50_000)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("message")
    @classmethod
    def message_is_not_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ToolApprovalRequest(BaseModel):
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["completed", "pending"]
    output: str | None = None
    requests: list[ToolApprovalRequest] = Field(default_factory=list)


class PendingResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["pending"] = "pending"
    input_message: str
    requests: list[ToolApprovalRequest]


class ApprovalDecision(BaseModel):
    call_id: str = Field(min_length=1)
    approved: bool
    reason: str = Field(default="", max_length=2_000)


class DecisionsRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    decisions: list[ApprovalDecision] = Field(min_length=1)
    resolved_by: str = Field(default="viorela", min_length=1, max_length=200)
