"""Does every label in docs/diagrams/ fit where it was put? Free, no browser.

SVG has no text layout: a `<text>` is placed at a point and drawn, and if it is
too long it simply runs over whatever is next to it. Nothing raises, nothing
warns, and the file stays well-formed - so a diagram can look right in the editor
and be unreadable on GitHub. That happened four times on 2026-08-31, and each one
was found by looking at a screenshot rather than by any check.

So this estimates the rendered width of every label from its glyphs and font size
and reports four ways it can go wrong:

  CANVAS   the label runs off the edge of the drawing
  BOX      it runs out of the box it starts inside
  INTRUDE  it starts outside a box and runs INTO it - the one a "does it fit in
           its own box" test cannot see, and the one that bit twice
  COLLIDE  two labels overlap on the same line

The width model is an estimate, deliberately a little generous, so it flags
near-misses too. It is not a substitute for looking: render with headless Chrome
and read the picture before believing a clean report.

    uv run python tests/checks/safe/diagram_fit.py
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

NS = "{http://www.w3.org/2000/svg}"
PAD = 10  # how close to a box edge a label may come

def width(text, size, bold):
    narrow = sum(c in "iljtfIr.,:;'|! " for c in text)
    wide = sum(c in "MW@%mw" for c in text)
    base = (len(text) - narrow - wide) * 0.53 + narrow * 0.27 + wide * 0.85
    return base * size * (1.045 if bold else 1.0)

def load(path):
    root = ET.parse(path).getroot()
    vb = [float(v) for v in root.get("viewBox").split()]
    rects, texts = [], []
    for el in root.iter():
        tag = el.tag.replace(NS, "")
        if tag == "rect":
            try:
                r = dict(x=float(el.get("x", 0)), y=float(el.get("y", 0)),
                         w=float(el.get("width", 0)), h=float(el.get("height", 0)))
            except ValueError:
                continue
            # Skip backdrops: the full-canvas ground, and the translucent
            # boundary rectangles that a label is meant to float over.
            translucent = float(el.get("opacity", 1) or 1) < 1
            if r["w"] < vb[2] * 0.98 and not translucent:
                rects.append(r)
        elif tag == "text":
            s = "".join(el.itertext()).strip()
            if not s:
                continue
            try:
                x = float(el.get("x", 0))
                y = float(el.get("y", 0))
            except ValueError:
                continue
            size = float(el.get("font-size", 12))
            bold = (el.get("font-weight") or "") in ("600", "700", "bold")
            anchor = el.get("text-anchor", "start")
            w = width(s, size, bold)
            x0 = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
            texts.append(dict(s=s, x0=x0, x1=x0 + w, y=y, size=size))
    return vb[2], vb[3], rects, texts

def enclosing(rects, t):
    """The tightest rect whose interior the label starts inside."""
    best = None
    for r in rects:
        if r["x"] <= t["x0"] + 2 and r["y"] <= t["y"] <= r["y"] + r["h"]:
            if t["x0"] < r["x"] + r["w"]:
                if best is None or r["w"] < best["w"]:
                    best = r
    return best

bad = 0
for f in sorted((ROOT / "docs" / "diagrams").glob("*.svg")):
    W, H, rects, texts = load(f)
    problems = []
    for t in texts:
        if t["x1"] > W - 8:
            problems.append(f"  CANVAS   y={t['y']:>4.0f}  ends {t['x1']:.0f}/{W:.0f}  {t['s'][:60]!r}")
            continue
        box = enclosing(rects, t)
        if box and t["x1"] > box["x"] + box["w"] - PAD:
            problems.append(
                f"  BOX      y={t['y']:>4.0f}  ends {t['x1']:.0f}, box ends {box['x']+box['w']:.0f}"
                f"  {t['s'][:55]!r}")
    # A label that starts outside a box but runs into it: the case a "does it fit
    # in its own box" test cannot see, and the one that actually bit twice.
    for t in texts:
        for r in rects:
            if r["y"] <= t["y"] <= r["y"] + r["h"] and t["x0"] < r["x"] - 2:
                if t["x1"] > r["x"] + 2:
                    problems.append(
                        f"  INTRUDE  y={t['y']:>4.0f}  ends {t['x1']:.0f}, box starts {r['x']:.0f}"
                        f"  {t['s'][:50]!r}")
                    break
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if abs(a["y"] - b["y"]) < max(a["size"], b["size"]) * 1.0:
                if a["x0"] < b["x1"] - 2 and b["x0"] < a["x1"] - 2:
                    problems.append(
                        f"  COLLIDE  y={a['y']:>4.0f}  {a['s'][:34]!r} vs {b['s'][:34]!r}")
    bad += len(problems)
    print(f"\n=== {f.name} ({W:.0f}x{H:.0f}, {len(texts)} labels) ===")
    print("\n".join(problems) if problems else "  fits")
sys.exit(1 if bad else 0)
