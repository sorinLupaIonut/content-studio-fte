"""The public HTTP contract of the harness."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from content_studio.language import DEFAULT_LANGUAGE, Language


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
    language: Language = DEFAULT_LANGUAGE

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
    language: Language = DEFAULT_LANGUAGE


class TrustedDecisionsRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    decisions: list[ApprovalDecision] = Field(min_length=1)
    language: Language = DEFAULT_LANGUAGE


class MeResponse(BaseModel):
    principal_id: str
    email: str
    provider: str
    is_development: bool
    # Which account the interface is looking at, and whether to show the admin
    # entry at all. `is_admin` is a hint for the navigation only - every admin
    # route checks the role again on the server, because a hidden link is not a
    # permission.
    is_admin: bool = False
    client_slug: str | None = None
    client_name: str | None = None


ProfileGroup = Literal[
    "identity",
    "ideal_client",
    "voice",
    "offer",
    "pillars",
    "ctas",
    "restrictions",
    "results",
]
ProfileBlockKind = Literal["paragraph", "bullet", "ordered", "quote"]


class ProfileBlock(BaseModel):
    kind: ProfileBlockKind
    text: str = Field(min_length=1, max_length=12_000)

    @field_validator("text")
    @classmethod
    def compact_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("profile block must not be blank")
        return value


class ProfileSection(BaseModel):
    key: str
    title: str
    group: ProfileGroup
    update_name: str = Field(exclude=True)
    blocks: list[ProfileBlock]
    read_only: bool = False


class ProfileSectionsResponse(BaseModel):
    sections: list[ProfileSection]


class ProfileUpdateRequest(BaseModel):
    blocks: list[ProfileBlock] = Field(min_length=1, max_length=250)


class CreateAccountRequest(BaseModel):
    """Provision one tester. Admin-only; see the `administrator` dependency."""

    principal_id: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    client_slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    client_name: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="google", max_length=40)
    role: Literal["user", "admin"] = "user"
    # The one-button start Sorin asked for: a copy of somebody's profile, never a
    # reference to it. `None` means an empty profile written from scratch.
    profile_from: str | None = Field(default=None, max_length=64)
    budget_micros: int = Field(default=1_000_000, ge=0, le=1_000_000_000)


class SetBudgetRequest(BaseModel):
    """A lifetime allowance, in integer micro-dollars. 1_000_000 = $1.00."""

    budget_micros: int = Field(ge=0, le=1_000_000_000)
