#!/usr/bin/env python3
"""Render a PNG specimen of a (variable) font so you can eyeball the result.

Usage:
    python3 proof.py --font work/MyHandVF.ttf --out work/proof.png
"""

import argparse

from PIL import Image, ImageDraw, ImageFont, features

SAMPLES = [
    "The quick brown fox jumps over the lazy dog!",
    "Pack my box with five dozen liquor jugs? (0123456789)",
    "fluffy official waffles; the quill sassy bookkeeper",
    "Příliš žluťoučký kůň úpěl ďábelské ódy.",
    "Kŕdeľ vtákov - zażółć gęślą jaźń, łódź",
    "5 × 4 ≠ €19; „ahoj“ → ☞ ✓ ♥ ☺ ❦ 100 °",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--font", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=56)
    args = ap.parse_args()

    # RAQM layout applies OpenType features (liga ligatures, calt alternates)
    layout = (ImageFont.Layout.RAQM if features.check("raqm")
              else ImageFont.Layout.BASIC)
    probe = ImageFont.truetype(args.font, args.size, layout_engine=layout)
    try:
        axes = probe.get_variation_axes()
    except OSError:
        axes = []
    weights = [300, 400, 550, 700] if axes else [None]

    line_h = int(args.size * 1.6)
    width = 1900
    height = 40 + len(weights) * (len(SAMPLES) + 1) * line_h
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    label_font = ImageFont.load_default(24)

    y = 30
    for w in weights:
        font = ImageFont.truetype(args.font, args.size, layout_engine=layout)
        if w is not None:
            font.set_variation_by_axes([w])
            draw.text((40, y), f"wght = {w}", font=label_font, fill=140)
        y += int(line_h * 0.7)
        for line in SAMPLES:
            draw.text((40, y), line, font=font, fill=0)
            y += line_h
        y += int(line_h * 0.3)

    img.save(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
