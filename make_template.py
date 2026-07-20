#!/usr/bin/env python3
"""Generate a printable handwriting-capture template (PDF) plus a layout JSON.

The template is a grid of boxes, one per glyph. Guides (box borders, baseline,
x-height line) are printed in light gray so they can be removed by
thresholding after scanning; only the four corner registration marks and the
page-ID dots are solid black. Labels sit *above* each box, outside the region
that gets cropped, so they never leak into a glyph.

Two sizes:
    normal   large boxes, easy to fill, good first-time experience
    compact  small boxes (~4.5 mm x-height) for natural-size handwriting;
             print at 100% and scan at 600 DPI

Usage:
    python3 make_template.py                     # all papers & sizes
    python3 make_template.py --paper a4 --size compact
    python3 make_template.py --sets core,czech   # limit the character sets

Outputs (in ./templates/):
    handwriting-template-<paper>[-compact].pdf   print at 100% ("actual size")
    layout-<paper>[-compact].json                needed later by segment.py
"""

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont
from fontTools import agl

DPI = 300
PAPER_SIZES_IN = {"a4": (8.27, 11.69), "letter": (8.5, 11.0)}

# Bumped whenever box positions/ordering change. Printed on every sheet and
# stored in the layout JSON so a scan can be matched to the right layout.
# (Sheets with no version marker are v1.)
LAYOUT_VERSION = 2

# Grayscale values (0 = black). Guides must survive printing but die at the
# binarization threshold used by build_font.py (default 110).
GUIDE_GRAY = 185
LABEL_GRAY = 110  # labels are outside the crop region, so darkness is fine
INK = 0

MARGIN_IN = 0.55   # page margin to the registration-mark centers
MARK_IN = 0.18     # side of the black corner squares
ID_DOT_IN = 0.07   # side of the page-ID squares

# Vertical geometry inside a box (fractions of box height, measured from top):
# top edge = ascender line, bottom edge = descender line.
XHEIGHT_FRAC = 0.40
BASELINE_FRAC = 0.75

SIZE_PARAMS = {
    "normal": {"box_h": 1.25, "label_h": 0.16, "row_gap": 0.10, "col_gap": 0.12,
               "label_font": 0.105, "cols": {"letters": 5, "symbols": 6, "ligatures": 4}},
    "compact": {"box_h": 0.50, "label_h": 0.12, "row_gap": 0.06, "col_gap": 0.08,
                "label_font": 0.08, "cols": {"letters": 9, "symbols": 9, "ligatures": 6}},
    # "book": A4/letter turned landscape, split into a left and a right half
    # that fill like the two pages of an open notebook (left page top-to-
    # bottom first, then the right page). cols are PER HALF; 6 keeps every
    # a/a-v2/a-v3 triple on one row.
    "book": {"box_h": 0.50, "label_h": 0.12, "row_gap": 0.06, "col_gap": 0.08,
             "label_font": 0.08, "cols": {"letters": 6, "symbols": 6, "ligatures": 4},
             "gutter": 0.55},
}


def page_dims(paper, size):
    w_in, h_in = PAPER_SIZES_IN[paper]
    if size == "book":
        w_in, h_in = h_in, w_in  # landscape
    return px(w_in), px(h_in)


def effective_cols(size, kind):
    n = SIZE_PARAMS[size]["cols"][kind]
    return n * 2 if size == "book" else n

PUNCT_NAMES = {
    ".": "period", ",": "comma", ";": "semicolon", ":": "colon",
    "!": "exclam", "?": "question", "'": "apostrophe", '"': "quote",
    "(": "paren-open", ")": "paren-close", "-": "hyphen", "_": "underscore",
    "/": "slash", "@": "at", "#": "hash", "&": "ampersand",
    "%": "percent", "+": "plus", "=": "equals", "*": "asterisk", "$": "dollar",
    "€": "euro", "£": "pound", "¥": "yen", "¢": "cent",
    "<": "less", ">": "greater", "[": "bracket-open", "]": "bracket-close",
    "{": "brace-open", "}": "brace-close", "×": "multiply", "÷": "divide",
    "−": "minus", "±": "plus-minus", "≈": "approx", "≠": "not-equal",
    "≤": "less-eq", "≥": "greater-eq", "~": "tilde", "^": "caret",
    "|": "bar", "\\": "backslash", "°": "degree", "§": "section",
    "…": "ellipsis", "–": "en-dash", "—": "em-dash", "•": "bullet",
    "„": "low quote", "“": "open quote", "”": "close quote",
    "‘": "open single", "’": "close single", "‚": "low single",
    "«": "guillemet <<", "»": "guillemet >>", "‹": "guillemet <", "›": "guillemet >",
    "¡": "inv. exclam", "¿": "inv. question",
    "©": "copyright", "®": "registered", "™": "trademark",
    "←": "arrow left", "→": "arrow right", "↑": "arrow up", "↓": "arrow down",
    "↔": "arrow both",
    "☞": "hand right", "☜": "hand left", "☝": "hand up", "☟": "hand down",
    "☺": "smiley", "☹": "frowny", "♥": "heart", "♡": "white heart",
    "♠": "spade", "♤": "white spade", "♦": "diamond", "♢": "white diamond",
    "♣": "club", "♧": "white club", "★": "star", "☆": "star outline",
    "✓": "check", "✗": "cross", "♪": "note", "☀": "sun", "☾": "moon",
    "✿": "flower", "❦": "fleuron", "❧": "fleuron 2", "⁂": "asterism",
    "⁓": "swung dash", "✎": "pencil", "✂": "scissors",
}

SYMBOLS_EXTRA = ("€£¥¢<>[]{}×÷−±≈≠≤≥~^|\\°§…–—•"
                 "„“”‘’‚«»‹›¡¿©®™←→↑↓↔")
EXTRAS = "☞☜☝☟☺☹♥♡♠♤♦♢♣♧★☆✓✗♪☀☾✿❦❧⁂⁓✎✂"

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = LOWER.upper()
SYMBOLS = "0123456789" + ".,;:!?'\"()-_/@#&%+=*$"
CZECH_LOWER = "áčďéěíňóřšťúůýž"
SLOVAK_LOWER = "äĺľŕô"
POLISH_LOWER = "ąćęłńśźż"
LIGATURES = ["ff", "fi", "fl", "ffi", "ffl", "th", "ch", "sh", "st", "ct",
             "ck", "qu", "tt", "ll", "ss", "ee", "oo", "ft"]


def glyph_name(text, suffix=""):
    base = "_".join(agl.UV2AGL.get(ord(c), f"uni{ord(c):04X}") for c in text)
    return base + suffix


def default_cells(chars):
    cells = []
    for ch in chars:
        label = ch if ch not in PUNCT_NAMES else f"{ch}  ({PUNCT_NAMES[ch]})"
        cells.append({"text": ch, "glyph": glyph_name(ch), "label": label})
    return cells


def grouped_lower_cells():
    """a, a v2, a v3, b, b v2, ... - the three versions of each letter sit
    next to each other so you can see (and steer) the variety while writing."""
    cells = []
    for ch in LOWER:
        cells.append({"text": ch, "glyph": glyph_name(ch), "label": ch})
        for alt_no in (1, 2):
            cells.append({"text": ch, "glyph": glyph_name(ch, f".alt{alt_no}"),
                          "label": f"{ch}  (v{alt_no + 1})"})
    return cells


def smallcap_cells():
    return [{"text": ch, "glyph": glyph_name(ch, ".sc"),
             "label": f"{ch.upper()}  (small cap)"} for ch in LOWER]


SET_KEYS = ["core", "symbols-extra", "czech", "slovak-polish", "alternates",
            "small-caps", "extras", "ligatures", "sample"]

# The writing-sample page: copy each gray model line onto the guides below
# it, at your natural pace. This page is a style reference for tuning
# spacing and rhythm - it is NOT cut into glyphs.
SAMPLE_SECTIONS = [
    ("Sentence case - copy each gray line onto the guides below it", [
        "The quick brown fox jumps over",
        "the lazy dog; my office coffee",
        "was just €2.50 at 7:45 today!",
        "Příliš žluťoučký kůň úpěl",
        "ďábelské ódy, věř mi…",
        "Zażółć gęślą jaźń, Kŕdeľ!",
    ]),
    ("ALL CAPS", [
        "PACK MY BOX WITH FIVE DOZEN",
        "LIQUOR JUGS - QUICKLY!",
        "PŘÍLIŠ ŽLUŤOUČKÝ KŮŇ.",
    ]),
    ("Free writing - anything you like", ["", ""]),
]


def get_sets(set_keys):
    """Build the (kind, short title, note, cells) list for the selected keys."""
    sets = []
    if "core" in set_keys:
        if "alternates" in set_keys:
            sets.append(("letters", "a-z x3",
                         "each letter 3 times: vary it naturally - the three "
                         "versions rotate as you type", grouped_lower_cells()))
        else:
            sets.append(("letters", "a-z", "", default_cells(LOWER)))
        sets.append(("letters", "A-Z", "", default_cells(UPPER)))
    if "small-caps" in set_keys:
        sets.append(("letters", "SMALL CAPS",
                     "write CAPITAL letterforms but small - about dashed-line "
                     "height, sitting on the solid line", smallcap_cells()))
    if "czech" in set_keys:
        sets.append(("letters", "Czech", "",
                     default_cells(CZECH_LOWER + CZECH_LOWER.upper())))
    if "slovak-polish" in set_keys:
        sets.append(("letters", "Slovak & Polish", "",
                     default_cells(SLOVAK_LOWER + SLOVAK_LOWER.upper()
                                   + POLISH_LOWER + POLISH_LOWER.upper())))
    if "core" in set_keys:
        sets.append(("symbols", "0-9 & punctuation", "", default_cells(SYMBOLS)))
    if "symbols-extra" in set_keys:
        sets.append(("symbols", "symbols & arrows", "", default_cells(SYMBOLS_EXTRA)))
    if "extras" in set_keys:
        sets.append(("symbols", "fun extras",
                     "hands, smileys, cards, flourishes - totally optional, "
                     "skip any you don't want", default_cells(EXTRAS)))
    if "ligatures" in set_keys:
        sets.append(("ligatures", "ligatures",
                     "write the letter pair JOINED, the way you naturally "
                     "connect those letters",
                     [{"text": lig, "glyph": glyph_name(lig), "label": lig}
                      for lig in LIGATURES]))
    return sets


def px(inches):
    return int(round(inches * DPI))


def load_label_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def dashed_hline(draw, x0, x1, y, color, dash=14, gap=10, width=2):
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=width)
        x += dash + gap


GRID_TOP_IN = 0.60  # room under the marks for a title line plus a note line


def compose_pages(paper, size, set_keys):
    """Flow the selected sets into pages. Consecutive sets that share a
    column count are packed onto the same pages so the compact template
    doesn't waste paper on sparse pages."""
    P = SIZE_PARAMS[size]
    H = page_dims(paper, size)[1]
    margin, mark = px(MARGIN_IN), px(MARK_IN)
    grid_y0 = margin + px(GRID_TOP_IN)
    grid_y1 = H - margin - mark
    row_h = px(P["box_h"]) + px(P["label_h"]) + px(P["row_gap"])
    rows_per_page = max(1, (grid_y1 - grid_y0) // row_h)

    # group consecutive sets by their column count
    groups = []
    for kind, short, note, cells in get_sets(set_keys):
        cols = effective_cols(size, kind)
        tagged = [(short, note, c) for c in cells]
        if groups and groups[-1][0] == cols:
            groups[-1][1].extend(tagged)
        else:
            groups.append((cols, tagged))

    pages = []
    for cols, tagged in groups:
        per_page = cols * rows_per_page
        chunks = [tagged[i:i + per_page] for i in range(0, len(tagged), per_page)]
        for i, chunk in enumerate(chunks):
            shorts = list(dict.fromkeys(t[0] for t in chunk))
            notes = [n for n in dict.fromkeys(t[1] for t in chunk) if n]
            suffix = f"  ({i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            pages.append({"title": " + ".join(shorts) + suffix,
                          "notes": notes, "cols": cols,
                          "cells": [t[2] for t in chunk]})
    if "sample" in set_keys:
        pages.append({"title": "writing sample - your natural rhythm",
                      "notes": ["copy the gray lines at your natural pace; "
                                "this page tunes spacing, it is not cut into "
                                "letters"],
                      "sample": True, "cols": 0, "cells": []})
    return pages


def render_page(paper, size, page_def, page_index, total_pages):
    P = SIZE_PARAMS[size]
    W, H = page_dims(paper, size)
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)

    margin, mark = px(MARGIN_IN), px(MARK_IN)
    marks = [(margin, margin), (W - margin, margin),
             (margin, H - margin), (W - margin, H - margin)]
    for cx, cy in marks:
        draw.rectangle([cx - mark // 2, cy - mark // 2,
                        cx + mark // 2, cy + mark // 2], fill=INK)

    dot = px(ID_DOT_IN)
    all_dot_slots = [(margin + mark + px(0.12) + i * px(0.16), margin)
                     for i in range(total_pages)]
    for cx, cy in all_dot_slots[:page_index + 1]:
        draw.rectangle([cx - dot // 2, cy - dot // 2,
                        cx + dot // 2, cy + dot // 2], fill=INK)

    label_font = load_label_font(px(P["label_font"]))
    title_font = load_label_font(px(0.13))
    draw.text((margin + mark, margin + px(0.06)),
              f"Page {page_index + 1} - {page_def['title']}",
              fill=LABEL_GRAY, font=title_font)
    for i, note in enumerate(page_def.get("notes", [])):
        draw.text((margin + mark, margin + px(0.26) + i * px(0.14)), note,
                  fill=LABEL_GRAY, font=label_font)
    tip = "black pen · letters sit on the SOLID line · lowercase body reaches the DASHED line"
    if size in ("compact", "book"):
        tip += " · scan at 600 DPI"
    if size == "book":
        tip += " · keep the sheet FLAT for scanning, never fold it"
    draw.text((margin - mark // 2, H - margin + mark), tip,
              fill=LABEL_GRAY, font=label_font)
    draw.text((W - margin - px(0.55), H - margin + mark),
              f"template v{LAYOUT_VERSION}", fill=LABEL_GRAY, font=label_font)

    grid_x0 = margin - mark // 2
    grid_x1 = W - margin + mark // 2
    grid_y0 = margin + px(GRID_TOP_IN)

    if page_def.get("sample"):
        render_sample_blocks(draw, size, grid_x0, grid_x1, grid_y0,
                             H - margin - mark, label_font, title_font)
        return img, {
            "page": page_index + 1,
            "size": [W, H],
            "reg_marks": marks,
            "mark_px": mark,
            "id_dot_slots": all_dot_slots,
            "id_dot_px": dot,
            "sample": True,
            "cells": [],
        }

    cols = page_def["cols"]
    col_gap, row_gap = px(P["col_gap"]), px(P["row_gap"])
    label_h, bh = px(P["label_h"]), px(P["box_h"])
    gutter = px(P.get("gutter", 0))
    half_cols = cols // 2 if gutter else cols
    bw = (grid_x1 - grid_x0 - gutter - (cols - 1) * col_gap) // cols

    if gutter:  # book spread: dashed "spine" down the middle of the sheet
        cx = (grid_x0 + grid_x1) // 2
        y = grid_y0
        while y < H - margin:
            draw.line([(cx, y), (cx, min(y + 18, H - margin))],
                      fill=GUIDE_GRAY, width=2)
            y += 30

    # Fill order: a normal page goes row by row; a book spread fills the
    # LEFT page top-to-bottom first, then the RIGHT page - like a real book.
    row_h = bh + label_h + row_gap
    rows = max(1, (H - margin - mark - grid_y0) // row_h)  # = compose_pages
    cells = []
    for i, spec in enumerate(page_def["cells"]):
        if gutter:
            half, j = divmod(i, half_cols * rows)
            r, c = divmod(j, half_cols)
            x0 = (grid_x0 + (c + half * half_cols) * (bw + col_gap)
                  + (gutter - col_gap if half else 0))
        else:
            r, c = divmod(i, cols)
            x0 = grid_x0 + c * (bw + col_gap)
        y0 = grid_y0 + r * row_h + label_h
        x1, y1 = x0 + bw, y0 + bh

        draw.text((x0 + 4, y0 - label_h + 2), spec["label"],
                  fill=LABEL_GRAY, font=label_font)
        draw.rectangle([x0, y0, x1, y1], outline=GUIDE_GRAY, width=2)
        baseline_y = y0 + int(bh * BASELINE_FRAC)
        xheight_y = y0 + int(bh * XHEIGHT_FRAC)
        draw.line([(x0, baseline_y), (x1, baseline_y)], fill=GUIDE_GRAY, width=2)
        dashed_hline(draw, x0, x1, xheight_y, GUIDE_GRAY,
                     dash=10 if size == "compact" else 14,
                     gap=8 if size == "compact" else 10)

        cells.append({
            "text": spec["text"],
            "glyph": spec["glyph"],
            "box": [x0, y0, x1, y1],
            "baseline_y": baseline_y,
            "xheight_y": xheight_y,
        })

    page_layout = {
        "page": page_index + 1,
        "size": [W, H],
        "reg_marks": marks,
        "mark_px": mark,
        "id_dot_slots": all_dot_slots,
        "id_dot_px": dot,
        "cells": cells,
    }
    return img, page_layout


def render_sample_blocks(draw, size, x0, x1, y0, y1, label_font, title_font):
    """Ruled model-line / writing-line pairs for the writing-sample page."""
    model_h, zone_h, gap = px(0.16), px(0.50), px(0.08)
    header_h = px(0.22)
    if size == "book":  # two half-page columns, like the rest of the book form
        gutter = px(SIZE_PARAMS["book"]["gutter"])
        mid = (x0 + x1) // 2
        columns = [(x0, mid - gutter // 2), (mid + gutter // 2, x1)]
        col_sections = [SAMPLE_SECTIONS[:1], SAMPLE_SECTIONS[1:]]
    else:
        columns = [(x0, x1)]
        col_sections = [SAMPLE_SECTIONS]

    for (cx0, cx1), sections in zip(columns, col_sections):
        y = y0
        for header, lines in sections:
            draw.text((cx0, y), header, fill=LABEL_GRAY, font=title_font)
            y += header_h
            for model in lines:
                if model:
                    draw.text((cx0, y), model, fill=LABEL_GRAY, font=label_font)
                baseline_y = y + model_h + int(zone_h * BASELINE_FRAC)
                xheight_y = y + model_h + int(zone_h * XHEIGHT_FRAC)
                draw.line([(cx0, baseline_y), (cx1, baseline_y)],
                          fill=GUIDE_GRAY, width=2)
                dashed_hline(draw, cx0, cx1, xheight_y, GUIDE_GRAY)
                y += model_h + zone_h + gap


def render_all(paper, size, set_keys):
    """Render every page; returns (images, layout_dict)."""
    page_defs = compose_pages(paper, size, set_keys)
    images, pages = [], []
    for i, page_def in enumerate(page_defs):
        img, layout = render_page(paper, size, page_def, i, len(page_defs))
        images.append(img)
        pages.append(layout)
    layout = {
        "version": LAYOUT_VERSION,
        "dpi": DPI,
        "paper": paper,
        "size_mode": size,
        "sets": sorted(set_keys),
        "guide_gray": GUIDE_GRAY,
        "baseline_frac": BASELINE_FRAC,
        "xheight_frac": XHEIGHT_FRAC,
        "pages": pages,
    }
    return images, layout


def build(paper, size, set_keys, outdir):
    images, layout = render_all(paper, size, set_keys)
    os.makedirs(outdir, exist_ok=True)
    stem = paper if size == "normal" else f"{paper}-{size}"
    pdf_path = os.path.join(outdir, f"handwriting-template-{stem}.pdf")
    images[0].save(pdf_path, save_all=True, append_images=images[1:], resolution=DPI)
    json_path = os.path.join(outdir, f"layout-{stem}.json")
    with open(json_path, "w") as f:
        json.dump(layout, f, indent=1)
    print(f"wrote {pdf_path}  ({len(images)} pages)")
    print(f"wrote {json_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--paper", choices=["a4", "letter", "both"], default="both")
    ap.add_argument("--size", choices=["normal", "compact", "book", "all"], default="all")
    ap.add_argument("--sets", default=",".join(SET_KEYS),
                    help=f"comma-separated subset of: {', '.join(SET_KEYS)}")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "templates"))
    args = ap.parse_args()
    set_keys = {s.strip() for s in args.sets.split(",") if s.strip()}
    unknown = set_keys - set(SET_KEYS)
    if unknown:
        ap.error(f"unknown sets: {', '.join(sorted(unknown))}")
    papers = ["a4", "letter"] if args.paper == "both" else [args.paper]
    sizes = ["normal", "compact", "book"] if args.size == "all" else [args.size]
    for paper in papers:
        for size in sizes:
            build(paper, size, set_keys, args.outdir)


if __name__ == "__main__":
    main()
