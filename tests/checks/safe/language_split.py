"""Does the language split hold? Free, offline, and the reason it exists.

    uv run python tests/checks/safe/language_split.py
    uv run python tests/checks/safe/language_split.py --list-allowed

AGENTS.md draws a line: some surfaces are Romanian because the client reads them,
everything else is English so that somebody who does not read Romanian can work
on this repository. The line is easy to state and impossible to hold by hand.

THE GREP THAT FINDS DIACRITICS IS NOT THE CHECK. Moving the harness to English on
2026-08-31 took five passes, and three of them were needed only because
`Conectat; 10 unelte disponibile.`, `Chatul nu a putut porni` and `cerute,
nechemate` carry no diacritic at all. A net woven out of ă î ș ț catches most
Romanian and then reports clean over the rest, which is the worst possible
answer: it looks like proof.

So this looks at two things at once — the diacritics AND a list of Romanian
function words that are not also English words. Two distinct hits from that list
inside one string literal is Romanian; one is a coincidence. Only string
literals are read, because a comment is allowed to quote what it is talking
about, and every quotation here is Romanian by nature.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from content_studio import enable_utf8_output  # noqa: E402

enable_utf8_output()

ROOT = Path(__file__).resolve().parents[3]

#: Every file under these must be English. `tests/` is absent on purpose: its
#: fixtures are her posts, her profile and the dictated sentences, so Romanian
#: there is the subject, not a leak.
ENGLISH_ONLY = (
    "src/content_studio",
    "evals",
)

#: Romanian by contract, and each for its own reason.
ALLOWED_FILES = {
    # The identity and voice the model writes in. AGENTS.md, language policy.
    "src/content_studio/worker.py",
    # A button press is dictation: these strings are what she is shown to have
    # said, so they are her language, not the harness's.
    "src/content_studio/harness/conversations.py",
    # This module's whole subject is the Romanian output rule; it quotes it.
    "src/content_studio/language.py",
    # Parsing patterns for her own markdown, and comments quoting it.
    "src/content_studio/db/seed.py",
    # The fixtures of `evals/output/`: her own published hooks and captions,
    # the words her profile forbids, and four planted fragments of deliberately
    # bad Romanian. Every Romanian string in this file is the THING BEING
    # GRADED, not prose about it - an English-only rule here would mean a
    # metric for Romanian writing with no Romanian to measure.
    "evals/output/cases.py",
}

#: Individual strings that stay Romanian inside an English file. Each is a VALUE
#: rather than prose about one: a domain term on the API contract, a heading in
#: her profile, a phrase she types that the model has to recognise, or a literal
#: written into the database.
ALLOWED_SUBSTRINGS = (
    # Domain contract — see ui/StudioViorela/Localization/Values.cs.
    "Poziționare",
    "Educație",
    "Conexiune",
    "Cărți",
    "Carusel",
    "CIFRĂ",
    "ÎNTREBARE",
    "Întrebare",
    "Cifră",
    # Written into `posts.source`, and named in the skill.
    "din memorie 🧠",
    # Headings in content/profile.md — keys into her document.
    "Ce își dorește cel mai mult acum?",
    "Ce probleme are în acest moment?",
    "Ce dureri simte?",
    "Fricile ei cele mai puternice",
    "Credințele ei limitative (în cuvintele ei)",
    # The same, for the four sections `voice.py` lifts. Keys, like the five
    # above, and quoted by the judge's rubric so it can name what it grades.
    "Vocea ta",
    "Expresii pe care le folosești des",
    "Lucruri pe care nu le spui niciodată",
    "Tonul tău",
    # Shortened deliberately: the rubric wraps this line, and a fragment
    # that spans a newline matches nothing.
    "Exemple de hook-uri",
    # Things she types, quoted so the model recognises them.
    "dezvoltă a treia",
    "aleg varianta cu CIFRA",
    "am mai scris despre asta?",
    "ce am dat luna asta",
    "Salvează modificările",
    "Durerea:",
    "limite",
    "#grijadetine",
    "da, dar",
    # The metadata `import_books` writes, and the SQL defaults that mirror it.
    "context de lucru",
    "ediție neînregistrată",
    "copie personală",
    # Data about Romanian itself: the diacritics, and the stopwords
    # `path/convergence.py` strips out of a focus SHE typed before asking
    # whether the topic reached the tool. Words used as data, not as prose.
    "ăâîșşțţĂÂÎȘŞȚŢ",
    "fara de a si cu la in pe sa",
    # More data about Romanian itself, in `evals/output/`: the two legacy
    # cedilla letters named in a finding, and one specimen of the agreement
    # error the rubric asks the judge to catch. Both are exhibits.
    "(ş/ţ)",
    "mai puțin oboseală",
    # The name of the pre-rename Romanian table, which `db/apply.py` looks for
    # so it can tell the operator which migration has not been run.
    "postari",
    "Sursă:",
    # The Romanian half of the one prompt line that chooses the answer language.
    "Răspunde natural, în română",
    # Values written into the database, or read back out of her documents.
    "(fără titlu)",
    "## Producție",
    "clienta ideală",
    "soluția",
    "lucruri pe care nu",
)

DIACRITICS = set("ăâîșțĂÂÎȘȚşţŞŢ")

#: Romanian function words that are not also English words. Two of them in one
#: string is Romanian; one is a coincidence — `de` appears in `de-duplicate`,
#: `nu` in a German quotation, `la` in a filename.
MARKERS = frozenset(
    """
    nu si sa se ce la cu de din pe un une este sunt esti era fost fara doar deja
    acum apoi cand unde pentru poate daca prea mult putin niciun nicio nimic
    mereu catre dupa inainte intre asta astea aceasta aceste ale lui ei lor
    cerute chemat chemate deschis deschise picat picate rulare rulari unelte
    unealta postare postari lotul lotului cauta cautare cautari ales alese
    aleasa spune scrie scris citit gata toate tot lipsesc lipseste conectat
    folderul urmele salvat salvata generarea varianta variante ideea ideile
    contul contului cererea cererile trebuie foloseste porneste raspunde
    cazuri cazul oricare niciunul fiecare acelasi aceeasi
    """.split()
)


def romanian(text: str) -> str | None:
    """Why this string looks Romanian, or None."""
    if any(ch in DIACRITICS for ch in text):
        return "diacritics"
    words = [w.strip(".,;:!?()[]{}\"'`«»„”0123456789").lower() for w in text.split()]
    # OCCURRENCES, not distinct words. `Niciun model, niciun container, niciun
    # cost.` carries one marker three times and slipped through a distinct-word
    # count on 2026-08-31 - found by reading an eval's output, which is exactly
    # the manual step this file exists to replace.
    hits = [w for w in words if w in MARKERS]
    if len(hits) >= 2:
        return f"words: {' '.join(sorted(set(hits)))}"
    # A SHORT string gets no benefit of the doubt, and 25 of them collected it
    # on 2026-08-31: `pe disc`, `niciun pas`, `Set de date:`, `n-a deschis`.
    # One marker inside a long English sentence is a coincidence; one marker
    # inside three words IS the string. The threshold that let these through
    # was written the same afternoon, against the opposite failure.
    if hits and len(words) <= 6:
        return f"short, and one of its {len(words)} words is {hits[0]!r}"
    return None


def allowed(text: str) -> bool:
    return any(fragment in text for fragment in ALLOWED_SUBSTRINGS)


#: In this one file a docstring is not documentation: `@server.tool()` publishes
#: it as the tool's description, so the model reads it. Everywhere else a
#: docstring explains code to a person and is free to QUOTE the Romanian it is
#: explaining - `avatar.py` cites the line from `SKILL.md` that made it
#: necessary, and flagging that would be flagging the evidence.
DOCSTRINGS_ARE_MODEL_INPUT = "src/content_studio/mcp_server/server.py"


def docstring_lines(tree: ast.AST) -> set[int]:
    """Where the docstrings are, so they can be told apart from other strings."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            found.add(body[0].value.lineno)
    return found


def strings_of(path: Path, relative: str) -> list[tuple[int, str]]:
    """Every string literal that the model or the client could end up reading."""
    try:
        tree = ast.parse(path.read_text("utf-8"))
    except SyntaxError:
        return []
    skip = set() if relative == DOCSTRINGS_ARE_MODEL_INPUT else docstring_lines(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.lineno not in skip
    ]


def files() -> list[Path]:
    found: list[Path] = []
    for where in ENGLISH_ONLY:
        for path in sorted((ROOT / where).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path.relative_to(ROOT).as_posix() in ALLOWED_FILES:
                continue
            found.append(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list-allowed", action="store_true", help="print the exemptions and exit"
    )
    args = parser.parse_args()

    if args.list_allowed:
        print("Files that stay Romanian:")
        for name in sorted(ALLOWED_FILES):
            print(f"  {name}")
        print(f"\nStrings that stay Romanian anywhere: {len(ALLOWED_SUBSTRINGS)}")
        for fragment in ALLOWED_SUBSTRINGS:
            print(f"  {fragment}")
        return 0

    leaks: list[tuple[str, int, str, str]] = []
    scanned = 0
    for path in files():
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        for line, text in strings_of(path, relative):
            if not text.strip() or allowed(text):
                continue
            why = romanian(text)
            if why:
                leaks.append((relative, line, why, " ".join(text.split())[:88]))

    print(f"{scanned} files that must be English, under: {', '.join(ENGLISH_ONLY)}\n")
    if not leaks:
        print("No Romanian outside the exemptions.")
        return 0

    for relative, line, why, text in leaks:
        print(f"  {relative}:{line}  ({why})")
        print(f"      {text}")
    print(f"\n{len(leaks)} strings. Either translate them, or, if one is a value")
    print("rather than prose, add it to ALLOWED_SUBSTRINGS with the reason.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
