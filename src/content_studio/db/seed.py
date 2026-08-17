"""Fill `clients` and `posts` from content/. Decision 3.

    uv run python -m content_studio.db.seed

Idempotent: run it as often as you like. The client is upserted on slug, the posts
on (client_id, source_file).

WHAT IS HARD HERE. The 26 existing posts do not have one format, they have three —
they were written in different months, with different tools:

  A. the oldest (07-09): metadata in a blockquote, on one line, separated by "·"
                            > **Pilon:** X · **Format:** Y · **Data:** Z
  B. the middle ones (07-15 → 07-29): one per line
                            **Pilon:** X
  C. the newest (08-13): the full structure, with **Hook ales:** and
     ## HOOK / ## SCRIPT / ## CAPTION / ## HASHTAGURI sections

The section headings vary too: "## SCRIPT", "## Scriptul (6–9 secunde, fără
vorbit)", "## Script (text pe ecran + idee de filmare)". That is why matching is
done on the first word, without diacritics and without case.

What is certain across all 26: the date (from the file name) and the title (`# ` on
the first line). Those two plus the pillar are the columns §3 wants for "have I
written about this already?". The rest is best-effort, and `body_md` keeps the
whole file so nothing the parser missed is lost.

The Romanian literals below — "pilon", "sursa", "hashtaguri" — are what the source
files actually say. They are matched, not named, so they stay as they are.

At the end it prints a coverage table: how many posts got each field. A seed that
quietly fills half the columns with NULL is worse than one that tells you what it
could not find.
"""

from __future__ import annotations

import asyncio
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.audit import CORPUS_SEEDED, event_name
from content_studio.config import (
    CLIENT_SLUG,
    CONTENT_DIR,
    MissingConfig,
    database_url,
    describe_database,
)

enable_utf8_output()

PROFILE = CONTENT_DIR / "profile.md"
POSTS_DIR = CONTENT_DIR / "posts"

CLIENT_NAME = "Viorela"

DATE_FROM_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
META_FIELD = re.compile(r"\*\*\s*([A-Za-zĂÂÎȘȚăâîșț ]{3,20}?)\s*:\s*\*\*\s*([^\n·]+)")
TITLE_LINE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# The ⭐ marked option out of a list of five hooks:
#   3. **SECRET** ⭐ *(recomandat)* — „textul hook-ului"
#   - **ÎNTREBARE** ⭐ *(recomandat)* — „textul hook-ului"
# The Romanian quotes are written as escapes („ opens, ” closes) so the pattern
# does not depend on this file's own encoding.
RECOMMENDED_HOOK = re.compile(
    "\\*\\*\\s*([A-ZĂÂÎȘȚ]{4,12})\\s*\\*\\*[^\n]*?⭐[^\n]*?[„\"]([^”\"\n]+)"
)
HOOK_TYPES = {"PROVOCARE", "CIFRA", "SECRET", "INTREBARE", "CONTRAST"}

# Pillars: deliberately NOT normalized against a fixed list. The five pillars
# (Magnetism, Educație, Conexiune, Despre Business, Conversie) belong to the
# Brand Legends METHOD, not to the client — they live in `skills/*/references/`.
# §3: the method is a capability, not data; it travels with the skill, not with
# the client. If this app reaches another coach tomorrow, the pillars leave
# unchanged. So all that happens here is cleaning the value; the vocabulary stays
# with the skill.


def without_diacritics(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def clean(s: str | None) -> str | None:
    """Strip emoji, markup and stray whitespace. None if nothing is left."""
    if s is None:
        return None
    s = re.sub(r"[☀-➿\U0001F300-\U0001FAFF️]", "", s)
    # The multi-character strip is deliberate: it is a SET of characters to peel
    # off either end, not a prefix.
    s = s.replace("**", "").replace("*", "").strip(" \t·—-– ")  # noqa: B005
    s = re.sub(r"\s+", " ", s)          # a removed emoji leaves double spaces
    # Quotes are NOT touched: in the title („Mesajul de 3 secunde") and in the
    # source („Granițe în relații" — Cloud & Townsend) they are part of the
    # content, and stripping them leaves unmatched pairs. The hook solved its own
    # quote inside RECOMMENDED_HOOK, which stops before the closing one.
    return s.strip() or None


def clean_pillar(s: str) -> str | None:
    """Only the pillar name: „Magnetism ✨ (perspectivă contrarian)" -> „Magnetism"."""
    return clean(s.split("(")[0])


@dataclass
class Post:
    source_file: str
    posted_on: date
    title: str
    body_md: str
    pillar: str | None = None
    format: str | None = None
    hook: str | None = None
    hook_type: str | None = None
    script: str | None = None
    caption: str | None = None
    hashtags: str | None = None
    cta: str | None = None
    source: str | None = None
    found: set[str] = field(default_factory=set)


def sections(text: str) -> dict[str, str]:
    """Cut the text on `## ` and index it by the first word, normalized."""
    out: dict[str, str] = {}
    matches = list(SECTION.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip().strip("-").strip()
        key = without_diacritics(m.group(1)).lower().split()[0].strip(":(—-")
        out.setdefault(key, body)
    return out


def parse(path: Path) -> Post | None:
    text = path.read_text(encoding="utf-8")

    m = DATE_FROM_NAME.match(path.name)
    if not m:
        return None
    day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    t = TITLE_LINE.search(text)
    title = clean(t.group(1)) if t else path.stem[11:].replace("-", " ")

    post = Post(
        source_file=path.name,
        posted_on=day,
        title=title or path.stem,
        body_md=text,
    )
    post.found.update({"posted_on", "title"})

    # The header: everything before the first `## ` section. It covers form A
    # (blockquote with "·") as well as B/C (one per line), because the field
    # pattern does not care what surrounds it.
    first = SECTION.search(text)
    header = text[: first.start()] if first else text[:1500]
    for key, value in META_FIELD.findall(header):
        k = without_diacritics(key).lower().strip()
        v = clean(value)
        if not v:
            continue
        if k == "pilon":
            post.pillar = clean_pillar(value)
            post.found.add("pillar")
        elif k == "format":
            post.format, _ = v, post.found.add("format")
        elif k == "sursa":
            post.source, _ = v, post.found.add("source")
        elif k in ("hook ales", "hook"):
            kind = without_diacritics(v).upper().strip()
            if kind in HOOK_TYPES:
                post.hook_type, _ = v.upper(), post.found.add("hook_type")

    found_sections = sections(text)
    for key, attribute in (("script", "script"), ("scriptul", "script"),
                           ("caption", "caption"), ("hashtaguri", "hashtags"),
                           ("cta", "cta")):
        if key in found_sections and not getattr(post, attribute):
            setattr(post, attribute, found_sections[key])
            post.found.add(attribute)

    # The hook. Form C keeps it under `## HOOK`, as a bold blockquote.
    # Forms A/B list five options, one marked ⭐ *(recomandat)* — that is the
    # chosen one, and the type comes from the same line.
    if "hook" in found_sections:
        line = next(
            (
                row
                for row in found_sections["hook"].splitlines()
                if row.strip().startswith(">")
            ),
            None,
        )
        if line:
            post.hook, _ = clean(line.lstrip("> ")), post.found.add("hook")
    if not post.hook:
        h = RECOMMENDED_HOOK.search(text)
        if h:
            post.hook = h.group(2).strip()
            post.found.add("hook")
            if not post.hook_type and without_diacritics(h.group(1)).upper() in HOOK_TYPES:
                post.hook_type, _ = h.group(1), post.found.add("hook_type")

    return post


CLIENT_SQL = """
INSERT INTO public.clients (slug, name, profile_md)
VALUES ($1, $2, $3)
ON CONFLICT (slug) DO UPDATE
   SET profile_md = EXCLUDED.profile_md,
       name = EXCLUDED.name,
       updated_at = NOW()
RETURNING id
"""

POST_SQL = """
INSERT INTO public.posts (client_id, posted_on, title, pillar, format, hook,
                   hook_type, script, caption, hashtags, cta, source, body_md,
                   source_file, status)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'imported')
ON CONFLICT (client_id, source_file) DO UPDATE
   SET posted_on=EXCLUDED.posted_on, title=EXCLUDED.title, pillar=EXCLUDED.pillar,
       format=EXCLUDED.format, hook=EXCLUDED.hook, hook_type=EXCLUDED.hook_type,
       script=EXCLUDED.script, caption=EXCLUDED.caption,
       hashtags=EXCLUDED.hashtags, cta=EXCLUDED.cta, source=EXCLUDED.source,
       body_md=EXCLUDED.body_md
"""

# `run_id` is NULL: seeding happens outside any conversation, which is exactly
# what the course's nullable foreign key is for. The counts that used to go into
# `payload` now ride in the event text — the trail has no payload column since D4.
AUDIT_SQL = "INSERT INTO public.audit_log (run_id, event) VALUES (NULL, $1)"

FIELDS = ["pillar", "format", "hook", "hook_type", "script",
          "caption", "hashtags", "cta", "source"]


async def main() -> int:
    if not PROFILE.exists():
        print(f"Missing {PROFILE}", file=sys.stderr)
        return 1

    files = sorted(f for f in POSTS_DIR.glob("*.md") if f.name != "README.md")
    if not files:
        print(f"No posts in {POSTS_DIR}", file=sys.stderr)
        return 1

    posts = [p for p in (parse(f) for f in files) if p is not None]
    skipped = len(files) - len(posts)

    try:
        url, connect_args = database_url()
    except MissingConfig as e:
        print(f"{e}", file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}\n")
    engine = create_async_engine(url, connect_args=connect_args)

    try:
        async with engine.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection

            profile_md = PROFILE.read_text(encoding="utf-8")
            client_id = await raw.fetchval(
                CLIENT_SQL, CLIENT_SLUG, CLIENT_NAME, profile_md
            )
            print(f"clients  ✓ {CLIENT_NAME} ({len(profile_md):,} profile characters)")

            for p in posts:
                await raw.execute(
                    POST_SQL, client_id, p.posted_on, p.title, p.pillar, p.format,
                    p.hook, p.hook_type, p.script, p.caption, p.hashtags,
                    p.cta, p.source, p.body_md, p.source_file,
                )
            print(f"posts    ✓ {len(posts)} rows")

            await raw.execute(
                AUDIT_SQL, event_name(CORPUS_SEEDED, f"{len(posts)} posts + profile")
            )
    except Exception as e:  # noqa: BLE001
        print(f"\nThe seed failed:\n  {type(e).__name__}: {e}", file=sys.stderr)
        print("Did you run `uv run python -m content_studio.db.apply` first?", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"\nCoverage across the {len(posts)} posts — what the parser understood:")
    for name in FIELDS:
        n = sum(1 for p in posts if name in p.found)
        bar = "█" * round(n / len(posts) * 24)
        print(f"  {name:<11} {n:>2}/{len(posts)}  {bar}")

    without_pillar = [p.source_file for p in posts if "pillar" not in p.found]
    if without_pillar:
        print(f"\nWithout a pillar ({len(without_pillar)}) — fill them in by hand if you "
              "want the pillar search from §3:")
        for f in without_pillar:
            print(f"  · {f}")

    if skipped:
        print(f"\n{skipped} files skipped (the name does not start with YYYY-MM-DD)")

    print("\nEvery post's full body is in `posts.body_md` — whatever the parser "
          "missed was not lost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
