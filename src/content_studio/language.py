"""The output language, as a separate axis from the method.

The method is Romanian and stays Romanian: `BASE_INSTRUCTIONS`, every `SKILL.md`
and every `references/` file. Those describe *how* the work is done — the voice,
the pillars, the hook types, the shape of each format — and translating them
would fork the source of truth in two, which is exactly what the language policy
in AGENTS.md forbids.

What varies is the language the answer comes out in. That is one appended block,
not a second skill tree. The model reads the Romanian method and writes English,
which is something models do reliably and something a parallel translation would
only make harder to keep in step.

The override is written in English on purpose. It is model-facing only — the
client never reads it — and asking for English output in English primes the
model far better than asking for it in Romanian.

Added for the American entrepreneur trying the product. The evals still assert
Romanian answers and have not been extended to English; that is a known, accepted
gap, recorded in plans/DEPLOYMENT.md.
"""

from __future__ import annotations

from typing import Literal, get_args

#: The languages the interface and the agent can work in.
Language = Literal["ro", "en"]

#: What everything falls back to. Romanian is the client's language, and every
#: caller that predates the language switch keeps this behaviour untouched.
DEFAULT_LANGUAGE: Language = "ro"

LANGUAGES: tuple[Language, ...] = get_args(Language)

# BASE_INSTRUCTIONS says the answer is Romanian with diacritics, in its second
# paragraph. An override has to contradict that in as many words, or the model
# splits the difference and answers half in each. It is appended last, after the
# profile, because the closer contradiction wins.
ENGLISH_OVERRIDE = """\
--- OUTPUT LANGUAGE: ENGLISH ---

This session runs in English. This section overrides the Romanian-language rule
above; every other rule stays exactly as written.

1. Write everything you produce in English: your replies, your questions, the
   hooks, the scripts, the captions, the hashtags, the calls to action. The
   instruction to answer "în română, cu diacritice" does not apply here.
2. The profile, the pillars, the hook types and the source material are Romanian
   and stay Romanian on disk. Read them, understand them, and write the English
   equivalent. Never paste Romanian text into an English answer, and never leave
   a term untranslated because it sounded specific.
3. Translate the meaning, not the words. "People pleasing" and "burnout" are
   already English. Others are not: `pilon` is a content pillar, `postare` is a
   post, `sursă` is a source, `hook` stays a hook. Where the Romanian is an idiom
   from her voice, write the English that carries the same warmth, not a literal
   rendering that carries none.
4. The voice does not change with the language. Warm, gentle, empathetic,
   vulnerable but firm, with the same authentic Christian perspective. Still no
   aggressive empowerment, still no marketing jargon, still no generic AI
   phrasing.
5. The skill's rule about numbers holds with full force in English too: no
   invented testimonials, no invented numbers, no masked quantifiers such as
   "many women" or "most people". A number is allowed only when it counts the
   points you are listing in the post yourself.
6. Structured output — the fields of a saved post, a batch of proposals — keeps
   its English field names, as always. The prose values are now English.
7. Controlled values are NOT prose and are NOT translated. `hook_type` stays
   PROVOCARE, CIFRA, SECRET, INTREBARE, CONTRAST. A pillar stays Poziționare,
   Educație, Conexiune, Conversie or Magnetism. A format stays Reel, Carusel or
   Stories. The source CHOICE stays Memorie, Cărți, Internet or Combinat. These
   are identifiers the database and the tools match on, not words on a screen:
   an English one is rejected, and the interface shows the reader an English
   label for them anyway.
8. THE `source` FIELD OF A POST IS NOT THAT CHOICE, and it IS prose. It is the
   provenance line the reader sees under the post — a book's title and page, a
   link, or the note that you wrote from the profile alone. Nothing matches on
   it. The method spells its memory form in Romanian, and in this session you
   write the English equivalent: "from memory 🧠 (profile + avatar), no external
   source". A book keeps its own title exactly as printed.
"""

#: Only non-default languages carry an override; Romanian is what the base
#: instructions already say, so it appends nothing.
OVERRIDES: dict[str, str] = {"en": ENGLISH_OVERRIDE}

# The system prompt is not enough on its own, and this was learned the hard
# way: the first English chat came back in Romanian even with the override in
# place. Every task prompt in this codebase is *written* in Romanian, and it
# sits closer to the answer than the system prompt does, so it wins. The
# language therefore has to be restated where the task is stated.
ENGLISH_TASK_NOTE = (
    "ANSWER IN ENGLISH. The Romanian in this prompt is the method and the "
    "source material, not the language of your answer. Controlled values "
    "(hook_type, pilon, format, and the sursă CHOICE) still keep their "
    "Romanian spelling — but the post's `source` field is prose, not a choice: "
    "write it in English."
)

TASK_NOTES: dict[str, str] = {"en": ENGLISH_TASK_NOTE}


def task_note(language: Language | str | None) -> str:
    """One line appended to a task prompt, empty for Romanian.

    Separate from `instruction_suffix` because it lands in a different
    place: that one goes into the system prompt, this one into the message
    that carries the work.
    """
    note = TASK_NOTES.get(normalise(language))
    return f"\n\n{note}\n" if note else ""


def normalise(value: str | None) -> Language:
    """The language a request asked for, or Romanian when it asked for nothing.

    Unknown tags fall back rather than raising: a stale browser tab sending a
    language this build no longer has should still get an answer.
    """
    if value is None:
        return DEFAULT_LANGUAGE
    tag = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return tag if tag in LANGUAGES else DEFAULT_LANGUAGE  # type: ignore[return-value]


def instruction_suffix(language: Language | str | None) -> str:
    """The block appended to the system prompt, empty for Romanian."""
    override = OVERRIDES.get(normalise(language if isinstance(language, str) else None))
    return f"\n\n{override}" if override else ""
