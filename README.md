# Handwriting → Variable Font

A small toolkit that turns scans of your handwriting into an installable
TrueType font — including a **variable font** with a Light→Bold weight axis
(`wght` 300–700), **ligatures** (fi, fl, ffi, th, ck...),
**pseudo-random alternates** so repeated letters don't look identical, and
full **Czech, Slovak and Polish** diacritics.

## How it works

```
print sheets  →  write 3x, fill in →  scan  →  segment  →  trace  →  compile
    PDF          the keepers        600dpi    per-letter   potrace   fontTools
                                              crops        beziers   .ttf / VF
```

## Modules: print only what you want

Each character set is a **self-contained printable module** (its own PDF +
layout JSON in `templates/`). Start with `english`, add the rest whenever
you decide the font is worth more of your time:

| module | contents |
|---|---|
| **english** | the base: a–z, A–Z, 0–9 and every symbol on a normal (Mac/US) keyboard — plus the how-to guide and the writing-sample page |
| **czech** | á č ď é ě í ň ó ř š ť ú ů ý ž + uppercase |
| **slovak** | á ä č ď é í ĺ ľ ň ó ô ŕ š ť ú ý ž + uppercase (complete on its own — it deliberately overlaps Czech, so you can print *only* Slovak) |
| **polish** | ą ć ę ł ń ó ś ź ż + uppercase |
| **symbols** | typographic extras: „uvozovky“ « guillemets », – — …, € £ ¥ ¢, © ® ™, ° § • ¡ ¿ |
| **math** | × ÷ − ± ≈ ≠ ≤ ≥ |
| **fun** | arrows, smileys ☺, hands ☞, card suits ♥ ♠, stars ★, flourishes ❦ — all optional |
| **ligatures** | ff fi fl ffi ffl th ch sh st ct ck qu tt ll ss ee oo ft — write the pair **joined**; skipped pairs generate no rule |
| **small-caps** | capital letterforms written small; compiled into the `smcp`/`c2sc` OpenType features |

Any combination works: *english + slovak but not polish* is just "print
those two PDFs". If two modules share a character (Czech and Slovak both
have á), whichever you segment **last** wins.

Each module comes in two sizes: **normal** (large boxes, easy first-time
experience, 300 DPI scan is enough) and **book** (landscape split like an
open notebook, natural-size ~4.5 mm x-height boxes — the most comfortable
to fill; scan at 600 DPI, keep the sheet flat, never fold it). The "book"
sheet is a single landscape page split into two A5-sized halves, side by
side, because that's closer to how a person naturally writes than one
wide page. Characters flow like a real book: the **left half fills
completely, top to bottom, first**, then the **right half** does the
same — the fill order never alternates back and forth across the spine.
Print at **100% / "actual size"** — never "fit to page"; the layout JSON
must match the printed geometry.

## Write 3, fill in the keepers

Every character appears in **three boxes in a row**, each with a small
circle above it. Write the character three times (vary naturally — don't
trace-copy), then **fill in the circle** solid above every version you
actually like:

- the **first filled-in** version becomes the character in your font —
  filling in just **one** box is a completely fine outcome; it simply means
  "use this one, no alternates",
- **further filled-in** versions become rotating OpenType `calt` alternates,
  so "book" never shows two identical o's — filling in two or all three is
  just as valid as filling in one,
- versions **left unfilled** are thrown away — a botched box costs nothing,
- **no fill at all** on a character = all non-empty boxes are used
  (forgetting to fill in never loses a character).

The circles are printed in the same light gray as the box guides, outside
the region that gets cropped, so filling one in can't break the scanning —
just color it in solidly and keep it *inside* the circle (a light or partial
mark may not register as a fill).

Labels are designed to survive a mediocre printer: the character is printed
**big** above the first box of each triple, with a plain-language name for
anything ambiguous ("ě  e + háček", "% percent").

## The workflow

1. Print `templates/handwriting-english-a4-book.pdf` (or `-normal`, or the
   `letter` variant). Its first two pages are the **how-to guide** — vertical
   zones, horizontal placement, the fill-in rules. Keep them next to you;
   they are never scanned (also available standalone as
   `templates/filling-guide.pdf`).
2. Write with a **black pen** (gel, fineliner ≥0.5 mm, or a fountain pen —
   let it dry before scanning; avoid pencil and light blue ink). Use **one
   pen for everything** — Light/Bold are derived mathematically:
   - letters sit on the **solid** line,
   - the body of lowercase letters reaches the **dashed** line,
   - ascenders go up toward the box top; descenders hang below the solid line,
   - left–right position inside the box doesn't matter — spacing is measured
     from the ink itself,
   - write at your natural speed, then fill in the keepers.
3. Scan **grayscale, pages flat** — 600 DPI for `book`, 300 DPI is enough
   for `normal`. Phone photos can work if the page fills the frame and is
   evenly lit, but a flatbed is better.
4. The last english page is a **writing sample**: copy the gray model lines
   at your natural pace. It's never cut into glyphs — it's the reference for
   tuning spacing and rhythm.
5. Run, once per module you printed (with that module's layout JSON):

```bash
pip install -r requirements.txt          # plus: apt install potrace
python3 segment.py --layout templates/layout-english-a4-book.json \
    scans/english*.png --outdir work/cells
python3 segment.py --layout templates/layout-czech-a4-book.json \
    scans/czech*.png --outdir work/cells      # add-ons land in the same dir
python3 build_font.py --cells work/cells \
    --out work/MyHand-Regular.ttf --family "My Hand"
python3 make_variable.py --regular work/MyHand-Regular.ttf \
    --out work/MyHandVF.ttf
python3 proof.py --font work/MyHandVF.ttf --out work/proof.png
```

Install `MyHandVF.ttf` and every app with a weight slider (or CSS
`font-weight`) gets your handwriting from Light to Bold. Filled in another
module later? Segment its scans into the same `work/cells` and rerun
`build_font.py` — the font grows.

## What each script does

1. **`make_template.py`** renders the module PDFs and their layout JSONs
   (`--modules`, `--paper`, `--size`). Guides are light gray so they can be
   thresholded away; only the corner registration marks and page-ID dots are
   black.
2. **`make_guide.py`** renders the how-to sheets (standalone + first pages
   of the english module).
3. **`segment.py`** finds the four registration marks on each scan, fits an
   affine transform (absorbing rotation, scale and offset — no careful
   scanning required), crops every box back into perfect alignment, and
   reads which circles were filled in.
4. **`build_font.py`** thresholds each crop (the gray guides disappear),
   applies the fill-in selection, traces the ink into smooth Beziers with
   potrace, aligns each glyph to the baseline printed in its box, and
   compiles a static `.ttf` with feature code generated from whatever cells
   had ink: `liga` for ligature pairs, `smcp`/`c2sc` for small caps, a
   chained-context `calt` rotation over every character's extra filled-in
   versions, and shape-based `kern` pairs so letters sit as close as your
   hand spaces them (`--target-gap`).
5. **`make_variable.py`** derives point-compatible Light and Bold masters by
   displacing every outline point along its ink-outward normal (counters
   move the opposite way), then interpolates them into a variable font with
   `fontTools.varLib`.

## Tuning

| Symptom | Fix |
|---|---|
| Gray guide lines appear in glyphs | lower `--threshold` (build_font.py) |
| Faint pen strokes break apart | raise `--threshold`, or rescan darker |
| A fill wasn't detected | color the circle in more solidly/darker (fully inside it), rescan |
| Dust specks become tiny glyph blobs | raise `--turdsize` |
| Words too loose / too airy | lower `--target-gap` (auto-kern closeness) |
| Letters collide | raise `--target-gap`, or `--lsb` / `--rsb` |
| Odd gap after one letter | raise `--kern-min` to drop small kern pairs |
| Word spaces too wide/narrow | adjust `--space-width` |
| Bold looks clogged | lower `--bold-offset` |
| Light falls apart | lower `--light-offset` |

## Testing without a scanner

`simulate_scan.py` fakes filled-in scans using a system font (with rotation,
rescaling and filled-in circles), so the whole pipeline can be exercised
end-to-end:

```bash
python3 simulate_scan.py --layout templates/layout-english-a4-book.json --outdir work/sim
python3 segment.py --layout templates/layout-english-a4-book.json work/sim/*.png --outdir work/cells
```

## Design notes & limits

- **Why boxes instead of drawing boxes around free writing?** Known geometry
  buys automatic alignment, baseline placement, and consistent scaling for
  free. Freeform capture needs manual annotation of every letter and baseline.
- **Why fill-in circles instead of circling the letter?** A circle drawn
  around a letter would merge with the letter's ink at threshold time. The
  fill-in circle lives outside the cropped region, so the mark can never
  contaminate a glyph — and an unfilled mistake is simply ignored. Filling
  the circle solid (rather than ticking it) is also a more binary, robust
  scan signal: a light or thin accidental mark stays well below the
  detection threshold, while a deliberate fill clears it easily.
- **Why a synthetic weight axis?** True multi-master handwriting produces
  outlines that are not point-compatible after autotracing.
  Normal-offsetting one master guarantees compatibility.
- Sheets are versioned (`template v4` in the footer, `version` in the layout
  JSON). A v3 sheet won't line up with a v4 layout — reprint.
- **Book fill order is a deliberate invariant:** the left A5 half fills
  completely, top to bottom, before the right half starts — it never
  zig-zags across the spine. This matches how someone actually writes in
  an open notebook and must be preserved if the "book" layout code
  (`render_page` / `SIZE_PARAMS` in `make_template.py`) is ever touched.
- Later idea: a second sheet per character where you mark usable extras to
  grow the alternate pool beyond three. The selection metadata
  (`base`/`cand`/`marked`) already supports it. (`marked` is still the
  metadata key name even though the on-paper signal changed from a tick to
  a solid fill.)
- **Auto-kerning is shape-based:** every letter's per-band left/right ink
  profile is measured, and each ordered pair is slid until its closest
  approach equals `--target-gap` — so `To`/`Va`/`r.` tuck in and blocky
  pairs stay apart, the way a hand spaces them. Accented letters and a
  letter's alternates ride in the base letter's kern class, keeping the
  table small. It does **not** add letter *joins* — those come from the
  `ligatures` module (write the pairs connected).
- Getting it closer to your hand: the three levers are **alternates**
  (fill in 2–3 versions so repeats differ), **ligatures** (captured joins),
  and **kerning/spacing** (above). Remaining next step: a real second axis
  (e.g. slant) via a second writing pass.
