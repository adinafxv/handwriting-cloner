#!/usr/bin/env python3
"""Cut a scanned, filled-in template into one grayscale image per character.

Finds the four black corner registration marks on each scan, fits an affine
transform from template coordinates to scan coordinates (this absorbs
rotation, scale/DPI differences, and offset), then resamples every character
box back into template space. Page number is auto-detected from the ID dots
next to the top-left mark, or can be forced with --page.

Usage:
    python3 segment.py --layout templates/layout-a4.json \
        scans/page1.png scans/page2.png scans/page3.png --outdir work/cells

Output: work/cells/<codepoint>_<name>.png  (grayscale, template resolution)
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage


def find_registration_marks(gray, layout_page, template_size):
    """Return the 4 mark centers in scan coordinates, ordered TL, TR, BL, BR."""
    h, w = gray.shape
    tw, th = template_size
    scale_est = ((w / tw) + (h / th)) / 2.0
    expected_area = (layout_page["mark_px"] * scale_est) ** 2

    mask = gray < 100
    labels, n = ndimage.label(mask)
    if n == 0:
        raise RuntimeError("no dark pixels found - is this the right image?")
    slices = ndimage.find_objects(labels)
    sizes = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))

    candidates = []
    for i, sl in enumerate(slices):
        area = sizes[i]
        if not (0.25 * expected_area < area < 4.0 * expected_area):
            continue
        bh = sl[0].stop - sl[0].start
        bw = sl[1].stop - sl[1].start
        if max(bh, bw) / max(1, min(bh, bw)) > 1.6:
            continue
        if area / (bh * bw) < 0.5:  # marks are solid squares
            continue
        cy = (sl[0].start + sl[0].stop) / 2.0
        cx = (sl[1].start + sl[1].stop) / 2.0
        candidates.append((cx, cy, area))
    if len(candidates) < 4:
        raise RuntimeError(
            f"found only {len(candidates)} registration-mark candidates; "
            "rescan flat, in grayscale, with the whole page visible")

    marks = []
    for tx, ty in layout_page["reg_marks"]:
        sx, sy = tx * scale_est, ty * scale_est
        best = min(candidates, key=lambda c: (c[0] - sx) ** 2 + (c[1] - sy) ** 2)
        marks.append((best[0], best[1]))
    if len({(round(x), round(y)) for x, y in marks}) < 4:
        raise RuntimeError("two corners matched the same blob - scan looks distorted")
    return marks


def fit_affine(src_pts, dst_pts):
    """Least-squares affine A such that A @ [x, y, 1] ~ dst, per point."""
    src = np.array([[x, y, 1.0] for x, y in src_pts])
    dst = np.array(dst_pts)
    coef, residuals, _, _ = np.linalg.lstsq(src, dst, rcond=None)
    return coef.T  # 2x3


def apply_affine(A, x, y):
    return (A[0, 0] * x + A[0, 1] * y + A[0, 2],
            A[1, 0] * x + A[1, 1] * y + A[1, 2])


def detect_page(gray, A, layout_page_any):
    """Count dark ID dots at the known slots; page number = count."""
    count = 0
    r = max(2, layout_page_any["id_dot_px"] // 3)
    for tx, ty in layout_page_any["id_dot_slots"]:
        sx, sy = apply_affine(A, tx, ty)
        sx, sy = int(round(sx)), int(round(sy))
        patch = gray[max(0, sy - r):sy + r, max(0, sx - r):sx + r]
        if patch.size and patch.mean() < 128:
            count += 1
        else:
            break
    return count


def glyph_filename(cell):
    # glyph names (e.g. "a", "f_i", "a.cand1") are already filesystem-safe
    return f"{cell['glyph']}.png"


def check_is_filled(gray, A, check, scale):
    """True if the circle above a box has been filled in solid. The circle
    itself is printed in light gray, so only real pen ink counts. A deliberate
    fill covers roughly 0.5-0.8 of the circle's area; a stray mark or thin
    accidental line covers roughly 0.05-0.15, so the threshold sits well above
    that band to require an unambiguous fill."""
    cx, cy, r = check
    sx, sy = apply_affine(A, cx, cy)
    sr = max(3, int(r * scale * 0.8))
    patch = gray[max(0, int(sy) - sr):int(sy) + sr,
                 max(0, int(sx) - sr):int(sx) + sr]
    if patch.size == 0:
        return False
    return float(np.mean(patch < 120)) > 0.30


def try_orientation(img, page0):
    """Attempt registration on one orientation of the scan.
    Returns (gray, A, residual, detected_page) or None if marks not found."""
    gray = np.asarray(img, dtype=np.uint8)
    tw, th = page0["size"]
    try:
        marks = find_registration_marks(gray, page0, (tw, th))
    except RuntimeError:
        return None
    A = fit_affine(page0["reg_marks"], marks)  # template -> scan
    residual = max(
        abs(apply_affine(A, tx, ty)[0] - mx) + abs(apply_affine(A, tx, ty)[1] - my)
        for (tx, ty), (mx, my) in zip(page0["reg_marks"], marks))
    return gray, A, residual, detect_page(gray, A, page0)


def segment_scan(path, layout, outdir, forced_page=None, supersample=2):
    img_orig = Image.open(path).convert("L")
    page0 = layout["pages"][0]
    tw, th = page0["size"]

    # The four corner marks are symmetric, so a rotated scan (a landscape
    # sheet fed through a portrait scanner, an upside-down page) can still
    # "register" - the page-ID dots are the arbiter of true orientation.
    # Try all four rotations and keep the one where the dots read.
    best = None
    for rot in (0, 270, 90, 180):
        img = img_orig if rot == 0 else img_orig.rotate(rot, expand=True)
        result = try_orientation(img, page0)
        if result is None:
            continue
        if best is None:
            best = (rot, img, result)
        if result[3] > 0:  # dots found: this orientation is correct
            best = (rot, img, result)
            break
    if best is None:
        raise RuntimeError(f"{path}: no registration marks found in any "
                           "orientation - rescan flat in grayscale")
    rot, img, (gray, A, residual, detected) = best
    if rot:
        print(f"{os.path.basename(path)}: auto-rotated {rot} degrees")

    if residual > 0.01 * max(tw, th):
        print(f"  warning: registration residual is high ({residual:.1f}px); "
              "check that the scan is flat", file=sys.stderr)

    if forced_page is not None:
        page_no = forced_page
    elif detected > 0:
        page_no = detected
    else:
        raise RuntimeError(
            f"{path}: could not read the page-ID dots; pass --page N")
    page = next(p for p in layout["pages"] if p["page"] == page_no)
    print(f"{os.path.basename(path)}: page {page_no}, "
          f"registration residual {residual:.1f}px")
    if page.get("sample") or not page["cells"]:
        print("  writing-sample page - kept as a style reference, "
              "no glyphs to extract")
        return

    os.makedirs(outdir, exist_ok=True)
    inset = 5
    s = supersample
    # affine scale factor (template px -> scan px), for sizing the fill probe
    scan_scale = float(np.hypot(A[0, 0], A[1, 0]))
    gray_full = np.asarray(img, dtype=np.uint8)
    written, filled = [], 0
    for cell in page["cells"]:
        x0, y0, x1, y1 = cell["box"]
        x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        bw, bh = x1 - x0, y1 - y0
        # PIL AFFINE maps output pixel -> source pixel; compose our affine
        # with the translation to this box's origin in template space.
        # Output is rendered at supersample x template resolution so that
        # high-DPI scans keep their detail for tracing.
        coeffs = (A[0, 0] / s, A[0, 1] / s, A[0, 0] * x0 + A[0, 1] * y0 + A[0, 2],
                  A[1, 0] / s, A[1, 1] / s, A[1, 0] * x0 + A[1, 1] * y0 + A[1, 2])
        cell_img = img.transform((bw * s, bh * s), Image.AFFINE, coeffs,
                                 resample=Image.BILINEAR, fillcolor=255)
        meta = {
            "text": cell["text"],
            "glyph": cell["glyph"],
            "base": cell.get("base", cell["glyph"]),
            "cand": cell.get("cand"),
            "baseline_y": (cell["baseline_y"] - y0) * s,
            "xheight_y": (cell["xheight_y"] - y0) * s,
            "box_h": (cell["box"][3] - cell["box"][1]) * s,
        }
        if "check" in cell:
            meta["marked"] = check_is_filled(gray_full, A, cell["check"],
                                             scan_scale)
            filled += meta["marked"]
        fname = glyph_filename(cell)
        cell_img.save(os.path.join(outdir, fname))
        with open(os.path.join(outdir, fname[:-4] + ".json"), "w") as f:
            json.dump(meta, f)
        written.append(cell["text"])
    print(f"  wrote {len(written)} cells to {outdir}  ({filled} filled)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scans", nargs="+", help="scan images (png/jpg/tiff)")
    ap.add_argument("--layout", required=True, help="layout-*.json from make_template.py")
    ap.add_argument("--outdir", default="work/cells")
    ap.add_argument("--page", type=int, default=None,
                    help="force page number (otherwise auto-detected per scan)")
    ap.add_argument("--supersample", type=int, default=2,
                    help="cell extraction resolution multiplier vs the "
                         "template's 300dpi (2 suits 600 DPI scans)")
    args = ap.parse_args()

    with open(args.layout) as f:
        layout = json.load(f)
    for path in args.scans:
        segment_scan(path, layout, args.outdir, forced_page=args.page,
                     supersample=args.supersample)


if __name__ == "__main__":
    main()
