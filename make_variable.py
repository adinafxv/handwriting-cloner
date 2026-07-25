#!/usr/bin/env python3
"""Turn the static handwriting font into a variable font with a weight axis.

Variable fonts interpolate between "masters" that must share identical point
structures. Rather than asking you to write the whole alphabet again with a
thicker pen (and then somehow making the traces point-compatible, which
autotracing can't guarantee), this script derives Light and Bold masters from
the Regular one: every outline point is displaced along its outward normal
(inward for the Light master, outward for Bold). Holes (counters, like the
inside of "o") are classified by nesting and displaced the opposite way, so
bold shrinks them just like a wider pen would. Same point count and order in
every master -> clean interpolation.

Usage:
    python3 make_variable.py --regular work/MyHand-Regular.ttf \
        --out work/MyHandVF.ttf --light-offset 12 --bold-offset 26
"""

import argparse
import copy
import math
import os

from fontTools.designspaceLib import (AxisDescriptor, DesignSpaceDocument,
                                      InstanceDescriptor, SourceDescriptor)
from fontTools.ttLib import TTFont
from fontTools import varLib


def contour_points(glyph, glyf_table):
    coords, ends, _ = glyph.getCoordinates(glyf_table)
    contours, start = [], 0
    for end in ends:
        contours.append([tuple(p) for p in coords[start:end + 1]])
        start = end + 1
    return contours


def signed_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def point_in_polygon(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        if (y0 > y) != (y1 > y):
            xint = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xint > x:
                inside = not inside
    return inside


def contour_is_hole(idx, contours):
    """A contour is a hole iff it nests inside an odd number of others."""
    probe = contours[idx][0]
    depth = sum(1 for j, other in enumerate(contours)
                if j != idx and point_in_polygon(probe, other))
    return depth % 2 == 1


def offset_contour(pts, delta, is_hole):
    """Displace each point along its ink-outward normal by delta."""
    n = len(pts)
    if n < 3:
        return list(pts)
    ccw = signed_area(pts) > 0
    # Outward normal of this polygon for edge direction (dx, dy):
    # CCW -> (dy, -dx); CW -> (-dy, dx). Ink-outward flips for holes.
    sign = (1.0 if ccw else -1.0) * (-1.0 if is_hole else 1.0)
    out = []
    for i in range(n):
        px, py = pts[(i - 1) % n]
        nx_, ny_ = pts[(i + 1) % n]
        tx, ty = nx_ - px, ny_ - py
        norm = math.hypot(tx, ty)
        if norm < 1e-9:
            out.append(pts[i])
            continue
        ox, oy = sign * ty / norm, -sign * tx / norm
        out.append((pts[i][0] + delta * ox, pts[i][1] + delta * oy))
    return out


def make_master(base_font, delta):
    font = copy.deepcopy(base_font)
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:  # empty or composite
            continue
        contours = contour_points(glyph, glyf)
        holes = [contour_is_hole(i, contours) for i in range(len(contours))]
        new_pts = []
        for i, pts in enumerate(contours):
            new_pts.extend(offset_contour(pts, delta, holes[i]))
        coords = glyph.coordinates
        for i, (x, y) in enumerate(new_pts):
            # shift by +delta so the left side bearing stays put
            coords[i] = (int(round(x + delta)), int(round(y)))
        advance, lsb = hmtx[name]
        hmtx[name] = (max(1, advance + 2 * int(round(delta))), lsb)
    return font


def set_style_name(font, style):
    name = font["name"]
    family = name.getDebugName(1)
    name.setName(style, 2, 3, 1, 0x409)
    name.setName(f"{family} {style}", 4, 3, 1, 0x409)
    name.setName(f"{family.replace(' ', '')}-{style}", 6, 3, 1, 0x409)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--regular", required=True, help="static TTF from build_font.py")
    ap.add_argument("--out", required=True, help="output variable .ttf")
    ap.add_argument("--base-offset", type=float, default=13,
                    help="units to thicken the Regular master itself before "
                         "deriving Light/Bold. Pen-traced handwriting comes out "
                         "thin, so the default (13) makes the shipped Regular "
                         "match what wght=550 used to look like; Light then "
                         "lands on the old untouched weight. 0 = raw trace")
    ap.add_argument("--light-offset", type=float, default=13,
                    help="units to thin strokes for the Light master "
                         "(relative to the base-offset Regular)")
    ap.add_argument("--bold-offset", type=float, default=26,
                    help="units to thicken strokes for the Bold master "
                         "(relative to the base-offset Regular)")
    ap.add_argument("--keep-masters", action="store_true",
                    help="also write the Light/Bold master TTFs next to --out")
    args = ap.parse_args()

    regular = TTFont(args.regular)
    if args.base_offset:
        print(f"thickening Regular master by {args.base_offset:g} units...")
        regular = make_master(regular, abs(args.base_offset))
        set_style_name(regular, "Regular")
    print("deriving Light master...")
    light = make_master(regular, -abs(args.light_offset))
    set_style_name(light, "Light")
    print("deriving Bold master...")
    bold = make_master(regular, abs(args.bold_offset))
    set_style_name(bold, "Bold")

    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    master_paths = {}
    for style, font in (("Light", light), ("Regular", regular), ("Bold", bold)):
        p = os.path.join(outdir, f"_master-{style}.ttf")
        font.save(p)
        master_paths[style] = p

    ds = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.tag, axis.name = "wght", "Weight"
    axis.minimum, axis.default, axis.maximum = 300, 400, 700
    ds.addAxis(axis)
    for style, wght in (("Light", 300), ("Regular", 400), ("Bold", 700)):
        src = SourceDescriptor()
        src.path = master_paths[style]
        src.location = {"Weight": wght}
        src.styleName = style
        ds.addSource(src)
        inst = InstanceDescriptor()
        inst.styleName = style
        inst.location = {"Weight": wght}
        ds.addInstance(inst)

    print("interpolating variable font...")
    vf, _, _ = varLib.build(ds)
    vf.save(args.out)
    print(f"wrote {args.out}")

    if not args.keep_masters:
        for p in master_paths.values():
            if p != os.path.abspath(args.regular):
                os.remove(p)


if __name__ == "__main__":
    main()
