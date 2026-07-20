# Handwriting → Variable Font

A small toolkit that turns scans of your handwriting into an installable
TrueType font — including a **variable font** with a Light→Bold weight axis
(`wght` 300–700), **ligatures** (fi, fl, ffi, th, ck...),
**pseudo-random alternates** so repeated letters don't look identical, and
full **Czech, Slovak and Polish** diacritics.

## How it works

```
print template  →  write letters  →  scan  →  segment  →  trace  →  compile
     PDF            black pen       300dpi    per-letter   potrace   fontTools
                                              crops        beziers   .ttf / VF
```

1. **`make_template.py`** generates a PDF of labeled boxes covering these
   character sets (choose with `--sets`, default all):
   - **core** — lowercase, uppercase, digits & punctuation. With
     `alternates` enabled, each lowercase letter appears three times **in a
     row** (a, a v2, a v3) so you can see and steer the variety as you
     write — just don't trace-copy the neighbour,
   - **symbols-extra** — currency (€ £ ¥ ¢), math (× ÷ − ± ≈ ≠ ≤ ≥ < >),
     brackets, arrows (← → ↑ ↓ ↔), typographic quotes including Czech
     „uvozovky“ and « guillemets », dashes, © ® ™, ° § • …,
   - **czech** — á č ď é ě í ň ó ř š ť ú ů ý ž + uppercase, written as whole
     letters so the diacritics are genuinely *your* diacritics,
   - **slovak-polish** — ä ĺ ľ ŕ ô / ą ć ę ł ń ś ź ż + uppercase,
   - **alternates** — the lowercase alphabet again, twice; write naturally,
     do **not** copy the first version. These become OpenType `calt`
     alternates that rotate as you type, so "book" never shows two
     identical o's,
   - **small-caps** — capital letterforms written small (about x-height).
     Compiled into the `smcp` and `c2sc` OpenType features: "Adina" in
     small-caps mode renders as a full-size A followed by small capitals,
   - **extras** — dingbats mapped to their real Unicode codepoints, so they
     work anywhere once typed: manicules (☞ ☜ ☝ ☟), smileys (☺ ☹), card
     suits filled and outline (♥ ♡ ♠ ♤ ♦ ♢ ♣ ♧), ★ ☆ ✓ ✗ ♪ ☀ ☾ ✿, and
     printers' flourishes (❦ ❧ ⁂ ⁓ ✎ ✂). All optional,
   - **ligatures** — ff fi fl ffi ffl th ch sh st ct ck qu tt ll ss ee oo
     ft; write the pair **joined** the way you naturally connect letters.
     Filled boxes become automatic `liga` substitutions; skip any pair you
     don't connect and no rule is generated for it.

   Each PDF comes in three forms: **normal** (large boxes, 11 pages),
   **compact** (4 pages, ~4.5 mm x-height boxes — write at your natural
   size and scan at 600 DPI), and **book** (4 pages, landscape split into a
   left and right half like an open notebook, same natural-size boxes —
   the most comfortable to fill in; keep the sheet flat when scanning,
   never fold it). Guides are printed in light gray so they can be
   thresholded away later; only the corner registration marks are black.
2. **`segment.py`** finds the four registration marks on each scan, fits an
   affine transform (absorbing rotation, scale and offset — no careful
   scanning required), and crops every box back into perfect alignment.
3. **`build_font.py`** thresholds each crop (the gray guides disappear),
   traces the ink into smooth Beziers with potrace, aligns each glyph to the
   baseline printed in its box, and compiles a static `.ttf` with fontTools.
   It then generates OpenType feature code from whatever cells had ink:
   `liga` rules for the ligature pairs, and a chained-context `calt` rotation
   (default → v2 → v3 → default...) for the alternates. Both features are on
   by default in browsers and most apps.
4. **`make_variable.py`** derives point-compatible Light and Bold masters by
   displacing every outline point along its ink-outward normal (counters are
   detected by nesting and move the opposite way), then interpolates them into
   a variable font with `fontTools.varLib`.

## The workflow for you

1. Print `templates/handwriting-template-a4-compact.pdf` if you write small
   (recommended — natural-size handwriting is your real handwriting), or the
   plain `-a4` / `-letter` version for large boxes. Always print at **100% /
   "actual size"** — do not "fit to page" or rescale in the print dialog;
   the box sizes are already designed for each writing size and the layout
   JSON must match the printed geometry.
2. Write one character per box with a **black pen** (gel, fineliner ≥0.5 mm,
   or a fountain pen with an M/B nib all work great; avoid pencil and light
   blue ink; let fountain-pen ink dry before scanning). Use **one pen for
   everything** — the Light/Bold weights are derived mathematically from
   your single pass, so you never write thin or thick versions:
   - letters sit on the **solid** line,
   - the body of lowercase letters (the x-height) reaches the **dashed** line,
   - ascenders (`b d f h k l`) go up toward the box top; descenders
     (`g j p q y`) hang below the solid line,
   - write at your natural speed — hesitation shows more than wobble.
3. Scan **grayscale, pages flat** — at **600 DPI** for the compact template,
   300 DPI is enough for the normal one. Phone photos can work if the page
   fills the frame and is evenly lit, but a flatbed scan is better.
4. The last template page is a **writing sample**: copy the gray model
   lines (sentence case, then ALL CAPS) onto the guides at your natural
   pace, plus free lines for anything you like. The text is engineered to
   cover every letter, the Czech/Slovak/Polish diacritics, digits and the
   common ligature pairs. This page is never cut into glyphs — it's the
   reference for tuning spacing, size and rhythm so the font matches how
   your writing actually flows.
5. Run (use `layout-a4-compact.json` if you printed the compact template):

```bash
pip install -r requirements.txt          # plus: apt install potrace
python3 segment.py --layout templates/layout-a4.json \
    scans/*.png --outdir work/cells
python3 build_font.py --cells work/cells \
    --out work/MyHand-Regular.ttf --family "My Hand"
python3 make_variable.py --regular work/MyHand-Regular.ttf \
    --out work/MyHandVF.ttf
python3 proof.py --font work/MyHandVF.ttf --out work/proof.png
```

Install `MyHandVF.ttf` and every app with a weight slider (or CSS
`font-weight`) gets your handwriting from Light to Bold.

## Tuning

| Symptom | Fix |
|---|---|
| Gray guide lines appear in glyphs | lower `--threshold` (build_font.py) |
| Faint pen strokes break apart | raise `--threshold`, or rescan darker |
| Dust specks become tiny glyph blobs | raise `--turdsize` |
| Letters too close / too far apart | adjust `--lsb` / `--rsb` / `--space-width` |
| Bold looks clogged | lower `--bold-offset` |
| Light falls apart | lower `--light-offset` |

## Testing without a scanner

`simulate_scan.py` fakes filled-in scans using a system font (with rotation
and rescaling to imitate a real scanner), so the whole pipeline can be
exercised end-to-end:

```bash
python3 simulate_scan.py --layout templates/layout-a4.json --outdir work/sim
python3 segment.py --layout templates/layout-a4.json work/sim/*.png --outdir work/cells
```

## Design notes & limits

- **Why boxes instead of drawing boxes around free writing?** Known geometry
  buys automatic alignment, baseline placement, and consistent scaling for
  free. Freeform capture needs manual annotation of every letter and baseline
  — far more work for the same result.
- **Why a synthetic weight axis?** True multi-master handwriting (writing
  everything again with a marker) produces outlines that are not
  point-compatible after autotracing, and matching them up is manual,
  expert-level work. Normal-offsetting one master guarantees compatibility.
  A real second axis (e.g. `slnt`, or a "neatness" axis) is possible later
  with the same trick or with manual outline matching.
- This builds an unhinted TTF; at small screen sizes rendering leans on the
  rasterizer's smoothing (fine on all modern systems).
- Alternates and ligatures are optional: any box left blank simply produces
  no glyph and no substitution rule. You can start with pages 1–3 only and
  add pages 4–6 in a later pass — rerun segment + build and the features
  appear.
- No kerning yet. Obvious next steps: autokerning of tight pairs
  (`To`, `Va`...), capture of accented characters, and a real second axis
  (e.g. slant) via a second writing pass.
