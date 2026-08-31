"""Romanian in the interface has to be one half of a pair, never a lone string.

`language_split.py` is the same idea for Python and stops at `src/` and
`evals/`. Nothing asked the question of the C# and the `.razor` files, and on
2026-08-31 that showed: the confirmation panel that appears before a saved post
is replaced — a destructive write with no history — printed a hardcoded
„Titlu:" and the raw `Educație` value. The last screen before an unrecoverable
change was the one screen an English reader could not read.

WHAT MAKES THIS DIFFERENT FROM A DIACRITIC GREP. Half the Romanian in this tree
is CORRECT: `Copy.cs` and `Values.cs` hold both languages a line apart, and
`T.Pick("românește", "in English")` is the same pattern inline. A net that only
looks for ă and ș drowns in those. So the rule here is about POSITION, not about
characters: a Romanian literal is fine as the first argument of a `Pick(...)`,
fine as a domain VALUE the tools match on, and wrong anywhere else.

    uv run python tests/checks/safe/ui_language_split.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from content_studio import enable_utf8_output  # noqa: E402

UI = Path(__file__).resolve().parents[3] / "ui" / "StudioViorela"

#: Both languages live here on purpose, one line apart. See `Copy.cs`'s header.
OWNED_BY_LOCALIZATION = {
    Path("Localization/Copy.cs"),
    Path("Localization/Values.cs"),
    Path("RomanianText.cs"),
}

#: Built output and build scratch, not source.
SKIP_DIRS = {"dist", "bin", "obj", "wwwroot"}

DIACRITIC = re.compile(r"[ăâîșțĂÂÎȘȚ]")

#: Romanian function words that are not English words. A sentence can be
#: Romanian without carrying a single diacritic — „Conectat; 10 unelte
#: disponibile." is the example that taught this project the lesson.
ROMANIAN_WORDS = re.compile(
    r"\b(?:este|sunt|pentru|despre|fara|pana|catre|daca|cand|ceea|"
    r"dumneavoastra|vrei|poti|esti|tine|tale|tau|lui|ei|nu se|se va|"
    r"a fost|au fost|nimic|ceva|acum|deja|inca)\b",
    re.IGNORECASE,
)

#: The domain vocabulary. These are identifiers the API, the schemas and the
#: tools match on; they appear in comparisons and defaults and never translate.
VALUES = {
    "Memorie", "Cărți", "Internet", "Combinat",
    "Poziționare", "Educație", "Conexiune", "Conversie", "Magnetism",
    "Reel", "Carusel", "Stories",
    "PROVOCARE", "CIFRA", "SECRET", "INTREBARE", "CONTRAST",
    "Română", "English",
}

#: `Pick("ro", "en")` and `new("ro", "en")` are the bilingual shapes.
#:
#: MATCHED ACROSS LINES, NOT WITHIN ONE. Both are routinely written over three
#: or four lines when the strings are long, and a same-line test called three
#: correct pairs offenders on the first run of this script — a check that cries
#: wolf gets switched off, which is worse than not having it.
PICK = re.compile(r"\b(?:Pick|new Phrase|new)\s*\($")

STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def is_romanian(text: str) -> bool:
    return bool(DIACRITIC.search(text) or ROMANIAN_WORDS.search(text))


def inside_a_pair(text: str, index: int) -> bool:
    """Is the literal at `index` an argument of a still-open `Pick(`/`new(`?

    Walk left, counting brackets. The first unclosed `(` is the call this
    literal belongs to; if the name before it is one of the bilingual
    constructors, the Romanian is where it should be.

    Every enclosing call is examined, not only the innermost one: the two
    branches of a ternary sit in their own parentheses inside the `Pick(`, and
    stopping at the first open bracket flagged them.
    """
    depth = 0
    i = index - 1
    while i >= 0:
        char = text[i]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                if PICK.search(text[max(0, i - 40) : i + 1]):
                    return True
                # Not this call. Keep going outward to the one containing it.
            else:
                depth -= 1
        elif char == ";":
            return False  # a statement boundary: no call is still open
        i -= 1
    return False


def offenders(path: Path) -> list[tuple[int, str]]:
    text = path.read_text("utf-8")
    found: list[tuple[int, str]] = []
    line_starts = [0]
    for i, char in enumerate(text):
        if char == "\n":
            line_starts.append(i + 1)

    for match in STRING.finditer(text):
        literal = match.group(1)
        if not literal.strip() or literal in VALUES or not is_romanian(literal):
            continue
        start = match.start()
        number = sum(1 for s in line_starts if s <= start)
        line = text[line_starts[number - 1] : start]
        if line.lstrip().startswith(("//", "///", "*", "@*")):
            continue
        if inside_a_pair(text, start):
            continue
        found.append((number, literal[:90]))
    return found


def main() -> int:
    enable_utf8_output()
    files = [
        p
        for p in sorted(UI.rglob("*"))
        if p.suffix in {".cs", ".razor"}
        and not SKIP_DIRS & set(p.relative_to(UI).parts)
        and p.relative_to(UI) not in OWNED_BY_LOCALIZATION
    ]
    print(f"{len(files)} interface files that must not hold a lone Romanian string\n")

    bad = 0
    for path in files:
        for number, literal in offenders(path):
            bad += 1
            print(f"{path.relative_to(UI)}:{number}\n    {literal!r}")

    if bad:
        print(
            f"\n{bad} Romanian literal(s) outside a bilingual pair. Move each one "
            "into Copy.cs, or make it a Pick(ro, en)."
        )
        return 1
    print("Every Romanian string is one half of a pair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
