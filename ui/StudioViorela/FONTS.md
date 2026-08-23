# Fonts

Both faces ship as **subset variable WOFF2**, not the TTF they were downloaded
as. The TTF of Source Serif 4 alone was 1.18 MB, served uncompressed because a
TrueType file has no precompressed twin next to it the way the framework
assemblies do — over a third of a first visit, for glyphs no page here draws.

Rebuild them from the upstream variable TTF with:

```bash
uv run --with "fonttools[woff]" python -m fontTools.subset <face>.ttf \
    --unicodes="U+0020-007E,U+00A0-00FF,U+0100-017F,U+0180-024F,U+02BC,U+2010-2015,U+2018-201F,U+2022,U+2026,U+2030,U+2039-203A,U+20AC,U+2122" \
    --layout-features='*' --no-hinting --flavor=woff2 --output-file=<face>.woff2
```

The range is Latin plus Latin Extended-A and -B, which is where Romanian's `ș`
and `ț` live (U+0218–U+021B) — the reason a plain latin subset would not do.
The weight axes survive subsetting; `app.css` still asks for `font-weight: 200 800`.

Neither licence declares a Reserved Font Name, so a subset may keep the family
name. The OFL text stays beside the fonts because the licence requires it to
travel with them.
