"""Strict D1b contracts for title-first generation and browser event streams."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from content_studio.language import DEFAULT_LANGUAGE, Language, task_note

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
    """The production body: how the thing gets shot or laid out.

    Carusel and Stories always have one. A Reel does not — see
    `SilentReelVariant` for why.
    """

    content_blocks: list[str] = Field(min_length=1, max_length=12)
    visual_direction: str = Field(min_length=3, max_length=2_000)
    duration_or_count: str = Field(min_length=1, max_length=120)


def checked_hashtags(values: list[str]) -> list[str]:
    """The one hashtag rule, shared by every contract that carries hashtags."""

    normalized = [value.strip() for value in values]
    if any(
        not value.startswith("#") or any(char.isspace() for char in value)
        for value in normalized
    ):
        raise ValueError("each hashtag must be one whitespace-free value beginning with #")
    if len(set(normalized)) != len(normalized):
        raise ValueError("hashtags must be unique")
    return normalized


def checked_hook_order(variants: list[Any]) -> None:
    """All five hook types, once each, in the order the tabs are drawn."""

    hook_types = [variant.hook_type for variant in variants]
    if hook_types != list(HOOK_TYPES):
        raise ValueError(
            "variants must contain PROVOCARE, CIFRA, SECRET, INTREBARE and "
            "CONTRAST in that order"
        )


class IdeaVariant(StrictContract):
    """One finished variant as it is stored, whatever format produced it.

    `script` and `format_details` are optional *together*: a silent reel has
    neither, every other format has both. The two model-facing contracts below
    are the exact ones — this is the shape that has to read all of them back,
    which is why it is the permissive one.
    """

    hook_type: HookType
    hook: str = Field(min_length=3, max_length=500)
    script: str | None = Field(default=None, min_length=3, max_length=12_000)
    caption: str = Field(min_length=3, max_length=8_000)
    hashtags: list[str] = Field(min_length=3, max_length=5)
    cta: str = Field(min_length=2, max_length=1_000)
    source: str = Field(min_length=2, max_length=2_000)
    format_details: FormatDetails | None = None

    @field_validator("hashtags")
    @classmethod
    def hashtag_shape(cls, values: list[str]) -> list[str]:
        return checked_hashtags(values)

    @model_validator(mode="after")
    def script_and_production_travel_together(self) -> IdeaVariant:
        if (self.script is None) != (self.format_details is None):
            raise ValueError(
                "script and format_details are both present or both absent"
            )
        return self


class ProducedVariant(StrictContract):
    """What the model fills for Carusel and Stories.

    Written out in full rather than inherited from `IdeaVariant`, because field
    order is the order the model writes in: the script comes before the caption
    that has to echo it.
    """

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
        return checked_hashtags(values)


#: A silent reel's caption carries the whole idea, so it cannot be two lines.
#: The floor is a guard against a degenerate answer, not the target — the target
#: is in `SILENT_REEL_BRIEF`, where the model can actually read it.
SILENT_REEL_CAPTION_FLOOR = 200


class SilentReelVariant(StrictContract):
    """What the model fills for a Reel, which the client films without speaking.

    No script and no production block: there is nothing said out loud and
    nothing shot to a spoken timing. Everything a voice-over would have carried
    is written into the caption instead, which is why its floor is far above the
    produced formats'. The fields are absent from the schema rather than
    nullable so the model cannot spend tokens inventing them.
    """

    hook_type: HookType
    hook: str = Field(min_length=3, max_length=500)
    caption: str = Field(min_length=SILENT_REEL_CAPTION_FLOOR, max_length=8_000)
    hashtags: list[str] = Field(min_length=3, max_length=5)
    cta: str = Field(min_length=2, max_length=1_000)
    source: str = Field(min_length=2, max_length=2_000)

    @field_validator("hashtags")
    @classmethod
    def hashtag_shape(cls, values: list[str]) -> list[str]:
        return checked_hashtags(values)


class IdeaDetails(StrictContract):
    """One idea's five variants as they are stored and read back."""

    idea_ordinal: int = Field(ge=1, le=10)
    title: str = Field(min_length=3, max_length=160)
    variants: list[IdeaVariant] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def one_variant_per_hook_in_order(self) -> IdeaDetails:
        checked_hook_order(self.variants)
        return self


class ProducedIdeaDetails(StrictContract):
    """The detail contract for Carusel and Stories."""

    idea_ordinal: int = Field(ge=1, le=10)
    title: str = Field(min_length=3, max_length=160)
    variants: list[ProducedVariant] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def one_variant_per_hook_in_order(self) -> ProducedIdeaDetails:
        checked_hook_order(self.variants)
        return self


class SilentReelDetails(StrictContract):
    """The detail contract for a Reel."""

    idea_ordinal: int = Field(ge=1, le=10)
    title: str = Field(min_length=3, max_length=160)
    variants: list[SilentReelVariant] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def one_variant_per_hook_in_order(self) -> SilentReelDetails:
        checked_hook_order(self.variants)
        return self


#: The detail phase asks for one exact schema per format, never a union.
DETAIL_CONTRACTS: dict[str, type[StrictContract]] = {
    "Reel": SilentReelDetails,
    "Carusel": ProducedIdeaDetails,
    "Stories": ProducedIdeaDetails,
}


def detail_output_type(format: FormatChoice) -> type[StrictContract]:
    """Which strict contract the model is asked to fill for this format."""

    return DETAIL_CONTRACTS[format]


#: The models the interface may ask for, as a contract rather than a string.
#: Anything else is a 422 at the edge instead of an unpriced model reaching
#: `pricing.py`, which charges what it does not recognise at the most expensive
#: rate in its table. `None` means the deployment default.
ModelChoice = Literal["gpt-5-nano", "gpt-5-mini"]


class GenerationBatchRequest(StrictContract):
    format: FormatChoice
    pillar: PillarChoice
    source: SourceChoice
    focus: str | None = Field(default=None, max_length=2_000)
    material_ids: list[UUID] = Field(default_factory=list, max_length=50)
    # On the batch request rather than on the start request, unlike `language`:
    # this one has to survive the request that created the batch. Details are
    # generated when she opens an idea, and they must come from the model she
    # picked then, not from whatever the deployment defaults to now.
    model: ModelChoice | None = None

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
    # Deliberately on the start request and not on GenerationBatchRequest:
    # that model is serialised straight into the MCP tool arguments, so a
    # field there would need a tool signature and a column to land in.
    language: Language = DEFAULT_LANGUAGE


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


#: Name the tool, and say the call comes first. This replaced a note that told
#: the model where the skill was MOUNTED - `.agents/<name>/SKILL.md`, read it with
#: `sed` - which stopped being true the moment the sandbox went away and became
#: an instruction to use a shell that does not exist.
#:
#: The measurement that made this necessary, batch c82d55fd on 2026-08-24: the
#: DETAIL phase called its tool 11 times out of 11, and the TITLE phase never
#: called `propune-postari` at all. It reached for `list_posts` and `search_books`
#: instead, got `[]` from both, and wrote ten titles without ever reading the
#: method. Saying "activează skill-ul" is not the same as naming a tool.
def use_skill_note(skill: str, *, preloaded: bool = False) -> str:
    """Tell the model where its method is - and only what is true.

    Two versions, because there are two shapes. When `content_studio.method` has
    already assembled the method into the system prompt there is no skill tool
    attached, and an instruction to call one is an instruction to spend a turn
    discovering it does not exist. The system prompt says the same thing from
    the other side; both have to move together, which is what
    `tests/unit/test_method.py` holds.
    """

    if preloaded:
        return """Metoda ta e în promptul de sistem, întreagă, împreună cu
referințele ei. Nu o ceri și nu o cauți — o aplici, pas cu pas.

Scrii direct răspunsul cerut. Un pas sărit e metodă neaplicată, nu timp
economisit."""

    return f"""Metoda ta este unealta `{skill}`. Cheam-o ÎNAINTE de orice
altceva, citește ce întoarce și urmeaz-o. Nu scrii nimic înainte s-o fi chemat.

Metoda ei nu se termină acolo: unde îți spune să ceri o referință, o ceri, tot
înainte de a scrie. Un pas sărit e metodă neaplicată, nu timp economisit."""


def title_prompt(
    request: GenerationBatchRequest,
    source_packet: dict[str, Any],
    language: Language = DEFAULT_LANGUAGE,
    *,
    preloaded: bool = False,
) -> str:
    """The bounded title-only branch of the existing proposal skill."""

    packet = json.dumps(source_packet, ensure_ascii=False)
    return f"""{use_skill_note("propune-postari", preloaded=preloaded)}

Formatul, pilonul și sursa sunt deja alese de ea — nu le pui la îndoială, nu ceri
confirmare și nu întrebi nimic. Scrii numai din materialul-sursă de mai jos și din
profil.

Format: {request.format}
Pilon: {request.pillar}
Sursă: {request.source}
Focus: {request.focus or "fără focus suplimentar"}
Material-sursă colectat o singură dată: {packet}

Răspunde numai prin contractul structurat cerut de aplicație.
{task_note(language)}"""


#: What the model has to know about a Reel that the schema alone cannot say.
#: The schema can withhold the script; only this can explain why, and what the
#: caption has to absorb because of it.
SILENT_REEL_BRIEF = """Reel-urile ei sunt MUTE: filmează fără să vorbească, cu text pe ecran.
Deci varianta NU are script și NU are bloc de producție — nu le scrie și nu le
inventa, contractul nici nu le acceptă.

Tot ce ar fi spus cu vocea intră în `caption`. Captionul e lung, 900–1400 de
semne: intră direct în ideea din hook, o desfășoară în 2–4 paragrafe scurte, așa
cum i-ar fi povestit unei prietene, și se închide cu întrebarea de engagement.
Nu e un rezumat de două fraze și nu repetă hook-ul cuvânt cu cuvânt.

`hook` rămâne scurt: e textul care apare pe ecran în primele două secunde."""

#: The produced formats keep the method they already had.
PRODUCED_BRIEF = """Varianta are `script` și `format_details` complete, potrivite formatului ales.
Captionul rămâne scurt, 2–4 fraze, cu întrebarea de engagement la final."""


def format_brief(format: FormatChoice) -> str:
    """The format-specific half of the detail prompt."""

    return SILENT_REEL_BRIEF if format == "Reel" else PRODUCED_BRIEF


def detail_prompt(
    request: GenerationBatchRequest,
    idea: IdeaTitle,
    source_packet: dict[str, Any],
    language: Language = DEFAULT_LANGUAGE,
    *,
    preloaded: bool = False,
) -> str:
    """The complete five-variant branch for one already-persisted idea."""

    idea_json = json.dumps(idea.model_dump(), ensure_ascii=False)
    packet = json.dumps(source_packet, ensure_ascii=False)
    return f"""{use_skill_note("dezvolta-postarea", preloaded=preloaded)}

Ideea ţi se dă mai jos, întreagă — nu o cauți în conversație și nu alegi alta.
Cele cinci variante pornesc din același unghi, dar hook-ul și construcția
fiecăreia sunt realmente diferite, nu aceeași propoziție reformulată.

Ideea existentă: {idea_json}
Format: {request.format}
Pilon: {request.pillar}
Sursă: {request.source}
Focus: {request.focus or "fără focus suplimentar"}
Material-sursă colectat o singură dată: {packet}

{format_brief(request.format)}

Dezvoltă exact ideea primită. Răspunde numai prin contractul structurat cerut de
aplicație; `idea_ordinal` și `title` rămân identice cu ideea existentă.
{task_note(language)}"""


def public_batch(batch: dict[str, Any]) -> dict[str, Any]:
    """Remove internal identity, session and source excerpts from an API response."""

    hidden = {"client_id", "owner_principal_id", "session_id", "source_packet"}
    return {key: value for key, value in batch.items() if key not in hidden}
