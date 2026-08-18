# Studio Viorela — the dashboard shell. Design decisions.

**Status: proposed, not implemented.** The mockup is a static HTML page. The
Blazor application still ships the horizontal `PrimaryNav` under a topbar.

Language follows the repo rule in [AGENTS.md](../../AGENTS.md): this is a
developer document, so it is English. Every string the client reads is Romanian
with diacritics, and the mockup shows them in their final wording.

## The file

[`shell-mockup.html`](shell-mockup.html) — open it in any browser. Nothing is
wired to the API; it is a picture you can click.

- The four tabs on the left switch the four pages.
- The **Laptop 1280 / Telefon 390** switch at the top is scaffolding, not
  product. It renders the frame at a fixed width and scales it down to fit,
  so both layouts are visible even in a narrow preview panel. Delete that bar
  and the `.viewbar` / `.stage` / `.frame` rules when porting.
- Phone rules hang off `.frame.phone`, not a media query, for the same reason.
  In the real application they go back to `@media (max-width: 1000px)`.

## What Sorin asked for

A dashboard: a menu on the left with Generator, Salvate, Profil, Materiale, and
the active tab clearly visible. The reference he sent was a dark admin panel
with a rail, grouped items, and a filled pill on the active row.

## The decisions, and why

**1. The rail has two groups, not one flat list.** *Lucrezi*: Generator,
Salvate. *Ce te reprezintă*: Profil, Materiale. The reference splits its list
too (`Others`), but there the split is filler. Here it carries meaning: the
first two are things she does, the last two are what feeds them. A grouping that
does not mean anything is worse than no grouping, because it teaches the eye to
ignore the labels.

**2. The active tab carries three signals: filled background, a plum bar on the
left edge, a coloured icon.** One would satisfy a design review. Three survive a
washed-out laptop screen, a bright room, and colour blindness — and this is the
one piece of navigation the client uses on every single visit.

**3. Dark, but warm.** The neutrals lean purple, not the blue-grey of the
reference. Headings stay on Source Serif and the accents stay plum and gold,
carried over from the current light theme. Without that it stops being her
studio and becomes a generic admin console.

**4. No statistics cards.** An earlier draft had four counters across the top of
Generator. They were dropped on Sorin's call: two of the four needed new
database queries, and none of them changed what she does next. The space went to
the ten generated ideas instead — the thing the page is actually about.

**5. The ten ideas are the body of the Generator page.** Two columns on a
laptop, one on a phone. Each card shows the five hook types with the chosen one
filled, a progress bar while the detail job runs, and a checkbox that feeds the
save summary. A card still generating says so rather than showing an empty
frame.

**6. The approval card stays gold and inline, never a modal.** Rule 6 is the
centre of this product. A modal trains people to dismiss it reflexively; a card
in the flow of the page has to be read. It sits above the ideas so it cannot be
scrolled past.

**7. On a phone the rail becomes a bottom bar** with icon over label, and the
active marker flips to a bar under the item. Thumb reach, not aesthetics: the
four destinations are the only global navigation in the product.

## What porting costs

Rewrite `ui/StudioViorela/Layout/MainLayout.razor` and
`ui/StudioViorela/Components/PrimaryNav.razor`, and the shell half of
`ui/StudioViorela/wwwroot/css/app.css` — the tokens, `.app-shell`, `.topbar`,
`.primary-nav`, and the mobile block.

The four page components keep their markup and all of their logic. The Generator
idea grid and the Saved list/editor split already exist; they need class names
and colours, not new behaviour.

`NavLink` already emits `active` on the matching route, so the active-tab styling
is CSS only — no state to track.

## Open, if the light theme is wanted back

The whole palette is defined in `:root`. A light variant means one more token
block, not a second stylesheet. Nobody has asked for it yet; the current
application is light, so someone should decide rather than let the two drift.
