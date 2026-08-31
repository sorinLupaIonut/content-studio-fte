"""Structured, non-Markdown profile view for the browser application."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from content_studio.config import SKILLS_DIR
from content_studio.harness.models import ProfileBlock, ProfileSection

HEADING = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
LIST_ITEM = re.compile(r"^[*-][ \t]+(.+)$")
ORDERED_ITEM = re.compile(r"^\d+[.)][ \t]+(.+)$")
INLINE_MARKUP = re.compile(r"(\*\*|__|(?<!\w)[*_](?!\s)|(?<!\s)[*_](?!\w)|`)")
PILLARS_FILE = SKILLS_DIR / "propune-postari" / "references" / "piloni.md"


def slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in ascii_value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def plain_inline(value: str) -> str:
    value = INLINE_MARKUP.sub("", value.strip())
    return re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)


def parse_blocks(body: str) -> list[ProfileBlock]:
    blocks: list[ProfileBlock] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(
                ProfileBlock(kind="paragraph", text=plain_inline(" ".join(paragraph)))
            )
            paragraph.clear()

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            flush()
            continue
        if line.startswith(">"):
            flush()
            text = plain_inline(line[1:].strip())
            if text:
                blocks.append(ProfileBlock(kind="quote", text=text))
            continue
        match = LIST_ITEM.match(line)
        if match:
            flush()
            blocks.append(ProfileBlock(kind="bullet", text=plain_inline(match.group(1))))
            continue
        match = ORDERED_ITEM.match(line)
        if match:
            flush()
            blocks.append(ProfileBlock(kind="ordered", text=plain_inline(match.group(1))))
            continue
        paragraph.append(line)
    flush()
    return [block for block in blocks if block.text]


def serialize_blocks(blocks: list[ProfileBlock]) -> str:
    lines: list[str] = []
    ordered = 0
    for block in blocks:
        text = " ".join(block.text.split()).strip()
        if not text:
            continue
        if block.kind == "bullet":
            line = f"- {text}"
            ordered = 0
        elif block.kind == "ordered":
            ordered += 1
            line = f"{ordered}. {text}"
        elif block.kind == "quote":
            line = f"> {text}"
            ordered = 0
        else:
            line = text
            ordered = 0
        if lines and block.kind in {"paragraph", "quote"}:
            lines.append("")
        lines.append(line)
    return "\n".join(lines).strip()


def category_for(parent: str, title: str) -> str:
    """Which tab a profile section belongs under, by what its heading says.

    ENGLISH KEYWORDS SIT BESIDE THE ROMANIAN ONES, since 2026-08-31, because a
    profile can be written in English now. Without them every keyword rule fell
    through and only the numbered-parent rules survived: measured on the first
    English profile, six groups became three - 8 identity, 4 offer, 4 voice, 2
    results, 14 ideal_client, 1 restrictions collapsed to 17 identity, 1 offer,
    15 ideal_client. Nothing raised; the page just drew the wrong tabs.

    No English word here matches a Romanian heading, so the Romanian behaviour
    is exactly what it was. `usp` is the one token both languages share.

    ONE SECTION LANDS DIFFERENTLY, and it is the Romanian side that is wrong:
    `clienta ideală` does not match her actual heading, `Clienta ta ideală` -
    there is a `ta` in the middle - so in Romanian that section falls through to
    `identity`, while `ideal client` matches `Your ideal client` cleanly. Left
    as it is deliberately: fixing the Romanian pattern would move a section
    between two tabs on the client's own page, which is a change she did not
    ask for and would notice.
    """
    combined = f"{parent} {title}".lower()
    if parent.startswith("6."):
        return "ctas"
    if "lucruri pe care nu" in combined or "never say" in combined:
        return "restrictions"
    if any(
        word in combined
        for word in (
            "vocea", "expresii", "tonul", "povestea",
            "voice", "expressions", "tone", "story",
        )
    ):
        return "voice"
    if any(
        word in combined
        for word in (
            "ofert", "servicii", "soluția", "usp",
            "offer", "services", "solution",
        )
    ):
        return "offer"
    if (
        parent.startswith(("2.", "3."))
        or "clienta ideală" in combined
        or "ideal client" in combined
    ):
        return "ideal_client"
    if parent.startswith("4.") or "rezultat" in combined or "result" in combined:
        return "results"
    return "identity"


def parse_profile(profile_md: str) -> list[ProfileSection]:
    headings = list(HEADING.finditer(profile_md))
    sections: list[ProfileSection] = []
    parent = "Profil"
    parent_slug = "profil"

    for index, match in enumerate(headings):
        level, title = match.group(1), plain_inline(match.group(2))
        if level == "##":
            parent = title
            parent_slug = slug(title)
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(profile_md)
        body = profile_md[match.end() : end]
        sections.append(
            ProfileSection(
                key=f"{parent_slug}--{slug(title)}",
                title=title,
                group=category_for(parent, title),
                update_name=title,
                blocks=parse_blocks(body),
            )
        )
    return sections


def parse_pillars(path: Path = PILLARS_FILE) -> list[ProfileSection]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", text, re.MULTILINE))
    result = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        title = plain_inline(match.group(1))
        result.append(
            ProfileSection(
                key=f"pillar--{slug(title)}",
                title=title,
                group="pillars",
                update_name="",
                blocks=parse_blocks(text[match.end() : end]),
                read_only=True,
            )
        )
    return result


def find_editable_section(profile_md: str, key: str) -> ProfileSection | None:
    return next((section for section in parse_profile(profile_md) if section.key == key), None)
