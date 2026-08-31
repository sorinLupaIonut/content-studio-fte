"""A field that gates its own button must bind while you type, not when you leave.

Blazor's `@bind` listens to `onchange`, which for a text field means *blur*.
That is harmless where a button is always clickable: pressing it blurs the
field first, the value commits, and the handler sees it. `Profile.razor` relies
on exactly that, correctly.

It stops being harmless the moment the button's ENABLED state depends on that
same change. Then the first press lands on a disabled button - the blur it
causes is what enables it - and the user's click is spent switching the button
on. Nothing runs. The second press works.

Both gated buttons in this interface shipped with that defect on 2026-08-31,
hours apart, and the second was found only because somebody typed into the
first:

    ChatDrawer.razor  disabled="@string.IsNullOrWhiteSpace(_draft)"
    Saved.razor       disabled="@(_busy || !_dirty)"

THE TWO SHAPES DO NOT LOOK ALIKE. The chat's Send reads the field's own value;
Saved's buttons read a flag the fields raise. That is why repairing the first
did not find the second - and why the first version of this check, which knew
only the flag shape, inspected one file out of twelve and reported clean over
the composer whose bug had started all of it. A net that catches one shape and
goes quiet on the other is worse than none: it looks like proof.

Scope stays narrow, but it is now drawn from the buttons rather than guessed: a
field is inspected only where a gated button actually reads it - by name, or
through a `Mark...` marker the field calls. `<select>` and checkboxes are
excluded throughout, since neither has a "while typing" and `onchange` fires on
the click itself.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
UI = ROOT / "ui" / "StudioViorela"

#: Every `disabled="@..."` on a button, with the expression captured.
BUTTON = re.compile(r"<button\b[^>]*?\bdisabled=\"(@[^\"]*)\"", re.S)

#: `disabled="@_busy"` and its spellings - "something is running", which no
#: field can change. A button gated only on that is always reachable when idle.
BUSY_ONLY = re.compile(r"^@\(?\s*_?[Bb]usy\s*\)?$")

#: Identifiers in a gate expression. `_draft.Title` collapses to `_draft`.
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

TEXT_FIELD = re.compile(r"<(?:input|textarea)\b[^>]*?@bind=\"([^\"]+)\"[^>]*?>", re.S)
NOT_TYPED = re.compile(r"type=\"(?:checkbox|radio)\"")

BINDS_LIVE = '@bind:event="oninput"'

#: A field that tells the page it changed.
ANY_MARKER = re.compile(r"@(?:bind:after|onchange|oninput)=\"[^\"]*Mark[^\"]*\"")

#: The marker routed through `onchange` - blur again, by the other door. The
#: Title field had exactly this shape: it bound live, so its VALUE was current,
#: but `@onchange="MarkDirty"` still waited for blur to raise the flag the
#: button reads. Binding live is half the fix; the flag has to move with it.
MARKER_ON_CHANGE = re.compile(r"@onchange=\"[^\"]*Mark[^\"]*\"")

#: A password or search box that must NOT re-render on every keystroke would go
#: here, with the reason. Empty is the honest state today.
EXEMPT: dict[str, str] = {}


def gate_names(text: str) -> set[str]:
    """What this page's buttons compute their enabled state from, `_busy` aside."""
    names: set[str] = set()
    for match in BUTTON.finditer(text):
        expression = match.group(1).strip()
        if BUSY_ONLY.match(expression):
            continue
        names.update(IDENT.findall(expression))
    return names - {"_busy", "Busy"}


def main() -> int:
    files = sorted(UI.rglob("*.razor"))
    print(f"{len(files)} interface files")

    faults: list[str] = []
    gated_pages = 0
    gating_fields = 0

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        gates = gate_names(text)
        if not gates:
            continue
        gated_pages += 1

        for match in TEXT_FIELD.finditer(text):
            tag = match.group(0)
            if NOT_TYPED.search(tag):
                continue
            bound = match.group(1)
            root = IDENT.match(bound)
            read_by_name = root is not None and root.group(0) in gates
            if not read_by_name and not ANY_MARKER.search(tag):
                continue
            gating_fields += 1

            stale = MARKER_ON_CHANGE.search(tag)
            if BINDS_LIVE in tag and not stale:
                continue
            line = text.count("\n", 0, match.start()) + 1
            why = "marks the page dirty on blur" if stale else "binds on blur"
            faults.append(
                f"  {rel}:{line}  {bound} {why}, and a button here "
                f"stays disabled until it changes"
            )

    print(f"{gated_pages} gate a button on something a field writes")
    print(f"{gating_fields} fields feed one of those buttons\n")

    if faults:
        print("These fields only commit when the user leaves them, so the first")
        print("click on the gated button is spent enabling it:\n")
        print("\n".join(faults))
        return 1

    print("Every gating field binds while the user types.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
