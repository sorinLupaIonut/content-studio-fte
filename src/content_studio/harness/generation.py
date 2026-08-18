"""Strict D1b contracts for title-first generation and browser event streams."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FormatChoice = Literal["Reel", "Carusel", "Stories"]
PillarChoice = Literal[
    "Poziționare",
    "Educație",
    "Conexiune",
    "Conversie",
    "Magnetism",
]
SourceChoice = Literal["Cărți", "Internet", "Memorie", "Combinat"]
HookType = Literal["PROVOCARE", "CIFRA", "SECRET", "INTREBARE", "CONTRAST"]

HOOK_TYPES: tuple[str, ...] = (
    "PROVOCARE",
    "CIFRA",
    "SECRET",
    "INTREBARE",
    "CONTRAST",
)

StreamEventType = Literal[
    "text.delta",
    "status",
    "titles.ready",
    "idea.ready",
    "idea.failed",
    "ui.patch",
    "approval.required",
    "completed",
    "cancelled",
    "error",
    "heartbeat",
]


class StrictContract(BaseModel):
    """Reject fields the API did not ask for instead of silently dropping them."""

    model_config = ConfigDict(extra="forbid")


class IdeaTitle(StrictContract):
    ordinal: int = Field(ge=1, le=10)
    title: str = Field(min_length=3, max_length=160)
    angle: str = Field(min_length=3, max_length=600)


class IdeaTitles(StrictContract):
    ideas: list[IdeaTitle] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def exact_order(self) -> IdeaTitles:
        ordinals = [idea.ordinal for idea in self.ideas]
        if ordinals != list(range(1, 11)):
            raise ValueError("ideas must be ordered exactly from 1 to 10")
        return self


class FormatDetails(StrictContract):
    """The format-specific production body shared by Reel, Carusel and Stories."""

    content_blocks: list[str] = Field(min_length=1, max_length=12)
    visual_direction: str = Field(min_length=3, max_length=2_000)
    duration_or_count: str = Field(min_length=1, max_length=120)


class IdeaVariant(StrictContract):
    hook_type: HookType
    hook: str = Field(min_length=3, max_length=500)
    script: str = Field(min_length=3, max_length=12_000)
    caption: str = Field(min_length=3, max_length=8_000)
    hashtags: list[str] = Field(min_length=3, max_length=5)
    cta: str = Field(min_length=2, max_length=1_000)
    source: str = Field(min_length=2, max_length=2_000)
    format_details: FormatDetails

    @field_validator("hashtags")
    @classmethod
    def hashtag_shape(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        invalid = (
            not value.startswith("#") or any(c.isspace() for c in value)
            for value in normalized
        )
        if any(invalid):
            raise ValueError("each hashtag must be one whitespace-free value beginning with #")
        if len(set(normalized)) != len(normalized):
            raise ValueError("hashtags must be unique")
        return normalized


class IdeaDetails(StrictContract):
    idea_ordinal: int = Field(ge=1, le=10)
    title: str = Field(min_length=3, max_length=160)
    variants: list[IdeaVariant] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def one_variant_per_hook_in_order(self) -> IdeaDetails:
        hook_types = [variant.hook_type for variant in self.variants]
        if hook_types != list(HOOK_TYPES):
            raise ValueError(
                "variants must contain PROVOCARE, CIFRA, SECRET, INTREBARE and "
                "CONTRAST in that order"
            )
        return self


class GenerationBatchRequest(StrictContract):
    format: FormatChoice
    pillar: PillarChoice
    source: SourceChoice
    focus: str | None = Field(default=None, max_length=2_000)
    material_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("focus")
    @classmethod
    def blank_focus_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def materials_belong_to_book_sources(self) -> GenerationBatchRequest:
        if self.material_ids and self.source not in {"Cărți", "Combinat"}:
            raise ValueError("material_ids are available only for Cărți or Combinat")
        return self


class GenerationStartRequest(GenerationBatchRequest):
    replace_current: bool = False


class VariantSelectionRequest(StrictContract):
    selected: Literal[True] = True


class StreamEvent(StrictContract):
    sequence: int = Field(ge=0)
    event: StreamEventType
    run_id: str | None = None
    batch_id: UUID | None = None
    idea_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def encode_sse(event: StreamEvent) -> str:
    """Serialize one browser event without allowing control-line injection."""

    return (
        f"id: {event.sequence}\n"
        f"event: {event.event}\n"
        f"data: {event.model_dump_json()}\n\n"
    )


def title_prompt(request: GenerationBatchRequest, source_packet: dict[str, Any]) -> str:
    """The bounded title-only branch of the existing proposal skill."""

    packet = json.dumps(source_packet, ensure_ascii=False)
    return f"""MOD UI STRUCTURAT D1B — TITLURI
Activează skill-ul `propune-postari` și urmează ramura lui pentru UI.

Format: {request.format}
Pilon: {request.pillar}
Sursă: {request.source}
Focus: {request.focus or "fără focus suplimentar"}
Material-sursă colectat o singură dată: {packet}

Răspunde numai prin contractul structurat cerut de aplicație.
"""


def detail_prompt(
    request: GenerationBatchRequest,
    idea: IdeaTitle,
    source_packet: dict[str, Any],
) -> str:
    """The complete five-variant branch for one already-persisted idea."""

    idea_json = json.dumps(idea.model_dump(), ensure_ascii=False)
    packet = json.dumps(source_packet, ensure_ascii=False)
    return f"""MOD UI STRUCTURAT D1B — DETALII
Activează skill-ul `dezvolta-postarea` și urmează ramura lui pentru UI.

Ideea existentă: {idea_json}
Format: {request.format}
Pilon: {request.pillar}
Sursă: {request.source}
Focus: {request.focus or "fără focus suplimentar"}
Material-sursă colectat o singură dată: {packet}

Dezvoltă exact ideea primită. Răspunde numai prin contractul structurat cerut de
aplicație; `idea_ordinal` și `title` rămân identice cu ideea existentă.
"""


def public_batch(batch: dict[str, Any]) -> dict[str, Any]:
    """Remove internal identity, session and source excerpts from an API response."""

    hidden = {"client_id", "owner_principal_id", "session_id", "source_packet"}
    return {key: value for key, value in batch.items() if key not in hidden}
