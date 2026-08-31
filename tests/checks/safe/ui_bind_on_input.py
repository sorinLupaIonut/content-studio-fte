"""A field that gates its own button must bind while you type, not when you leave.

Blazor's `@bind` listens to `onchange`, which for a text field means *blur*.
That is harmless where a button is always clickable: pressing it blurs the
field first, the value commits, and the handler sees it.

It stops being harmless the moment the button's ENABLED state depends on that
same change. Then the first press lands on a disabled button - the blur it
causes is what enables it - and the user's click is spent switching the button
on. Nothing runs. The second press works.

Measured on production 2026-08-31: every field in `Saved.razor` marked the form
dirty on blur, and both of its buttons were `disabled="@(_busy || !_dirty)"`.
Editing a saved post and pressing "Save changes" once did nothing but raise the
"Unsaved draft" banner. It never raised an error, and the page looked correct
the whole time - the same shape of defect as the chat composer fixed hours
earlier in `ChatDrawer.razor`, which is why one fix did not find the other.

Scope, deliberately narrow: only files that HAVE a button disabled on a negated
flag are inspected. Elsewhere `@bind` on blur is a real and correct choice.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
UI = ROOT / "ui" / "StudioViorela"

#: A button switched off by a flag being false - `disabled="@(_busy || !_dirty)"`.
GATED_BUTTON = re.compile(r"<button[^>]*\bdisabled=\"@\([^\"]*![_A-Za-z]", re.S)

#: A free-text field. `<select>` is excluded on purpose: a select HAS no
#: "while typing", so `onchange` is the only event it could bind to.
TEXT_FIELD = re.compile(r"<(?:input|textarea)\b[^>]*@bind=\"[^\"]+\"[^>]*>", re.S)

BINDS_LIVE = '@bind:event="oninput"'

#: The marker routed through `onchange` - blur again, by the other door. The
#: Title field had exactly this shape: it bound live, so its VALUE was current,
#: but `@onchange="MarkDirty"` still waited for blur to raise the flag the
#: button reads. Binding live is half the fix; the flag has to move with it.
MARKER_ON_CHANGE = re.compile(r"@onchange=\"[^\"]*Mark[^\"]*\"")

#: A password or search box that must NOT re-render on every keystroke would go
#: here, with the reason. Empty is the honest state today.
EXEMPT: dict[str, str] = {}


def main() -> int:
    files = sorted(UI.rglob("*.razor"))
    print(f"{len(files)} interface files; inspecting those with a gated button")

    faults: list[str] = []
    inspected = 0

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        if not GATED_BUTTON.search(text):
            continue
        inspected += 1
        for match in TEXT_FIELD.finditer(text):
            tag = match.group(0)
            stale = MARKER_ON_CHANGE.search(tag)
            if BINDS_LIVE in tag and not stale:
                continue
            line = text.count("\n", 0, match.start()) + 1
            field = re.search(r"@bind=\"([^\"]+)\"", tag)
            why = "marks dirty on blur via @onchange" if stale else "binds on blur"
            faults.append(
                f"  {rel}:{line}  {field.group(1) if field else '?'} "
                f"{why}, but this page gates a button on a flag"
            )

    print(f"{inspected} of them gate a button on a flag\n")

    if faults:
        print("These fields only commit when the user leaves them, so the first")
        print("click on the gated button is spent enabling it:\n")
        print("\n".join(faults))
        return 1

    print("Every gating field binds while the user types.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
