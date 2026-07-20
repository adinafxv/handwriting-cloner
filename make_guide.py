#!/usr/bin/env python3
"""Generate the box-filling guide: one example box per kind of character,
with a model glyph correctly placed on the guides and a short caption.
This is a reference sheet to keep next to you while writing - it is never
scanned.

Usage:
    python3 make_guide.py            # writes templates/filling-guide.pdf
"""

import os

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

from make_template import (BASELINE_FRAC, GUIDE_GRAY, LABEL_GRAY, XHEIGHT_FRAC,
                           DPI, dashed_hline, load_label_font, px)

MODEL_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# (model text, size factor, caption lines)
ROWS = [
    ("LETTERS - the solid line is the floor, the dashed line is the body height", [
        ("a", 1.0, ["body between", "dashed & solid"]),
        ("h", 1.0, ["ascender", "goes high"]),
        ("g", 1.0, ["tail below", "the solid line"]),
        ("t", 1.0, ["half-ascender", "is fine"]),
        ("A", 1.0, ["CAPITAL: tall,", "on the solid line"]),
        ("A", 0.68, ["SMALL CAP:", "up to the dashed"]),
        ("4", 1.0, ["digits =", "capital height"]),
    ]),
    ("DIACRITICS - accents live above the body; they may go higher than the dashed line", [
        ("č", 1.0, ["haček above", "the body"]),
        ("ď", 1.0, ["caron beside", "the stem"]),
        ("í", 1.0, ["accent replaces", "the dot"]),
        ("ů", 1.0, ["ring on top"]),
        ("Ě", 1.0, ["capital + accent:", "squeeze up top"]),
        ("ą", 1.0, ["ogonek hangs", "below the line"]),
        ("ł", 1.0, ["stroke through", "the stem"]),
    ]),
    ("PUNCTUATION & SYMBOLS - draw them where they sit when you write a sentence", [
        (",", 1.0, ["on the solid,", "tail below"]),
        ("“", 1.0, ["quotes float", "up high"]),
        ("„", 1.0, ["Czech low quote:", "on the solid line"]),
        ("?", 1.0, ["full height"]),
        ("€", 1.0, ["like a capital"]),
        ("→", 1.0, ["middle of", "the box"]),
        ("☺", 1.0, ["draw it big,", "centered"]),
    ]),
]

LIGATURE_ROW = ("LIGATURES - write the PAIR as one joined movement, no pen lift if you can",
                [("th", 1.0, ["joined th"]), ("fi", 1.0, ["joined fi"])])

TIPS = [
    "check the label above EVERY box",
    "stay inside the box, off the gray border",
    "one pen only - Light & Bold are computed",
    "empty box = character skipped, that's OK",
    "natural speed beats careful hesitation",
]


def load_picker():
    coverage = []
    for path in MODEL_FONTS:
        if os.path.exists(path):
            coverage.append((path, set(TTFont(path).getBestCmap())))

    def pick(text):
        for path, cps in coverage:
            if all(ord(c) in cps for c in text):
                return path
        return coverage[0][0]
    return pick


def main():
    W, H = px(8.27), px(11.69)
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)
    margin = px(0.55)
    pick = load_picker()

    title_font = load_label_font(px(0.16))
    header_font = load_label_font(px(0.115))
    caption_font = load_label_font(px(0.095))

    draw.text((margin, margin - px(0.1)),
              "How to fill the boxes - keep this next to you (do not scan this page)",
              fill=60, font=title_font)

    bw, bh = px(0.95), px(0.85)
    gap = px(0.11)
    y = margin + px(0.35)

    def draw_box(x, y, model, factor, captions, wide=False):
        w = bw * 2 if wide else bw
        draw.rectangle([x, y, x + w, y + bh], outline=GUIDE_GRAY, width=2)
        baseline_y = y + int(bh * BASELINE_FRAC)
        xheight_y = y + int(bh * XHEIGHT_FRAC)
        draw.line([(x, baseline_y), (x + w, baseline_y)], fill=GUIDE_GRAY, width=3)
        dashed_hline(draw, x, x + w, xheight_y, GUIDE_GRAY)
        # size the model so its x-height matches the dashed->solid zone,
        # then anchor it on the baseline: the font's own metrics place
        # ascenders, tails, accents and symbols exactly where they belong
        zone = baseline_y - xheight_y
        size = int(zone * 1.9 * factor)
        font = ImageFont.truetype(pick(model), size)
        draw.text((x + w * (0.30 if not wide else 0.32), baseline_y),
                  model, font=font, fill=30, anchor="ls")
        for i, cap in enumerate(captions):
            draw.text((x + 4, y + bh + 6 + i * px(0.105)), cap,
                      fill=LABEL_GRAY, font=caption_font)

    for header, cells in ROWS:
        draw.text((margin, y), header, fill=LABEL_GRAY, font=header_font)
        y += px(0.20)
        x = margin
        for model, factor, captions in cells:
            draw_box(x, y, model, factor, captions)
            x += bw + gap
        y += bh + px(0.40)

    header, cells = LIGATURE_ROW
    draw.text((margin, y), header, fill=LABEL_GRAY, font=header_font)
    y += px(0.20)
    x = margin
    for model, factor, captions in cells:
        draw_box(x, y, model, factor, captions, wide=True)
        x += bw * 2 + gap
    tips_x = x + px(0.15)
    draw.text((tips_x, y), "GOLDEN RULES", fill=LABEL_GRAY, font=header_font)
    for i, tip in enumerate(TIPS):
        draw.text((tips_x, y + px(0.22) + i * px(0.16)), "-  " + tip,
                  fill=LABEL_GRAY, font=caption_font)
    y += bh + px(0.45)

    outdir = os.path.join(os.path.dirname(__file__), "templates")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "filling-guide.pdf")
    img.save(out, resolution=DPI)
    png = os.path.join(outdir, "filling-guide.png")
    img.resize((img.width // 2, img.height // 2)).save(png)
    print(f"wrote {out}")
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
