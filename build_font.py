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

import numpy as np
from PIL import Image
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


def build_glyph(cell_png, meta, threshold, turdsize, lsb, rsb):
    """Return (TTGlyph, advance_width, lsb) or None if the cell is empty."""
    gray = np.asarray(Image.open(cell_png).convert("L"))
    ink = gray < threshold

    ys, xs = np.where(ink)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    pad = 4
    crop = np.zeros((y1 - y0 + 2 * pad, x1 - x0 + 2 * pad), dtype=bool)
    crop[pad:-pad, pad:-pad] = ink[y0:y1, x0:x1]

    scale = UPM / meta["box_h"]  # template box height == full em span
    if (y1 - y0) * scale < 8:    # a stray dot, not a glyph
        return None
    svg_transform, dees = trace_cell(crop, turdsize)

    baseline_in_crop = meta["baseline_y"] - y0 + pad
    # crop pixels (y down) -> font units (y up), ink left edge at x=lsb
    font_transform = (scale, 0, 0, -scale,
                      lsb - pad * scale, baseline_in_crop * scale)

    tt_pen = TTGlyphPen(None)
    quad_pen = Cu2QuPen(tt_pen, max_err=2.0)
    pen = TransformPen(TransformPen(quad_pen, font_transform), svg_transform)
    for d in dees:
        parse_path(d, pen)

    advance = int(round((x1 - x0) * scale)) + lsb + rsb
    return tt_pen.glyph(), advance, lsb


def build_font(cells_dir, out_path, family, style="Regular", threshold=110,
               turdsize=15, lsb=30, rsb=30, space_width=280):
    glyphs, metrics, cmap = {}, {}, {}

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

    skipped, ligatures, alternates, smallcaps = [], {}, {}, {}
    for png in sorted(glob.glob(os.path.join(cells_dir, "*.png"))):
        with open(png[:-4] + ".json") as f:
            meta = json.load(f)
        name, text = meta["glyph"], meta["text"]
        result = build_glyph(png, meta, threshold, turdsize, lsb, rsb)
        if result is None:
            skipped.append(name)
            continue
        glyph, advance, glyph_lsb = result
        glyphs[name] = glyph
        metrics[name] = (advance, glyph_lsb)
        if len(text) == 1 and "." not in name:
            cmap[ord(text)] = name
        if len(text) > 1:
            ligatures[name] = text
        if ".alt" in name:
            alternates[name] = text
        if name.endswith(".sc"):
            smallcaps[name] = text
    if skipped:
        print(f"  skipped empty cells: {' '.join(skipped)}")

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

    fea = build_features(glyphs, ligatures, alternates, smallcaps)
    if fea:
        addOpenTypeFeaturesFromString(fb.font, fea)
    fb.save(out_path)
    print(f"wrote {out_path}  ({len(order)} glyphs, {len(ligatures)} ligatures, "
          f"{len(alternates)} alternates, {len(smallcaps)} small caps)")


def build_features(glyphs, ligatures, alternates, smallcaps):
    """Generate liga (ligatures) + calt (alternate rotation) feature code
    from whatever glyphs actually exist. Cells left blank simply produce no
    rules."""
    def base_name(ch):
        return agl.UV2AGL.get(ord(ch), f"uni{ord(ch):04X}")

    lines = ["languagesystem DFLT dflt;", "languagesystem latn dflt;"]

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

    # Pseudo-random alternates: rotate default -> alt1 -> alt2 along a word.
    # Both rules are chained contextual substitutions; within one lookup,
    # earlier substitutions change the context seen by later positions, which
    # is exactly what makes the states alternate.
    have1 = sorted(n[:-5] for n in alternates if n.endswith(".alt1") and n[:-5] in glyphs)
    have2 = sorted(n[:-5] for n in alternates if n.endswith(".alt2") and n[:-5] in glyphs)
    letters = sorted(n for n in glyphs
                     if len(n) == 1 and n.islower() and n.isalpha())
    if have1 and letters:
        lines += [
            f"@LC = [{' '.join(letters)}];",
            f"@R1F = [{' '.join(have1)}];",
            f"@R1T = [{' '.join(n + '.alt1' for n in have1)}];",
        ]
        calt = ["feature calt {", "    sub @LC @R1F' by @R1T;"]
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
    ap.add_argument("--lsb", type=int, default=30, help="left side bearing (units)")
    ap.add_argument("--rsb", type=int, default=30, help="right side bearing (units)")
    ap.add_argument("--space-width", type=int, default=280)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    build_font(args.cells, args.out, args.family, args.style, args.threshold,
               args.turdsize, args.lsb, args.rsb, args.space_width)


if __name__ == "__main__":
    main()
