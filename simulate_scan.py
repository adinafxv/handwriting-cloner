#!/usr/bin/env python3
"""Produce fake "filled-in scans" of the template, for testing the pipeline
without a printer or scanner. Draws each character into its box using an
installed system font, then rotates and rescales the page slightly to imitate
a real scan.

Usage:
    python3 simulate_scan.py --layout templates/layout-a4.json --outdir work/sim
"""

import argparse
import json
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

import make_template

FAKE_HAND_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def load_font_picker():
    """Return picker(text) -> font path covering all of text's characters
    (falls back to the first font). Symbols like manicules live only in some
    of the candidates."""
    from fontTools.ttLib import TTFont
    coverage = []
    for path in FAKE_HAND_FONTS:
        if os.path.exists(path):
            coverage.append((path, set(TTFont(path).getBestCmap())))

    def pick(text):
        for path, cps in coverage:
            if all(ord(c) in cps for c in text):
                return path
        return coverage[0][0]
    return pick


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--layout", required=True)
    ap.add_argument("--outdir", default="work/sim")
    ap.add_argument("--rotate", type=float, default=0.7, help="degrees of skew")
    ap.add_argument("--scale", type=float, default=0.85,
                    help="rescale factor, to imitate a different scan DPI")
    args = ap.parse_args()

    with open(args.layout) as f:
        layout = json.load(f)

    pick_font = load_font_picker()
    os.makedirs(args.outdir, exist_ok=True)

    # PIL can't read PDFs, so re-render the page images from the layout code
    images, _ = make_template.render_all(
        layout["paper"], layout["size_mode"], set(layout["sets"]))

    for page in layout["pages"]:
        img = images[page["page"] - 1]
        draw = ImageDraw.Draw(img)
        for cell in page["cells"]:
            x0, y0, x1, y1 = cell["box"]
            # size the fake pen so lowercase roughly matches the x-height zone
            size = int((cell["baseline_y"] - cell["xheight_y"]) * 1.35)
            text = cell["text"]
            if cell["glyph"].endswith(".sc"):  # small caps: small capital forms
                text = text.upper()
                size = int(size * 0.72)
            font = ImageFont.truetype(pick_font(text), size)
            # make the "alternate versions" visibly different by tilting them
            tilt = {"alt1": 8, "alt2": -8}.get(cell["glyph"].rsplit(".", 1)[-1], 0)
            if tilt:
                patch = Image.new("L", (x1 - x0, y1 - y0), 255)
                ImageDraw.Draw(patch).text(
                    ((x1 - x0) * 0.2, cell["baseline_y"] - y0),
                    text, font=font, fill=15, anchor="ls")
                patch = patch.rotate(tilt, resample=Image.BILINEAR, fillcolor=255)
                region = img.crop((x0, y0, x1, y1))
                img.paste(ImageChops.darker(region, patch), (x0, y0))
            else:
                draw.text((x0 + (x1 - x0) * 0.2, cell["baseline_y"]),
                          text, font=font, fill=15, anchor="ls")
        img = img.rotate(args.rotate, resample=Image.BILINEAR, fillcolor=255)
        w, h = img.size
        img = img.resize((int(w * args.scale), int(h * args.scale)), Image.BILINEAR)
        out = os.path.join(args.outdir, f"scan-page{page['page']}.png")
        img.save(out)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
