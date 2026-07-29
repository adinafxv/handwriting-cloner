#!/usr/bin/env python3
"""Build a static TrueType font from segmented handwriting cells.

For every cell image produced by segment.py: binarize (dropping the light-gray
guide lines), trace the ink with potrace into smooth Bezier outlines, scale so
the template's ascender-to-descender span maps to the em square, sit the glyph
on the baseline recorded in the cell metadata, and compile everything with
fontTools.

Usage:
    python3 build_font.py --cells work/cells --out work/MyHand-Regular.ttf \
        --family "My Hand"
"""

import argparse
import glob
import json
import os
import re
import subprocess
import tempfile
import unicodedata

import numpy as np
from PIL import Image
from scipy import ndimage
from fontTools import agl
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path

UPM = 1000
ASCENDER = 750    # box top -> +750 (baseline sits at 75% of box height)
DESCENDER = -250  # box bottom -> -250

SVG_TRANSFORM_RE = re.compile(
    r'transform="translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([-\d.]+),([-\d.]+)\)"')
SVG_PATH_RE = re.compile(r'<path d="([^"]+)"')


def trace_cell(binary, turdsize):
    """Trace a boolean ink mask with potrace; return (transform, [path d strings])."""
    with tempfile.TemporaryDirectory() as td:
        pbm = os.path.join(td, "cell.pbm")
        svg = os.path.join(td, "cell.svg")
        Image.fromarray(np.where(binary, 0, 255).astype(np.uint8)).convert("1").save(pbm)
        subprocess.run(
            ["potrace", "-s", "--turdsize", str(turdsize), "--alphamax", "1.0",
             "--opttolerance", "0.2", "-o", svg, pbm],
            check=True, capture_output=True)
        text = open(svg).read()
    m = SVG_TRANSFORM_RE.search(text)
    if not m:
        raise RuntimeError("unexpected potrace SVG output")
    tx, ty, sx, sy = (float(v) for v in m.groups())
    return (sx, 0, 0, sy, tx, ty), SVG_PATH_RE.findall(text)


KERN_BIN = 50  # font-unit height of each ink-profile band used for kerning


def ink_profiles(crop, scale, x_off, baseline_in_crop, dy=0.0):
    """Per-band left/right ink edges of a glyph, in font units. Bands are
    horizontal slices KERN_BIN units tall; each maps to (min_x, max_x) of the
    ink in that band. Used to slot neighbouring letters close without
    collision (auto-kerning)."""
    prof = {}
    ys, xs = np.where(crop)
    if len(xs) == 0:
        return prof
    yf = (baseline_in_crop - ys) * scale + dy   # font-unit y (up positive)
    xlf = xs * scale + x_off                     # font-unit x
    bands = np.floor(yf / KERN_BIN).astype(int)
    for b in np.unique(bands):
        m = bands == b
        prof[int(b)] = (float(xlf[m].min()), float(xlf[m].max()))
    return prof


# Lowercase letters that legitimately drop below the baseline; their ink
# bottom must NOT be snapped to the line.
DESCENDERS = set("gjpqy")


def is_descender(ch):
    """True for g j p q y AND their accented forms - 'ý' is a descender just
    like 'y'. Testing the raw character would snap 'ý' onto its own tail and
    shove the whole letter up."""
    return len(ch) == 1 and (ch in DESCENDERS or ascii_base(ch) in DESCENDERS)

# Symbols that belong on the math axis - vertically centred about half the
# x-height rather than sitting wherever the pen happened to land in the box.
# Written freehand, arrows and operators drift high or low and then look
# misaligned in running text; centring them is what a type designer does.
MATH_AXIS = 175  # font units above the baseline
CENTERED = set("←→↑↓↔×÷−±≈≠≤≥=+<>~-–—")

# Punctuation that stands on the baseline like a letter, and brackets that
# straddle it. Written freehand these drift wherever the pen started, so they
# float in running text; place them from their own ink instead.
BASELINE_PUNCT = set("&@$%#?!")
HANG_PUNCT = set("'\"`")   # hang from the ascender line, not float above it
BRACKETS = set("()[]{}")
BRACKET_DROP = 0.09   # share of the bracket's height that sits below baseline
AT_DROP = 0.09        # @ dips slightly below the line


SHORT_LETTERS = set("acemnorsuvwxz")     # tops define the x-height
ASCENDER_LETTERS = set("bdfhklt")
CAPITALS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = set("0123456789")


def ascii_base(ch):
    """'é' -> 'e'; returns None if it isn't a plain letter underneath."""
    d = unicodedata.normalize("NFD", ch)
    return d[0] if d and d[0].isascii() and d[0].isalpha() else None


def measure_cells(cells_dir, threshold, glyph_scale, snap_baseline=False):
    """Cheap pre-pass (no tracing): how tall each character will actually end
    up, in font units. Must match how the glyph gets placed later - a snapped
    letter stands on its own ink bottom, so its height is the ink height; a
    descender keeps the printed baseline, so measure its body above that.
    Also returns each character's stroke width in font units, for evening out
    pen weight."""
    heights, strokes = {}, {}
    for png in sorted(glob.glob(os.path.join(cells_dir, "*.png"))):
        try:
            with open(png[:-4] + ".json") as f:
                meta = json.load(f)
        except OSError:
            continue
        text = meta.get("text", "")
        if len(text) != 1:
            continue
        ink = np.asarray(Image.open(png).convert("L")) < threshold
        ys, xs = np.where(ink)
        if len(xs) == 0:
            continue
        scale = UPM / meta["box_h"] * glyph_scale
        snapped = (snap_baseline and (text.isalpha() or text.isdigit())
                   and not is_descender(text))
        if snapped:
            height = (ys.max() - ys.min()) * scale        # sits on its own ink
        else:
            height = (meta["baseline_y"] - ys.min()) * scale
        heights.setdefault(text, []).append(height)
        dt = ndimage.distance_transform_edt(ink)
        strokes.setdefault(text, []).append(2.0 * float(np.median(dt[ink])) * scale)
    med = lambda d: {c: sorted(v)[len(v) // 2] for c, v in d.items()}
    return med(heights), med(strokes)


def cell_width(png, threshold, glyph_scale):
    """Ink width of one cell in font units, for comparing an alternate's
    proportions against the primary's."""
    try:
        with open(png[:-4] + ".json") as f:
            meta = json.load(f)
    except OSError:
        return 0.0
    ink = np.asarray(Image.open(png).convert("L")) < threshold
    xs = np.where(ink.any(axis=0))[0]
    if len(xs) == 0:
        return 0.0
    return (xs.max() - xs.min()) * UPM / meta["box_h"] * glyph_scale


def is_clipped(png, threshold):
    """True if the ink runs into the bottom of the cell - a descender written
    past the box, which comes back with its tail cut off."""
    ink = np.asarray(Image.open(png).convert("L")) < threshold
    return bool(ink.any() and ink[-2:, :].any())


def text_of(chosen):
    return chosen[0]["meta"].get("text", "")


def cell_height(png, threshold, glyph_scale, snap_baseline):
    """Height one cell will occupy, in font units - same metric as
    measure_cells, but for a single candidate rather than a median."""
    try:
        with open(png[:-4] + ".json") as f:
            meta = json.load(f)
    except OSError:
        return None
    ink = np.asarray(Image.open(png).convert("L")) < threshold
    ys, xs = np.where(ink)
    if len(xs) == 0:
        return None
    scale = UPM / meta["box_h"] * glyph_scale
    text = meta.get("text", "")
    snapped = (snap_baseline and len(text) == 1
               and (text.isalpha() or text.isdigit())
               and not is_descender(text))
    if snapped:
        return (ys.max() - ys.min()) * scale
    return (meta["baseline_y"] - ys.min()) * scale


def normalization(heights, strength):
    """Per-character scale factors that pull every letter toward a common
    x-height (and ascenders toward a common ascender height). Handwriting
    drifts in size letter to letter; this evens it out without touching the
    shapes. strength 0 = off, 1 = fully uniform."""
    def median(chars):
        vals = [heights[c] for c in chars if c in heights]
        return sorted(vals)[len(vals) // 2] if vals else None

    target_x = median(SHORT_LETTERS)
    target_asc = median(ASCENDER_LETTERS)
    target_cap = median(CAPITALS)
    target_dig = median(DIGITS)
    factors = {}
    if not target_x:
        return factors, None
    for ch, h in heights.items():
        base = ascii_base(ch)
        # Only measure UNACCENTED letters: 'á' is taller than 'a' purely
        # because of the accent, so normalising it on total height would
        # shrink the whole letter. Accented forms inherit their base's factor.
        if base is None or base != ch or h <= 0:
            continue
        if base in SHORT_LETTERS or base in DESCENDERS:
            target = target_x          # descenders: body height above baseline
        elif base in ASCENDER_LETTERS and target_asc:
            target = target_asc
        elif base in CAPITALS and target_cap:
            target = target_cap        # capitals drift as much as lowercase
        else:
            continue
        factors[ch] = 1.0 + strength * (target / h - 1.0)
    # digits have no ascii_base (not letters), so handle them directly
    if target_dig:
        for ch, h in heights.items():
            if ch in DIGITS and h > 0:
                factors[ch] = 1.0 + strength * (target_dig / h - 1.0)
    for ch in heights:
        base = ascii_base(ch)
        if ch not in factors and base in factors:
            factors[ch] = factors[base]
    return factors, target_x


def build_glyph(cell_png, meta, threshold, turdsize, lsb, rsb,
                snap_baseline=False, glyph_scale=1.0,
                center_symbols=False, extra_scale=1.0, dy=0.0,
                math_axis=None, accent_overhang=True,
                target_stroke=None, quote_top=None):
    """Return (TTGlyph, advance_width, lsb, profiles) or None if cell empty."""
    gray = np.asarray(Image.open(cell_png).convert("L"))
    ink = gray < threshold

    # Even out pen weight: a lighter-pressure letter traces thinner than its
    # neighbours. Nudging the ink THRESHOLD grows or shrinks the stroke
    # smoothly (it eats into the scanner's antialiased edge), which beats
    # dilating by whole pixels - at these cell sizes one pixel is already a
    # ~10% jump in weight.
    if target_stroke and ink.any():
        px_to_units = UPM / meta["box_h"] * glyph_scale * extra_scale
        want = target_stroke / max(px_to_units, 1e-6)
        best, best_err = ink, None
        for t in range(max(35, threshold - 60), threshold + 71, 4):
            cand = gray < t
            if not cand.any():
                continue
            w = 2.0 * float(np.median(
                ndimage.distance_transform_edt(cand)[cand]))
            err = abs(w - want)
            if best_err is None or err < best_err:
                best, best_err = cand, err
        ink = best

    # A solidly filled selection circle sits just above its box, so a few
    # pixels of it can land inside the crop and show up as a speck floating
    # over the letter. Drop small blobs touching the TOP border only - the
    # bottom and sides are where a descender tail or a wide letter genuinely
    # runs to the edge, and eating those would amputate the glyph.
    if ink.any():
        labels, n = ndimage.label(ink)
        if n > 1:
            total = float(ink.sum())
            for lab in set(labels[0, :]):
                if lab and (labels == lab).sum() < 0.15 * total:
                    ink &= labels != lab

    ys, xs = np.where(ink)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    pad = 4 + (8 if extra_scale != 1.0 else 0)
    crop = np.zeros((y1 - y0 + 2 * pad, x1 - x0 + 2 * pad), dtype=bool)
    crop[pad:-pad, pad:-pad] = ink[y0:y1, x0:x1]

    # Scaling a glyph scales its stroke too, so a letter shrunk to match the
    # x-height comes out visibly thinner than its neighbours. Thicken (or
    # thin) the ink first by the matching amount so the pen weight survives.
    if extra_scale != 1.0 and crop.any():
        stroke = 2.0 * float(np.median(
            ndimage.distance_transform_edt(crop)[crop]))
        k = stroke * (1.0 / extra_scale - 1.0) / 2.0
        if k >= 0.5:
            crop = ndimage.binary_dilation(crop, iterations=int(round(k)))
        elif k <= -0.5:
            crop = ndimage.binary_erosion(crop, iterations=int(round(-k)))

    # template box height == full em span; glyph_scale shrinks the drawn
    # letters within that em so the font sets at a normal size next to other
    # fonts at the same point size (everything - heights, widths, advances,
    # kern profiles - derives from this one factor, so it stays consistent)
    scale = UPM / meta["box_h"] * glyph_scale * extra_scale
    if (y1 - y0) * scale < 8:    # a stray dot, not a glyph
        return None
    svg_transform, dees = trace_cell(crop, turdsize)

    baseline_in_crop = meta["baseline_y"] - y0 + pad
    # Baseline snapping: instead of trusting where the pen sat in the box,
    # drop the glyph's actual ink bottom onto the baseline. This cancels the
    # per-letter vertical "float" that makes a hand-built font bounce. Skipped
    # for descenders (they belong below the line) and for anything that isn't a
    # single letter/digit (punctuation, symbols, ligatures sit by design).
    text = meta.get("text", "")
    snappable = (len(text) == 1 and (text.isalpha() or text.isdigit())
                 and not is_descender(text))
    if snap_baseline and snappable:
        baseline_in_crop = (y1 - 1 - y0) + pad  # bottom-most ink row
    elif center_symbols and text in HANG_PUNCT and quote_top:
        # top of the ink sits AT the ascender line; freehand quotes drift far
        # above it (measured: apostrophe topping out 160 units over the
        # tallest ascender, reading as detached from the word)
        baseline_in_crop = quote_top / scale + pad
    elif center_symbols and text in BASELINE_PUNCT:
        drop = AT_DROP if text == "@" else 0.0
        baseline_in_crop = (y1 - 1 - y0) + pad - drop * (y1 - 1 - y0)
    elif center_symbols and text in BRACKETS:
        baseline_in_crop = (y1 - 1 - y0) + pad - BRACKET_DROP * (y1 - 1 - y0)
    elif center_symbols and text in CENTERED:
        # put the ink's vertical middle on the math axis (half the x-height,
        # measured from this font's own letters when we know it)
        axis = MATH_AXIS if math_axis is None else math_axis
        mid_row = (y1 - 1 - y0) / 2.0 + pad
        baseline_in_crop = mid_row + axis / scale
    # crop pixels (y down) -> font units (y up), ink left edge at x=lsb;
    # dy nudges the whole glyph up or down (per-character tuning)
    x_off = lsb - pad * scale
    font_transform = (scale, 0, 0, -scale, x_off,
                      baseline_in_crop * scale + dy)

    tt_pen = TTGlyphPen(None)
    quad_pen = Cu2QuPen(tt_pen, max_err=2.0)
    pen = TransformPen(TransformPen(quad_pen, font_transform), svg_transform)
    for d in dees:
        parse_path(d, pen)

    # An accent that sticks out sideways (Czech ď, ť, ľ, or an acute written
    # to the right) must not be charged to the letter's width, or the next
    # letter starts a caron-width too far away. Real fonts let the accent
    # overhang the sidebearing; the kern profiles still carry it, so nothing
    # collides. Only for accented letters - on '%' or '=' the pieces ARE the
    # character.
    right = x1 - 1
    if accent_overhang and len(text) == 1 and ascii_base(text) not in (None, text):
        labels, n = ndimage.label(ink)
        if n > 1:
            sizes = ndimage.sum_labels(ink, labels, index=np.arange(1, n + 1))
            body = np.argmax(sizes) + 1
            right = max(x0, int(np.where(labels == body)[1].max()))
    advance = int(round((right - x0 + 1) * scale)) + lsb + rsb
    prof = ink_profiles(crop, scale, x_off, baseline_in_crop, dy)
    return tt_pen.glyph(), advance, lsb, prof


def build_font(cells_dir, out_path, family, style="Regular", threshold=110,
               turdsize=15, lsb=18, rsb=18, space_width=250,
               target_gap=40, kern_min=8, snap_baseline=False,
               glyph_scale=1.0, center_symbols=False, max_tuck=0.15,
               primary=None, normalize=0.0, adjust=None,
               accent_overhang=True, even_alternates=True,
               even_weight=True, alt_tolerance=0.18):
    glyphs, metrics, cmap = {}, {}, {}
    primary = primary or {}
    adjust = adjust or {}

    # Even out letter sizes, and locate the math axis from this font's own
    # x-height, before any tracing happens.
    heights, strokes = measure_cells(cells_dir, threshold, glyph_scale,
                                     snap_baseline)
    # Pen pressure drifts between letters, so some come out visibly lighter.
    # Aim every glyph at the median stroke width of the plain letters.
    letter_strokes = [v for c, v in strokes.items()
                      if len(c) == 1 and c.isalpha() and ascii_base(c) == c]
    target_stroke = (sorted(letter_strokes)[len(letter_strokes) // 2]
                     if letter_strokes and even_weight else None)
    norm, target_x = normalization(heights, normalize) if normalize else ({}, None)
    math_axis = target_x / 2.0 if target_x else None
    asc_heights = [heights[c] for c in ASCENDER_LETTERS if c in heights]
    quote_top = (sorted(asc_heights)[len(asc_heights) // 2]
                 if asc_heights else None)
    if norm:
        worst = sorted(norm.items(), key=lambda kv: -abs(kv[1] - 1))[:4]
        print("  evened out letter sizes: " +
              ", ".join(f"{c} x{f:.2f}" for c, f in worst) + " ...")

    notdef_pen = TTGlyphPen(None)
    for contour in ([(80, 0), (80, 700), (420, 700), (420, 0)],
                    [(120, 40), (380, 40), (380, 660), (120, 660)]):
        notdef_pen.moveTo(contour[0])
        for pt in contour[1:]:
            notdef_pen.lineTo(pt)
        notdef_pen.closePath()
    glyphs[".notdef"] = notdef_pen.glyph()
    metrics[".notdef"] = (500, 80)

    glyphs["space"] = TTGlyphPen(None).glyph()
    metrics["space"] = (space_width, 0)
    cmap[0x20] = "space"

    # Group cells by base glyph. Templates give every character three
    # candidate boxes ("a.cand1"...) plus a circle the writer fills in for the
    # versions they want. First filled-in candidate = the glyph, further
    # filled-in ones = rotating alternates. Filled-but-empty or unfilled boxes
    # are dropped; if nothing is filled in, every non-empty box is used.
    # Old-style cells without candidate metadata pass through one-to-one.
    groups = {}
    for png in sorted(glob.glob(os.path.join(cells_dir, "*.png"))):
        with open(png[:-4] + ".json") as f:
            meta = json.load(f)
        base = meta.get("base", meta["glyph"])
        groups.setdefault(base, []).append((meta.get("cand") or 0, png, meta))

    skipped, rejected, ligatures, alternates, smallcaps = [], 0, {}, {}, {}
    clipped = {}
    odd_shape = {}
    profiles, advances = {}, {}   # per-glyph, for auto-kerning
    for base, cands in sorted(groups.items()):
        cands.sort(key=lambda c: c[0])
        # Measure first (cheap, no tracing) so selection and sizing are decided
        # before anything gets traced - then only the keepers are built.
        usable = []
        for cand_no, png, meta in cands:
            h = cell_height(png, threshold, glyph_scale, snap_baseline)
            if h is not None:
                usable.append({"cand": cand_no, "png": png, "meta": meta,
                               "h": h, "w": cell_width(png, threshold,
                                                       glyph_scale),
                               "clipped": is_clipped(png, threshold)})
        if not usable:
            skipped.append(base)
            continue

        marked = [u for u in usable if u["meta"].get("marked")]
        chosen = marked if marked else usable
        # A tail written past the bottom of the box comes back cut off. Prefer
        # an unclipped version for the letter itself; clipped ones drop to
        # alternates (or out entirely if there is a clean one).
        if any(u["clipped"] for u in chosen) and not all(u["clipped"] for u in chosen):
            # Drop them, do not demote: a cut-off tail is just as wrong in an
            # alternate, and the rotation puts it on screen anyway.
            clipped.setdefault(text_of(chosen), []).extend(
                u["cand"] for u in chosen if u["clipped"])
            chosen = [u for u in chosen if not u["clipped"]]
        rejected += len(usable) - len(chosen)
        # --primary promotes a different one of your three versions to be THE
        # letter (the rest stay alternates), no rescanning needed.
        text = chosen[0]["meta"].get("text", "")
        want = primary.get(text)
        if want is not None:
            # An explicit --primary beats the filled-in circles, and may name
            # a box you never filled: sometimes the version you skipped is the
            # one that sits best next to the others.
            pick = [u for u in usable if u["cand"] == want]
            if pick:
                chosen = pick + [u for u in chosen if u["cand"] != want]
        # An alternate should read as the same letter written again, not as a
        # different letter. Matching heights is not enough - one version of
        # 'h' came out 28% wider than the primary and looked unhinged in
        # running text. Compare proportions and drop the outliers.
        if even_alternates and len(chosen) > 1:
            a0 = chosen[0]["w"] / max(chosen[0]["h"], 1e-6)
            keep = [chosen[0]]
            for u in chosen[1:]:
                a = u["w"] / max(u["h"], 1e-6)
                if abs(a - a0) / max(a0, 1e-6) <= alt_tolerance:
                    keep.append(u)
                else:
                    odd_shape.setdefault(text_of(chosen), []).append(u["cand"])
            chosen = keep
        chosen = chosen[:3]
        text = chosen[0]["meta"]["text"]

        tweak = adjust.get(text, {})
        base_scale = norm.get(text, 1.0) * tweak.get("scale", 1.0)
        g_lsb = lsb + int(tweak.get("lsb", 0))
        g_rsb = rsb + int(tweak.get("rsb", 0))
        h0 = chosen[0]["h"]

        results = []
        for idx, u in enumerate(chosen):
            extra = base_scale
            # Alternates should vary in SHAPE, not size. If one version of 'i'
            # carries its dot higher, neighbouring i's read as a doubled dot
            # rather than as natural variation, so match the primary's height.
            if even_alternates and idx > 0 and h0 and u["h"] > 0:
                extra *= h0 / u["h"]
            r = build_glyph(u["png"], u["meta"], threshold, turdsize,
                            g_lsb, g_rsb,
                            snap_baseline=snap_baseline,
                            glyph_scale=glyph_scale,
                            center_symbols=center_symbols,
                            extra_scale=extra,
                            dy=tweak.get("dy", 0.0),
                            math_axis=math_axis,
                            accent_overhang=accent_overhang,
                            target_stroke=target_stroke,
                            quote_top=quote_top)
            if r is not None:
                results.append(r)
        if not results:
            skipped.append(base)
            continue

        for idx, (glyph, advance, glyph_lsb, prof) in enumerate(results):
            name = base if idx == 0 else f"{base}.alt{idx}"
            glyphs[name] = glyph
            metrics[name] = (advance, glyph_lsb)
            profiles[name] = prof
            advances[name] = advance
            if idx == 0:
                if len(text) == 1 and "." not in name:
                    cmap[ord(text)] = name
                if len(text) > 1:
                    ligatures[name] = text
                if name.endswith(".sc"):
                    smallcaps[name] = text
            else:
                alternates[name] = text
    if odd_shape:
        print("  alternates dropped for odd proportions: " +
              ", ".join(f"{c}{v}" for c, v in sorted(odd_shape.items())))
    if clipped:
        print("  clipped versions dropped: " +
              ", ".join(f"{c}{v}" for c, v in sorted(clipped.items())))
    if skipped:
        print(f"  skipped empty characters: {' '.join(skipped)}")
    if rejected:
        print(f"  discarded {rejected} unfilled versions")

    # Editors type curly quotes and real dashes; without these the text falls
    # back to another font mid-word ("It's" in a different hand). Point them at
    # the plain characters we captured.
    for cp, target in ((0x2019, "quotesingle"), (0x2018, "quotesingle"),
                       (0x201C, "quotedbl"), (0x201D, "quotedbl"),
                       (0x2013, "hyphen"), (0x2014, "hyphen"),
                       (0x00A0, "space"), (0x2212, "hyphen")):
        if cp not in cmap and target in glyphs:
            cmap[cp] = target

    # No euro on the base keyboard sheet (it lives in the "symbols" module).
    # Until that sheet is scanned, synthesise one from this hand's own parts:
    # the C, crossed by two bars made from the hyphen. Replaced automatically
    # by the real drawing the moment a symbols scan provides one.
    if 0x20AC not in cmap and "C" in glyphs and "hyphen" in glyphs:
        pen = TTGlyphPen(glyphs)
        pen.addComponent("C", (1, 0, 0, 1, 60, 0))
        hb = 0.55
        for dy in (120, 255):
            pen.addComponent("hyphen", (hb, 0, 0, 0.75, 0, dy))
        glyphs["Euro"] = pen.glyph()
        metrics["Euro"] = (metrics["C"][0] + 60, metrics["C"][1])
        cmap[0x20AC] = "Euro"
        print("  synthesised a Euro from C + hyphen (scan the symbols "
              "sheet to replace it with your real one)")

    order = [".notdef", "space"] + sorted(n for n in glyphs if n not in (".notdef", "space"))
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENDER + 50, descent=DESCENDER - 50)
    fb.setupNameTable({
        "familyName": family,
        "styleName": style,
        "fullName": f"{family} {style}",
        "psName": f"{family.replace(' ', '')}-{style}",
        "version": "Version 1.0",
    })
    fb.setupOS2(sTypoAscender=ASCENDER, sTypoDescender=DESCENDER,
                sTypoLineGap=90, usWinAscent=ASCENDER + 50,
                usWinDescent=abs(DESCENDER) + 50)
    fb.setupPost()

    kern = compute_kerning(glyphs, cmap, profiles, advances, alternates,
                           target_gap, kern_min, max_tuck)
    fea = build_features(glyphs, ligatures, alternates, smallcaps, kern)
    if fea:
        addOpenTypeFeaturesFromString(fb.font, fea)
    fb.save(out_path)
    print(f"wrote {out_path}  ({len(order)} glyphs, {len(ligatures)} ligatures, "
          f"{len(alternates)} alternates, {len(smallcaps)} small caps, "
          f"{len(kern['pairs'])} kern pairs)")


def compute_kerning(glyphs, cmap, profiles, advances, alternates,
                    target_gap, kern_min, max_tuck=0.15):
    """Auto-kern letter/digit pairs by their ink shapes: slide the right glyph
    until its closest approach to the left glyph equals target_gap. Letters
    that interlock (To, Va, r., ...) tuck closer or overlap; blocky pairs stay
    apart - the same thing a hand does. Accented letters (a, a, a) and a
    letter's alternates all ride in that base letter's kern class, so the table
    stays small while variation and diacritics keep the same spacing."""
    # Identities are the plain ASCII letters/digits present. Each accented
    # letter folds onto its ASCII base (e -> e), sharing its kerning.
    name2cp = {}
    for cp, n in cmap.items():
        name2cp.setdefault(n, cp)

    def ascii_base(cp):
        d = unicodedata.normalize("NFD", chr(cp))
        return d[0] if d and d[0].isascii() and d[0].isalnum() else None

    ident, cls = [], {}
    for cp, n in sorted(cmap.items(), key=lambda kv: kv[1]):
        if ascii_base(cp) == chr(cp) and chr(cp).isalnum() and profiles.get(n):
            ident.append(n)
            cls[n] = [n]
    ascii_name = {chr(name2cp[n]): n for n in ident}
    # pass 1: fold accented letters onto their ASCII base class (e -> e)
    for cp, n in cmap.items():
        b = ascii_base(cp)
        if b in ascii_name and n != ascii_name[b]:
            cls[ascii_name[b]].append(n)
    # pass 2: fold every glyph's alternates into whatever class holds its base
    for n in list(glyphs):
        if ".alt" not in n:
            continue
        base = n[:-5]
        for members in cls.values():
            if base in members:
                members.append(n)
                break

    adv_list = sorted(advances[n] for n in ident if n in advances)
    typical_advance = adv_list[len(adv_list) // 2] if adv_list else UPM * 0.4

    def pair_kern(nl, nr):
        pl, pr = profiles[nl], profiles[nr]
        shared = set(pl) & set(pr)
        if not shared:
            return 0
        # closest approach if right origin sits at advances[nl]:
        # gap(band) = advances[nl] + pr_left[band] - pl_right[band]
        slack = min(pr[b][0] - pl[b][1] for b in shared)
        kern = int(round(target_gap - advances[nl] - slack))
        # Clamp how far a pair may tuck. A letter with a big overhang (y, j,
        # f, T, V) otherwise drags its neighbour a quarter of a glyph width
        # underneath itself - the closest approach is still "correct", but it
        # reads as two letters merging.
        #
        # The cap is a share of the font's TYPICAL advance, not of this
        # letter's own. Scaling it to the left glyph starves the narrow ones:
        # 'l' is half the width of 'n', so 'ly' got a third less tuck than
        # 'ny' and stayed visibly apart, even though the gap it needs to close
        # is the same either way.
        limit = int(round(max_tuck * typical_advance))
        return max(kern, -limit)

    pairs = {}
    for nl in ident:
        for nr in ident:
            k = pair_kern(nl, nr)
            if abs(k) >= kern_min:
                pairs[(nl, nr)] = k
    return {"classes": cls, "pairs": pairs}


def build_features(glyphs, ligatures, alternates, smallcaps, kern=None):
    """Generate liga (ligatures) + calt (alternate rotation) + kern feature
    code from whatever glyphs actually exist. Cells left blank simply produce
    no rules."""
    def base_name(ch):
        return agl.UV2AGL.get(ord(ch), f"uni{ord(ch):04X}")

    lines = ["languagesystem DFLT dflt;", "languagesystem latn dflt;"]

    # Kerning: class-based GPOS pairs (a glyph and its alternates kern alike).
    if kern and kern["pairs"]:
        for name, members in sorted(kern["classes"].items()):
            if len(members) > 1:
                lines.append(f"@K_{name} = [{' '.join(members)}];")
        krules = []
        for (nl, nr), v in sorted(kern["pairs"].items()):
            gl = f"@K_{nl}" if len(kern["classes"].get(nl, [nl])) > 1 else nl
            gr = f"@K_{nr}" if len(kern["classes"].get(nr, [nr])) > 1 else nr
            krules.append(f"    pos {gl} {gr} {v};")
        lines += ["feature kern {"] + krules + ["} kern;"]

    # Ligatures, longest first so 'ffi' wins over 'ff'/'fi'.
    liga_rules = []
    for lig_name, text in sorted(ligatures.items(), key=lambda kv: -len(kv[1])):
        components = [base_name(c) for c in text]
        if all(c in glyphs for c in components):
            liga_rules.append(f"    sub {' '.join(components)} by {lig_name};")
    if liga_rules:
        lines += ["feature liga {"] + liga_rules + ["} liga;"]

    # Small caps: smcp turns lowercase into small caps; c2sc turns capitals
    # into small caps. Using both gives the classic "Title Case in capitals,
    # first letter full-size" look.
    smcp_rules, c2sc_rules = [], []
    for sc_name, text in sorted(smallcaps.items()):
        lower = base_name(text)
        upper = base_name(text.upper())
        if lower in glyphs:
            smcp_rules.append(f"    sub {lower} by {sc_name};")
        if upper in glyphs:
            c2sc_rules.append(f"    sub {upper} by {sc_name};")
    if smcp_rules:
        lines += ["feature smcp {"] + smcp_rules + ["} smcp;"]
    if c2sc_rules:
        lines += ["feature c2sc {"] + c2sc_rules + ["} c2sc;"]

    # Pseudo-random alternates: rotate default -> alt1 -> alt2 along a line.
    # Any character can have alternates (its extra filled-in versions). Both
    # rules are chained contextual substitutions; within one lookup, earlier
    # substitutions change the context seen by later positions, which is
    # exactly what makes the states alternate.
    have1 = sorted(n[:-5] for n in glyphs if n.endswith(".alt1") and n[:-5] in glyphs)
    have2 = sorted(n[:-5] for n in glyphs
                   if n.endswith(".alt2") and n[:-5] in glyphs and n[:-5] in have1)
    context = sorted(n for n in glyphs
                     if n not in (".notdef", "space") and ".alt" not in n)
    if have1 and context:
        lines += [
            f"@CTX = [{' '.join(context)}];",
            f"@R1F = [{' '.join(have1)}];",
            f"@R1T = [{' '.join(n + '.alt1' for n in have1)}];",
        ]
        calt = ["feature calt {", "    sub @CTX @R1F' by @R1T;"]
        if have2:
            lines += [
                f"@A1 = [{' '.join(n + '.alt1' for n in have1)}];",
                f"@R2F = [{' '.join(have2)}];",
                f"@R2T = [{' '.join(n + '.alt2' for n in have2)}];",
            ]
            calt.append("    sub @A1 @R2F' by @R2T;")
        lines += calt + ["} calt;"]
    return "\n".join(lines) if len(lines) > 2 else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cells", required=True, help="directory from segment.py")
    ap.add_argument("--out", required=True, help="output .ttf path")
    ap.add_argument("--family", default="My Handwriting")
    ap.add_argument("--style", default="Regular")
    ap.add_argument("--threshold", type=int, default=110,
                    help="ink threshold 0-255; lower it if gray guides leak in")
    ap.add_argument("--turdsize", type=int, default=15,
                    help="potrace speckle suppression, in pixels")
    ap.add_argument("--lsb", type=int, default=18, help="left side bearing (units)")
    ap.add_argument("--rsb", type=int, default=18, help="right side bearing (units)")
    ap.add_argument("--space-width", type=int, default=250)
    ap.add_argument("--target-gap", type=int, default=40,
                    help="auto-kern: font-unit gap between adjacent letters at "
                         "their closest point (lower = tighter/more joined)")
    ap.add_argument("--kern-min", type=int, default=8,
                    help="skip kern pairs smaller than this many units")
    ap.add_argument("--glyph-scale", type=float, default=1.0,
                    help="shrink the drawn letters within the em (0.92 sets a "
                         "bit smaller next to other fonts at the same pt size)")
    ap.add_argument("--alt-tolerance", type=float, default=0.18,
                    help="how far an alternate's proportions may stray from "
                         "the primary before it is dropped")
    ap.add_argument("--no-even-weight", action="store_true",
                    help="keep each letter's own pen weight instead of "
                         "matching the median stroke width")
    ap.add_argument("--no-even-alternates", action="store_true",
                    help="let alternates keep their own size (by default each "
                         "alternate is scaled to the primary's height)")
    ap.add_argument("--no-accent-overhang", action="store_true",
                    help="charge sideways accents (d-caron, t-caron) to the "
                         "letter's width instead of letting them overhang")
    ap.add_argument("--normalize", type=float, default=0.0,
                    help="even out letter sizes toward a common x-height "
                         "(0 = off, 1 = fully uniform; 0.7 is a good start)")
    ap.add_argument("--adjust-file", default=None,
                    help="JSON of per-character tweaks, e.g. "
                         '{"o": {"scale": 0.95}, "y": {"dy": -30}}')
    ap.add_argument("--primary", default="",
                    help="promote a different filled-in version to be the "
                         "letter itself, e.g. 'o=2,a=3' (box numbers 1-3)")
    ap.add_argument("--max-tuck", type=float, default=0.15,
                    help="cap a negative kern at this share of the left "
                         "glyph's width, so overhangs don't swallow neighbours")
    ap.add_argument("--center-symbols", action="store_true",
                    help="vertically centre arrows and math operators on the "
                         "math axis instead of where the pen sat")
    ap.add_argument("--snap-baseline", action="store_true",
                    help="drop each letter/digit's ink bottom onto the baseline "
                         "(cancels per-letter vertical float; descenders exempt)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    build_font(args.cells, args.out, args.family, args.style, args.threshold,
               args.turdsize, args.lsb, args.rsb, args.space_width,
               args.target_gap, args.kern_min, args.snap_baseline,
               args.glyph_scale, args.center_symbols, args.max_tuck,
               {k: int(v) for k, v in
                (p.split("=") for p in args.primary.split(",") if p)},
               args.normalize,
               json.load(open(args.adjust_file)) if args.adjust_file else None,
               not args.no_accent_overhang,
               not args.no_even_alternates,
               not args.no_even_weight, args.alt_tolerance)


if __name__ == "__main__":
    main()
