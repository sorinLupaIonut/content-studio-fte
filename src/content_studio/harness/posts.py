"""Strict saved-post contracts shared by FastAPI and `content-data`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from content_studio.harness.generation import (
    FormatChoice,
    FormatDetails,
    HookType,
    PillarChoice,
    StrictContract,
)

# The draft tables speak the ASCII hook codes the strict contracts are built on;
# `posts.hook_type` has always held the client's own spelling, diacritics and all,
# and her 27 imported posts are written that way. Neither side gives in: the map
# below is the border crossing, applied once on write and once on read.
HOOK_TYPE_LABELS: dict[str, str] = {
    "PROVOCARE": "PROVOCARE",
    "CIFRA": "CIFRĂ",
    "SECRET": "SECRET",
    "INTREBARE": "ÎNTREBARE",
    "CONTRAST": "CONTRAST",
}

HOOK_TYPE_CODES: dict[str, str] = {
    label: code for code, label in HOOK_TYPE_LABELS.items()
}


class SavedPostContent(StrictContract):
    title: str = Field(min_length=3, max_length=160)
    pillar: PillarChoice
    format: FormatChoice
    hook: str = Field(min_length=3, max_length=500)
    hook_type: HookType
    # Both optional, and deliberately not coupled the way the draft contract
    # couples them. A silent reel arrives with neither. Her posts imported into
    # the studio before the production block existed arrive with a script and no
    # `format_details`, and the editor has to be able to open those too.
    script: str | None = Field(default=None, min_length=3, max_length=12_000)
    caption: str = Field(min_length=3, max_length=8_000)
    hashtags: list[str] = Field(min_length=3, max_length=5)
    cta: str = Field(min_length=2, max_length=1_000)
    source: str = Field(min_length=2, max_length=2_000)
    format_details: FormatDetails | None = None

    @field_validator("hashtags")
    @classmethod
    def hashtag_shape(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(
            not value.startswith("#") or any(char.isspace() for char in value)
            for value in normalized
        ):
            raise ValueError("each hashtag must begin with # and contain no spaces")
        if len(set(normalized)) != len(normalized):
            raise ValueError("hashtags must be unique")
        return normalized


class SavePostsBatch(StrictContract):
    """What `content-data` validates before a batch reaches `public.posts`.

    Not a wire format: the browser sends variant ids, and the server assembles
    this from the draft rows it already holds. Retyping ten complete posts
    through the model would cost tokens for content the database already has,
    and would let a rewrite slip in between "she approved" and "it was written".
    """

    posts: list[SavedPostContent] = Field(min_length=1, max_length=10)


class SavePostsRequest(StrictContract):
    """The browser's request: which selected variants become saved posts."""

    variant_ids: list[UUID] = Field(min_length=1, max_length=10)

    @field_validator("variant_ids")
    @classmethod
    def unique_variants(cls, values: list[UUID]) -> list[UUID]:
        if len({str(value) for value in values}) != len(values):
            raise ValueError("a variant cannot be saved twice in one batch")
        return values


class PostUpdateRequest(SavedPostContent):
    """The browser's complete replacement draft for one saved post."""


def public_post(value: dict[str, Any]) -> dict[str, Any]:
    """Expose saved content without client/session implementation fields."""

    hidden = {"client_id", "conversation_id", "body_md", "source_file"}
    result = {key: item for key, item in value.items() if key not in hidden}
    if isinstance(result.get("id"), UUID):
        result["id"] = str(result["id"])
    hashtags = result.get("hashtags")
    if isinstance(hashtags, str):
        result["hashtags"] = [item for item in hashtags.split() if item]
    hook_type = result.get("hook_type")
    if isinstance(hook_type, str):
        result["hook_type"] = HOOK_TYPE_CODES.get(hook_type, hook_type)
    return result
