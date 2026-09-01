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
    #: Did the approved write actually land? None when the question does not
    #: apply or could not be answered.
    #:
    #: `status` CANNOT ANSWER IT. A run finishes `completed` when the AGENT
    #: finishes, and an agent whose tool refuses does not crash - it reads the
    #: refusal and writes a sentence about it. On 2026-08-31 the profile page
    #: reported "the change was saved" for every save it had ever offered, while
    #: `update_profile` was raising on all of them: the agent handled the error,
    #: the run completed, and the only place the truth existed was
    #: `runs.output_message`. A gate that reports a write it did not make is
    #: worse than one that refuses out loud.
    applied: bool | None = None


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
    # Which models this account may ask a batch to be written with. One entry
    # means no choice, and the interface draws no picker for it - which is what
    # every account had before 2026-09-01 and what every account but the
    # client's own still has.
    #
    # A HINT FOR THE INTERFACE, exactly like `is_admin` above. The start
    # endpoint asks `config.models_for` again before it honours a model name,
    # because a picker that is not drawn is not a permission.
    models: list[str] = Field(default_factory=list)


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


class SetBudgetRequest(BaseModel):
    """A lifetime allowance, in integer micro-dollars. 1_000_000 = $1.00."""

    budget_micros: int = Field(ge=0, le=1_000_000_000)


class SetDisabledRequest(BaseModel):
    """Suspend or restore one principal. Not a delete - see `SET_DISABLED_SQL`."""

    disabled: bool
