#!/usr/bin/env python3
"""Generate the how-to sheet(s): example boxes with a model glyph correctly
placed on the guides and a short caption, plus the rules of the
three-boxes-tick-the-keepers system. This is a reference to keep next to you
while writing - it is never scanned (it has no registration marks), and it
also rides along as the first pages of the "english" module PDF.

Usage:
    python3 make_guide.py            # writes templates/filling-guide.pdf
"""

import os

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

from make_template import (BASELINE_FRAC, GUIDE_GRAY, LABEL_GRAY, XHEIGHT_FRAC,
                           DPI, PAPER_SIZES_IN, dashed_hline, load_label_font,
                           px)

MODEL_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# (model text, size factor, caption lines)
VERTICAL_ROW = (
    "UP-DOWN: the solid line is the floor, the dashed line is the body height",
    [
        ("a", 1.0, ["body between", "dashed & solid"]),
        ("h", 1.0, ["ascender", "goes high"]),
        ("g", 1.0, ["tail below", "the solid line"]),
        ("t", 1.0, ["half-ascender", "is fine"]),
        ("A", 1.0, ["CAPITAL: tall,", "on the solid line"]),
        ("A", 0.68, ["SMALL CAP:", "up to the dashed"]),
        ("4", 1.0, ["digits =", "capital height"]),
    ])

DETAIL_ROWS = [
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
        ("„", 1.0, ["low quote: on", "the solid line"]),
        ("?", 1.0, ["full height"]),
        ("€", 1.0, ["like a capital"]),
        ("→", 1.0, ["middle of", "the box"]),
        ("☺", 1.0, ["draw it big,", "centered"]),
    ]),
]

LIGATURE_ROW = ("LIGATURES - write the PAIR as one joined movement, no pen lift if you can",
                [("th", 1.0, ["joined th"]), ("fi", 1.0, ["joined fi"])])

PICK_RULES = [
    "write the character in all THREE boxes - vary naturally, don't trace-copy",
    "then TICK the circle above every version you actually like",
    "1st ticked version  =  the letter in your font (1, 2 or 3 ticks is fine)",
    "2nd & 3rd ticked    =  rotating alternates (repeats won't look cloned)",
    "no tick on a version = it is thrown away - a botched box costs nothing",
    "no tick on ANY of the three = all non-empty boxes get used",
    "keep the tick INSIDE the circle - a stray tick inside the box would",
    "    become part of the letter",
]

HORIZONTAL_RULES = [
    "keep the character roughly centered, with a little air on both sides",
    "exact left-right position does NOT matter - letter spacing is measured",
    "    from the ink itself, not from the box",
    "never touch the gray border: ink on the border gets cut off",
    "width is free: a wide m and a narrow i are both fine",
]

TIPS = [
    "the BIG character above the first box (with its name, e.g.",
    "    \"ě  e + háček\") tells you what the three boxes want",
    "one pen for everything - Light & Bold are computed later",
    "empty boxes = character skipped, that's OK",
    "natural speed beats careful hesitation",
    "print at 100% / actual size - never \"fit to page\"",
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


def render_pages(paper="a4"):
    """Return the guide as a list of page images (portrait)."""
    w_in, h_in = PAPER_SIZES_IN[paper]
    W, H = px(w_in), px(h_in)
    margin = px(0.55)
    pick = load_picker()

    title_font = load_label_font(px(0.19))
    header_font = load_label_font(px(0.135))
    caption_font = load_label_font(px(0.105))
    rule_font = load_label_font(px(0.115))

    bw, bh = px(0.95), px(0.85)
    gap = px(0.11)

    def new_page(title):
        img = Image.new("L", (W, H), 255)
        draw = ImageDraw.Draw(img)
        draw.text((margin, margin - px(0.1)), title, fill=40, font=title_font)
        return img, draw

    def draw_box(draw, x, y, model, factor, captions, wide=False, check=None):
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
        if check is not None:  # ticked / unticked circle above the box
            r = px(0.055)
            ccx, ccy = x + w - r - 8, y - r - 10
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r],
                         outline=GUIDE_GRAY, width=2)
            if check:
                draw.line([(ccx - r * 0.5, ccy), (ccx - r * 0.1, ccy + r * 0.5)],
                          fill=20, width=5)
                draw.line([(ccx - r * 0.1, ccy + r * 0.5), (ccx + r * 0.6, ccy - r * 0.6)],
                          fill=20, width=5)
        for i, cap in enumerate(captions):
            draw.text((x + 4, y + bh + 8 + i * px(0.115)), cap,
                      fill=LABEL_GRAY, font=caption_font)

    def rules_block(draw, x, y, header, rules):
        draw.text((x, y), header, fill=LABEL_GRAY, font=header_font)
        y += px(0.24)
        for rule in rules:
            indent = px(0.22) if rule.startswith("    ") else 0
            bullet = "" if rule.startswith("    ") else "-  "
            draw.text((x + indent, y), bullet + rule.strip(),
                      fill=60, font=rule_font)
            y += px(0.185)
        return y

    # ---- page 1: the system -------------------------------------------------
    img1, draw = new_page("READ ME FIRST - how to fill the sheets  (do not scan this page)")
    y = margin + px(0.35)

    draw.text((margin, y), "EVERY CHARACTER GETS 3 BOXES - TICK THE KEEPERS",
              fill=LABEL_GRAY, font=header_font)
    y += px(0.34)
    demo = [("a", True, ["ticked: becomes", "your letter 'a'"]),
            ("a", False, ["not ticked:", "thrown away"]),
            ("a", True, ["ticked: becomes", "an alternate 'a'"])]
    x = margin
    for model, ticked, captions in demo:
        draw_box(draw, x, y, model, 1.0, captions, check=ticked)
        x += bw + gap
    y_rules = y + px(0.12)
    x_rules = x + px(0.25)
    rules_block(draw, x_rules, y_rules, "THE RULES",
                PICK_RULES[:6])
    y += bh + px(0.55)

    rules_block(draw, margin, y, "TICKING", PICK_RULES[6:])
    y += px(0.24) + 2 * px(0.185) + px(0.28)

    header, cells = VERTICAL_ROW
    draw.text((margin, y), header, fill=LABEL_GRAY, font=header_font)
    y += px(0.24)
    x = margin
    for model, factor, captions in cells:
        draw_box(draw, x, y, model, factor, captions)
        x += bw + gap
    y += bh + px(0.55)

    y = rules_block(draw, margin, y,
                    "LEFT-RIGHT: anywhere in the box is fine",
                    HORIZONTAL_RULES)

    # ---- page 2: the details ------------------------------------------------
    img2, draw = new_page("How to draw the tricky ones  (do not scan this page)")
    y = margin + px(0.35)
    for header, cells in DETAIL_ROWS:
        draw.text((margin, y), header, fill=LABEL_GRAY, font=header_font)
        y += px(0.24)
        x = margin
        for model, factor, captions in cells:
            draw_box(draw, x, y, model, factor, captions)
            x += bw + gap
        y += bh + px(0.55)

    header, cells = LIGATURE_ROW
    draw.text((margin, y), header, fill=LABEL_GRAY, font=header_font)
    y += px(0.24)
    x = margin
    for model, factor, captions in cells:
        draw_box(draw, x, y, model, factor, captions, wide=True)
        x += bw * 2 + gap
    tips_x = x + px(0.15)
    rules_block(draw, tips_x, y, "GOLDEN RULES", TIPS[:4])
    y += bh + px(0.55)

    rules_block(draw, margin, y, "BEFORE YOU START", TIPS[4:])

    return [img1, img2]


def main():
    pages = render_pages("a4")
    outdir = os.path.join(os.path.dirname(__file__), "templates")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "filling-guide.pdf")
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=DPI)
    for i, img in enumerate(pages):
        png = os.path.join(outdir, f"filling-guide-{i + 1}.png")
        img.resize((img.width // 2, img.height // 2)).save(png)
        print(f"wrote {png}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
