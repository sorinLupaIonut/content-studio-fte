"""Strict D1b contracts for title-first generation and browser event streams."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from content_studio import avatar
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

#: Ten ways one theme can be approached, one per proposal.
#:
#: TEN, NOT NINE AND NOT TWELVE. The count is the mechanism: ten archetypes for
#: ten slots makes the set a permutation, so "different from each other" stops
#: being a request and becomes arithmetic. Add an eleventh and two proposals can
#: share; remove one and the contract cannot be satisfied.
#:
#: None of them collides with a `HookType`. PROVOCARE, CIFRA, SECRET, INTREBARE
#: and CONTRAST are how a hook opens in Faza 2; these are what the post is
#: about. Two vocabularies that overlapped by a word would be two vocabularies
#: the model conflates.
#:
#: Romanian and uppercase, like the hook types, because these are domain values
#: - the same rule that keeps `Pilon` and `Sursă` untranslated.
ANGLE_TYPES: tuple[str, ...] = (
    "DURERE",
    "MIT",
    "METODA",
    "POVESTE",
    "GRESEALA",
    "INAINTE_DUPA",
    "CULISE",
    "DOVADA",
    "OBIECTIE",
    "RITUAL",
)

AngleType = Literal[
    "DURERE",
    "MIT",
    "METODA",
    "POVESTE",
    "GRESEALA",
    "INAINTE_DUPA",
    "CULISE",
    "DOVADA",
    "OBIECTIE",
    "RITUAL",
]

#: The glossary rides on the field, not in the prompt. A description attached to
#: the property is read where the value is written; the same sentence 3,800
#: tokens higher up is the arrangement that produced two delegation ideas in one
#: batch of ten.
ANGLE_TYPE_BRIEF = (
    "Tiparul acestei propuneri. Fiecare dintre cele zece îl folosește pe al său, "
    "o singură dată — sunt exact zece tipare pentru zece propuneri. "
    "DURERE: numești durerea și o recunoști, fără soluție încă. "
    "MIT: răstorni o credință în care ea crede de mult. "
    "METODA: pașii concreți, în ordine. "
    "POVESTE: experiența ta, la persoana întâi. "
    "GRESEALA: ce face ea fără să-și dea seama că o costă. "
    "INAINTE_DUPA: cele două stări, una lângă alta. "
    "CULISE: cum se lucrează de fapt, ce nu se vede. "
    "DOVADA: rezultatul unui om real. "
    "OBIECTIE: răspunsul la «da, dar…». "
    "RITUAL: un gest mic, repetabil, de făcut azi."
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
    """One proposal as it is stored and as Faza 2 reads it back.

    No `angle_type`: the archetype is a forcing function for the moment the ten
    are written, not a property of the idea afterwards. See `ProposedIdeas`.
    """

    ordinal: int = Field(ge=1, le=10)
    title: str = Field(min_length=3, max_length=160)
    angle: str = Field(min_length=3, max_length=600)


class ProposedIdea(StrictContract):
    """One proposal as the model writes it, archetype first.

    Field order is writing order, and `angle_type` comes before the title on
    purpose: the model commits to an angle it has not used yet, then writes into
    it. Reversed, it writes whatever came to mind and labels it afterwards -
    which is exactly the behaviour this contract exists to stop.
    """

    ordinal: int = Field(ge=1, le=10)
    angle_type: AngleType = Field(description=ANGLE_TYPE_BRIEF)
    title: str = Field(min_length=3, max_length=160)
    # The glossary above is written as "DURERE: numesti durerea", and the first
    # run with it came back with every angle shaped "Durerea: ... Promisiunea:
    # ...". The model copied the glossary's punctuation into the field she
    # actually reads. This description is the answer to that, and it is here
    # rather than in the prompt for the same reason the glossary is.
    angle: str = Field(
        min_length=3,
        max_length=600,
        description=(
            "Unghiul, în una-două fraze curgătoare: ce durere atinge și ce "
            "promite. PROZĂ, NU ETICHETE: niciun «Durerea:», niciun "
            "«promisiunea:», niciun două-puncte care anunță ce urmează, și "
            "nu numi tiparul ales. Se citește ca o frază spusă cuiva."
        ),
    )


class ProposedIdeas(StrictContract):
    """The ten, each on a different archetype.

    WHY THE SCHEMA AND NOT THE SKILL. `propune-postari/SKILL.md` already says it
    - "realmente diferite intre ele... nu aceeasi idee reformulata de zece ori"
    - and calls it "singura parte grea a fazei, si singura pe care nicio schema
    n-o poate verifica in locul tau". Measured on 2026-08-24, with that sentence
    3,800 tokens above the schema: batch a16a3f94 proposed delegation twice (2
    and 8) and boundaries twice (1 and 5). Pairwise embedding similarity 0.511
    average, 0.620 for the closest pair.

    Ten archetypes for ten slots makes the set a permutation: the model cannot
    write delegation twice, because the second attempt has no unused archetype
    left to file it under. The same lever that stopped hashtags containing
    spaces - the constraint next to the field, not the rule far above it.
    """

    ideas: list[ProposedIdea] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def exact_order(self) -> ProposedIdeas:
        if [idea.ordinal for idea in self.ideas] != list(range(1, 11)):
            raise ValueError("ideas must be ordered exactly from 1 to 10")
        return self

    @model_validator(mode="after")
    def one_idea_per_archetype(self) -> ProposedIdeas:
        used = [idea.angle_type for idea in self.ideas]
        if len(set(used)) != len(used):
            repeated = sorted({value for value in used if used.count(value) > 1})
            raise ValueError(
                "each of the ten ideas uses a different angle_type; repeated: "
                + ", ".join(repeated)
            )
        return self

    def to_titles(self) -> IdeaTitles:
        """Drop the archetype and hand over what the rest of the system stores."""

        return IdeaTitles(
            ideas=[
                IdeaTitle(ordinal=idea.ordinal, title=idea.title, angle=idea.angle)
                for idea in self.ideas
            ]
        )


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


#: What a hashtag has to look like, stated where the model writes it.
#:
#: The provider enforces `pattern` WHILE the model writes, not afterwards -
#: probed on 2026-08-24 by asking gpt-5-mini outright for hashtags containing
#: spaces and getting back none. So this is prevention; `checked_hashtags` below
#: is the net under it, for any path where the schema is not enforced.
HASHTAG_PATTERN = r"^#\S+$"

#: Injected into the JSON schema rather than onto the Python type ON PURPOSE.
#: A `StringConstraints(pattern=...)` would be a field constraint, and field
#: constraints run BEFORE an "after" validator - so `perfecționism` would be
#: rejected before `checked_hashtags` ever got the chance to repair it into
#: `#perfecționism`. Prevention in the schema, repair in the validator, and
#: neither standing in the other's way.
HASHTAG_FIELD = {
    "items": {"type": "string", "pattern": HASHTAG_PATTERN},
    "description": (
        "Trei până la cinci hashtaguri. Fiecare începe cu # și e un singur "
        "cuvânt lipit, fără spații: #grijadetine, nu «#grijade tine»."
    ),
}


def checked_hashtags(values: list[str]) -> list[str]:
    """The one hashtag rule: repair what is unambiguous, refuse what is not.

    THIS USED TO RAISE, AND IT WAS THE MOST EXPENSIVE LINE IN THE PROJECT.
    Recovered on 2026-08-24 by pulling every failed run back from the provider
    by `response_id`: of 44 turns that died on a contract, 39 died here. Not one
    was malformed JSON. The 367 rejected values were 279 that simply had no `#`
    (`perfecționism` for `#perfecționism`), 67 with a space in the middle
    (`#grijade tine`), and 21 with other whitespace - every single one of them
    mechanically repairable. The bill for refusing instead of repairing was
    $0.1889 of $0.7920 spent, 24%, thrown away and re-earned by a second call
    that was given no idea what it had done wrong.

    Repair is not indulgence here: Instagram truncates a hashtag at the first
    space anyway, so `#grijade tine` was never going to be one tag. Joining it
    is what she would have done by hand.

    What still refuses: a value that repairs to nothing, and a set that comes
    out of repair with fewer than three distinct tags. The count is re-checked
    here because Pydantic's `min_length` on the list runs BEFORE this validator,
    so anything dropped below the floor would otherwise pass unnoticed.
    """

    repaired: list[str] = []
    for value in values:
        # One token, one `#`, whatever whitespace the model put in the middle.
        token = "#" + "".join(value.split()).lstrip("#")
        if token == "#":
            continue
        if token not in repaired:
            repaired.append(token)
    if not 3 <= len(repaired) <= 5:
        raise ValueError(
            "three to five distinct hashtags are needed; after repair there "
            f"were {len(repaired)} (from {values!r})"
        )
    return repaired


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
    hashtags: list[str] = Field(
        min_length=3, max_length=5, json_schema_extra=HASHTAG_FIELD
    )
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
    hashtags: list[str] = Field(
        min_length=3, max_length=5, json_schema_extra=HASHTAG_FIELD
    )
    cta: str = Field(min_length=2, max_length=1_000)
    source: str = Field(min_length=2, max_length=2_000)
    format_details: FormatDetails

    @field_validator("hashtags")
    @classmethod
    def hashtag_shape(cls, values: list[str]) -> list[str]:
        return checked_hashtags(values)


#: A silent reel's caption carries the whole idea, so it cannot be two lines.
#: Raised from 200 to 900 on 2026-08-25, and the reason is rule 5: what a prompt
#: cannot enforce, a schema can. `SILENT_REEL_BRIEF` has asked for 900–1400 all
#: along and been ignored — measured 2026-08-24, mini averaged 668 and 0 of 50
#: captions landed in range; the eight frozen cases of 2026-08-25 averaged 333.
#: A floor of 200 called that compliant, so nothing ever objected.
#:
#: This costs no retry. OpenAI enforces `minLength` WHILE the model writes, not
#: after, so the constraint shapes the answer instead of rejecting it. The
#: ceiling stays at 8_000 deliberately: `maxLength` is not on the list of
#: keywords measured to be enforced during decoding, and a rejected run costs
#: the whole batch, while a caption that runs long is caught by `CaptionLength`
#: at no risk at all.
SILENT_REEL_CAPTION_FLOOR = 900


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
    hashtags: list[str] = Field(
        min_length=3, max_length=5, json_schema_extra=HASHTAG_FIELD
    )
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

{avatar_brief(source_packet)}

Cele zece propuneri stau în același focus, dar fiecare pornește din alt loc:
contractul îți cere un `angle_type` diferit la fiecare, iar tiparul îl alegi
înainte de titlu, nu după. Două propuneri care spun același lucru cu alte
cuvinte sunt o propunere, nu două.

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


def avatar_brief(source_packet: dict[str, Any]) -> str:
    """Her pains, lifted out of the packet and given their own block.

    The profile is already inside `packet` above, JSON-encoded among the topic,
    the recent posts and everything else. Repeating it is deliberate and it is
    the same trade the caption floor made: what an instruction cannot achieve by
    being present, a shape can achieve by being unmissable. Roughly 9 KB, once
    per run, against ten proposals that were all interchangeable without it.
    """
    profile = source_packet.get("profile")
    return avatar.brief(profile) if isinstance(profile, str) else ""


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

{avatar_brief(source_packet)}

{format_brief(request.format)}

Dezvoltă exact ideea primită. Răspunde numai prin contractul structurat cerut de
aplicație; `idea_ordinal` și `title` rămân identice cu ideea existentă.
{task_note(language)}"""


def public_batch(batch: dict[str, Any]) -> dict[str, Any]:
    """Remove internal identity, session and source excerpts from an API response."""

    hidden = {"client_id", "owner_principal_id", "session_id", "source_packet"}
    return {key: value for key, value in batch.items() if key not in hidden}
