#!/usr/bin/env python3
"""Generate printable handwriting-capture sheets (PDF) plus layout JSONs.

The sheets are organized as self-contained MODULES, grouped into three
tiers (see MODULES_BASE / MODULES_LANGUAGES / MODULES_EXTRAS below) so you
only print what you want:

    base       english - a-z, A-Z, digits and every symbol on a normal
               (Mac/US) keyboard, plus the writing-sample page and the
               how-to guide as the first pages
    languages  one diacritic/alphabet add-on per language (Czech, Slovak,
               Polish, Greek, Cyrillic languages, and Latin-diacritic
               languages from French to Esperanto - see LANGUAGE_SETS).
               Every module is complete on its own, so e.g. "english +
               slovak but not polish" just works; uppercase is derived
               automatically via with_upper() (handles ß, dotless i,
               final sigma, etc. - see its docstring)
    extras     symbols (typographic extras + math signs), fun (optional
               extras), ligatures (joined letter pairs), small-caps

Every character appears in THREE boxes in a row, each with a small circle
above it. Write the character three times, then FILL IN the circle above
every version you actually like:

    - the first filled-in version becomes the character in the font,
    - further filled-in versions become rotating alternates (so repeated
      letters don't look cloned),
    - versions left unfilled are thrown away - a bad box costs nothing,
    - if you fill in nothing for a character, all non-empty boxes are used.

Guides (box borders, baseline, x-height line, fill circles) are printed in
light gray so they can be removed by thresholding after scanning; only the
four corner registration marks and the page-ID dots are solid black. The
character to write is printed BIG at the start of each triple, above and
outside the region that gets cropped.

Letter boxes are narrow (portrait: taller than wide) so a single letter
isn't lost in a wide box and there's little horizontal slack to fight when
placing it; symbol boxes stay wider for glyphs that need the room.

Two sizes:
    normal   large boxes, easy to fill, good first-time experience
    book     landscape, split like an open notebook, natural-size boxes
             (~4.5 mm x-height); print at 100% and scan at 600 DPI

Usage:
    python3 make_template.py                          # all modules & papers
    python3 make_template.py --modules english,czech --paper a4 --size book

Outputs (in ./templates/):
    handwriting-<module>-<paper>-<size>.pdf    print at 100% ("actual size")
    layout-<module>-<paper>-<size>.json        needed later by segment.py
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
# (v3 introduced modules + the three-boxes-with-tick-circles system.
#  v4 narrowed the letter/symbol boxes and switched tick -> fill-in-solid.
#  v5 dropped the per-box description text (just the big character now),
#  narrowed the LETTER boxes further to a portrait shape (taller than wide,
#  so there's little horizontal slack to fight), and pulled the fill circle
#  back down snug against the box.
#  v6 restored real clearance between the fill circle and the box - a filled
#  circle was bleeding into the cropped cell and showing up as a speck over
#  the letter.
#  v7 narrowed ligature boxes to ~2x a letter box.
#  v8 added Celsius/Fahrenheit signs to the symbols module.
#  v9 merged the math signs (plus superscripts/root/infinity/empty-set/pi/
#  sum) into the symbols sheet.)
LAYOUT_VERSION = 9

# Grayscale values (0 = black). Guides must survive printing but die at the
# binarization threshold used by build_font.py (default 110).
GUIDE_GRAY = 185
LABEL_GRAY = 100  # labels are outside the crop region, so darkness is fine
INK = 0

MARGIN_IN = 0.55   # page margin to the registration-mark centers
MARK_IN = 0.18     # side of the black corner squares
ID_DOT_IN = 0.07   # side of the page-ID squares

# Vertical geometry inside a box (fractions of box height, measured from top):
# top edge = ascender line, bottom edge = descender line.
XHEIGHT_FRAC = 0.40
BASELINE_FRAC = 0.75

# Every character gets this many boxes; fill in the circle above the keepers.
CANDIDATES = 3

# cols must be a multiple of CANDIDATES so a triple never wraps mid-row.
# cols must be a multiple of CANDIDATES so a triple never wraps mid-row.
# LETTER boxes are deliberately narrow (portrait: taller than wide) - a single
# letter is a small fraction of a square box, and all that horizontal slack
# just makes it harder to place the letter consistently. SYMBOL boxes stay
# wider because some glyphs (em dash, arrows, guillemets) genuinely need it.
SIZE_PARAMS = {
    "normal": {"box_h": 1.05, "label_h": 0.28, "row_gap": 0.10, "col_gap": 0.10,
               "label_font": 0.11, "char_font": 0.17, "check_r": 0.06,
               "cols": {"letters": 9, "symbols": 6, "ligatures": 6}},
    # "book": A4/letter turned landscape, split into a left and a right half
    # that fill like the two pages of an open notebook (left page top-to-
    # bottom first, then the right page). cols are PER HALF. Letters use
    # 12/half (4 triples per half-row) => ~portrait boxes (w/h ~0.8); symbols
    # stay at 9/half so the wide typographic glyphs still fit.
    "book": {"box_h": 0.50, "label_h": 0.22, "row_gap": 0.06, "col_gap": 0.03,
             "label_font": 0.085, "char_font": 0.13, "check_r": 0.05,
             "cols": {"letters": 12, "symbols": 9, "ligatures": 6},
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

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = LOWER.upper()
DIGITS = "0123456789"
# Everything typeable on a plain Mac/US keyboard (minus letters and space).
MAC_PUNCT = ".,;:!?'\"()-_/@#&%+=*$`~^[]{}\\|<>"


def with_upper(chars):
    """De-duplicate chars (preserving order), then append each character's
    uppercase - but ONLY when that uppercase is exactly one character and
    isn't already present. Plain `chars + chars.upper()` breaks on:
      - chars whose .upper() is multiple characters, e.g. German 'ss' <-
        'ß'.upper() == 'SS' (would create a broken 2-char cell/glyph),
        or Greek 'ΐ'/'ΰ', which have no single-codepoint uppercase at all,
      - chars that map to an uppercase already produced by another
        character, e.g. Greek final sigma 'ς'.upper() == 'Σ', the same as
        regular sigma 'σ'.upper() - would duplicate a cell/glyph name.
    Order is preserved: every lowercase first, then every derived
    uppercase, both in first-seen order."""
    seen = []
    for c in chars:
        if c not in seen:
            seen.append(c)
    result = list(seen)
    for c in seen:
        u = c.upper()
        if len(u) == 1 and u not in result:
            result.append(u)
    return "".join(result)


CZECH = "áčďéěíňóřšťúůýž"
SLOVAK = "áäčďéíĺľňóôŕšťúýž"   # complete on its own; overlaps Czech on purpose
POLISH = "ąćęłńóśźż"

# Greek and Cyrillic-script languages.
GREEK = "αβγδεζηθικλμνξοπρστυφχψωςάέήίόύώϊϋΐΰ"
UKRAINIAN = "абвгдеєжзиіїйклмнопрстуфхцчшщьюяґ"
RUSSIAN = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
BULGARIAN = "абвгдежзийклмнопрстуфхцчшщъьюя"
SERBIAN = "абвгдђежзијклљмнњопрстћуфхцчџш"  # Cyrillic

# Latin-script languages: just the letters/diacritics beyond plain a-z
# (already covered by `english`), each module complete on its own.
GERMAN = "äöüß"
FRENCH = "àâçéèêëîïôùûüÿœæ"
SPANISH = "áéíóúüñ¡¿"
PORTUGUESE = "áâãàçéêíóôõú"
ITALIAN = "àèéìíòóù"
HUNGARIAN = "áéíóöőúüű"
ROMANIAN = "ăâîșț"
TURKISH = "çğıöşü"
DUTCH = "ëïéèáíóú"
CROATIAN = "čćđšž"
SLOVENIAN = "čšž"
LITHUANIAN = "ąčęėįšųūž"
LATVIAN = "āčēģīķļņšūž"
ESTONIAN = "šžõäöü"
DANISH_NORWEGIAN = "æøå"
SWEDISH = "åäö"
FINNISH = "äöå"
ICELANDIC = "áðéíóúýþæö"
WELSH = "âêîôûŵŷ"
ESPERANTO = "ĉĝĥĵŝŭ"

# module key -> (display title, characters). Order here is the print/browse
# order: Czech/Slovak/Polish (the original three), then Greek + Cyrillic,
# then Latin-diacritic languages roughly Western -> Northern -> Central/
# Eastern Europe, plus Welsh and Esperanto at the end.
LANGUAGE_SETS = {
    "czech": ("Czech", CZECH),
    "slovak": ("Slovak", SLOVAK),
    "polish": ("Polish", POLISH),
    "greek": ("Greek", GREEK),
    "ukrainian": ("Ukrainian", UKRAINIAN),
    "russian": ("Russian", RUSSIAN),
    "bulgarian": ("Bulgarian", BULGARIAN),
    "serbian": ("Serbian", SERBIAN),
    "german": ("German", GERMAN),
    "french": ("French", FRENCH),
    "spanish": ("Spanish", SPANISH),
    "portuguese": ("Portuguese", PORTUGUESE),
    "italian": ("Italian", ITALIAN),
    "hungarian": ("Hungarian", HUNGARIAN),
    "romanian": ("Romanian", ROMANIAN),
    "turkish": ("Turkish", TURKISH),
    "dutch": ("Dutch", DUTCH),
    "croatian": ("Croatian", CROATIAN),
    "slovenian": ("Slovenian", SLOVENIAN),
    "lithuanian": ("Lithuanian", LITHUANIAN),
    "latvian": ("Latvian", LATVIAN),
    "estonian": ("Estonian", ESTONIAN),
    "danish-norwegian": ("Danish/Norwegian", DANISH_NORWEGIAN),
    "swedish": ("Swedish", SWEDISH),
    "finnish": ("Finnish", FINNISH),
    "icelandic": ("Icelandic", ICELANDIC),
    "welsh": ("Welsh", WELSH),
    "esperanto": ("Esperanto", ESPERANTO),
}
# Vietnamese is deliberately not included: its alphabet needs 130+
# precomposed base+tone-mark characters, which doesn't fit this module's
# one-page-ish add-on shape - it would need a bespoke multi-page treatment.

SYMBOLS_TYPO = "„“”‘’‚«»‹›–—…•°℃℉§¡¿€£¥¢©®™"
MATH = "×÷−±≈≠≤≥²³√∞∅π∑"
FUN = "←→↑↓↔☞☜☝☟☺☹♥♡♠♤♦♢♣♧★☆✓✗♪☀☾✿❦❧⁂⁓✎✂"
LIGATURES = ["ff", "fi", "fl", "ffi", "ffl", "th", "ch", "sh", "st", "ct",
             "ck", "qu", "tt", "ll", "ss", "ee", "oo", "ft"]

PICK_NOTE = ("write each character 3x, then FILL IN the circle above every "
             "version you like - versions left unfilled are discarded")


def glyph_name(text, suffix=""):
    base = "_".join(agl.UV2AGL.get(ord(c), f"uni{ord(c):04X}") for c in text)
    return base + suffix


def candidate_cells(texts, suffix=""):
    """Three boxes per character. The big character label is drawn once, over
    the first box of the triple; the other two boxes carry only their circle."""
    cells = []
    for text in texts:
        base = glyph_name(text, suffix)
        for cand in range(1, CANDIDATES + 1):
            cells.append({
                "text": text, "base": base, "cand": cand,
                "glyph": f"{base}.cand{cand}",
                "label": text if cand == 1 else "",
            })
    return cells


def smallcap_cells():
    cells = candidate_cells(LOWER, suffix=".sc")
    for c in cells:
        c["label"] = c["text"].upper() if c["label"] else ""
    return cells


# Three tiers, concatenated into the one flat MODULES list everything else
# uses (--modules, argparse help, etc.) - existing module names/order for
# english/czech/slovak/polish/symbols/math/fun/ligatures/small-caps are
# unchanged, languages are just inserted between base and extras.
MODULES_BASE = ["english"]
MODULES_LANGUAGES = list(LANGUAGE_SETS.keys())
MODULES_EXTRAS = ["symbols", "fun", "ligatures", "small-caps"]
MODULES = MODULES_BASE + MODULES_LANGUAGES + MODULES_EXTRAS

# The writing-sample page: copy each gray model line onto the guides below
# it, at your natural pace. This page is a style reference for tuning
# spacing and rhythm - it is NOT cut into glyphs.
SAMPLE_SECTIONS = [
    ("Sentence case - copy each gray line onto the guides below it", [
        "The quick brown fox jumps over",
        "the lazy dog; my office coffee",
        "was just $2.50 at 7:45 today!",
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


def get_sets(module):
    """Build the (kind, short title, note, cells) list for one module."""
    if module == "english":
        return [
            ("letters", "a-z", PICK_NOTE, candidate_cells(LOWER)),
            ("letters", "A-Z", "", candidate_cells(UPPER)),
            ("symbols", "0-9 & keyboard symbols", "",
             candidate_cells(DIGITS + MAC_PUNCT)),
        ]
    if module in LANGUAGE_SETS:
        title, chars = LANGUAGE_SETS[module]
        return [("letters", title, PICK_NOTE,
                 candidate_cells(with_upper(chars)))]
    if module == "symbols":
        return [("symbols", "typographic symbols", PICK_NOTE,
                 candidate_cells(SYMBOLS_TYPO)),
                ("symbols", "math symbols", PICK_NOTE, candidate_cells(MATH))]
    if module == "fun":
        return [("symbols", "arrows & fun extras",
                 PICK_NOTE + " - all of these are optional",
                 candidate_cells(FUN))]
    if module == "ligatures":
        return [("ligatures", "ligatures",
                 "write the letter pair JOINED, the way you naturally "
                 "connect those letters - " + PICK_NOTE,
                 candidate_cells(LIGATURES))]
    if module == "small-caps":
        return [("letters", "SMALL CAPS",
                 "write CAPITAL letterforms but small - about dashed-line "
                 "height, sitting on the solid line - " + PICK_NOTE,
                 smallcap_cells())]
    raise ValueError(f"unknown module: {module}")


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


def compose_pages(paper, size, module):
    """Flow the module's sets into pages. Consecutive sets that share a
    column count are packed onto the same pages so the template doesn't
    waste paper on sparse pages."""
    P = SIZE_PARAMS[size]
    H = page_dims(paper, size)[1]
    margin, mark = px(MARGIN_IN), px(MARK_IN)
    grid_y0 = margin + px(GRID_TOP_IN)
    grid_y1 = H - margin - mark
    row_h = px(P["box_h"]) + px(P["label_h"]) + px(P["row_gap"])
    rows_per_page = max(1, (grid_y1 - grid_y0) // row_h)

    # group consecutive sets by their column count
    groups = []
    for kind, short, note, cells in get_sets(module):
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
    if module == "english":
        pages.append({"title": "writing sample - your natural rhythm",
                      "notes": ["copy the gray lines at your natural pace; "
                                "this page tunes spacing, it is not cut into "
                                "letters"],
                      "sample": True, "cols": 0, "cells": []})
    return pages


def render_page(paper, size, module, page_def, page_index, total_pages):
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
    char_font = load_label_font(px(P["char_font"]))
    title_font = load_label_font(px(0.13))
    draw.text((margin + mark, margin + px(0.06)),
              f"{module} - page {page_index + 1} - {page_def['title']}",
              fill=LABEL_GRAY, font=title_font)
    for i, note in enumerate(page_def.get("notes", [])):
        draw.text((margin + mark, margin + px(0.26) + i * px(0.14)), note,
                  fill=LABEL_GRAY, font=label_font)
    tip = ("black pen · sit letters on the SOLID line, body up to the DASHED"
           " line · fill the circle above the versions you keep")
    if size == "book":
        tip += " · scan at 600 DPI, sheet FLAT, never folded"
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
    check_r = px(P["check_r"])
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

        # Compact label strip: the fill-in circle sits just above the box at
        # its top-right corner; the big character label goes at the top-left of
        # the first box of the triple only. No description text, so the circle
        # and the char never fight for space and the strip stays short.
        ccx = x1 - check_r - px(0.02)
        # Keep real clearance above the box: a solidly filled circle plus a
        # few pixels of scan skew must never reach into the cropped cell, or
        # it lands in the glyph as a speck floating over the letter.
        ccy = y0 - check_r - px(0.08)
        draw.ellipse([ccx - check_r, ccy - check_r,
                      ccx + check_r, ccy + check_r],
                     outline=GUIDE_GRAY, width=2)

        if spec.get("label"):
            draw.text((x0 + 2, y0 - px(0.03)), spec["label"],
                      fill=LABEL_GRAY, font=char_font, anchor="ls")

        draw.rectangle([x0, y0, x1, y1], outline=GUIDE_GRAY, width=2)
        baseline_y = y0 + int(bh * BASELINE_FRAC)
        xheight_y = y0 + int(bh * XHEIGHT_FRAC)
        draw.line([(x0, baseline_y), (x1, baseline_y)], fill=GUIDE_GRAY, width=2)
        dashed_hline(draw, x0, x1, xheight_y, GUIDE_GRAY,
                     dash=10 if size == "book" else 14,
                     gap=8 if size == "book" else 10)

        cells.append({
            "text": spec["text"],
            "glyph": spec["glyph"],
            "base": spec["base"],
            "cand": spec["cand"],
            "box": [x0, y0, x1, y1],
            "check": [ccx, ccy, check_r],
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


def render_all(paper, size, module):
    """Render every cell page of one module; returns (images, layout_dict)."""
    page_defs = compose_pages(paper, size, module)
    images, pages = [], []
    for i, page_def in enumerate(page_defs):
        img, layout = render_page(paper, size, module, page_def, i, len(page_defs))
        images.append(img)
        pages.append(layout)
    layout = {
        "version": LAYOUT_VERSION,
        "dpi": DPI,
        "paper": paper,
        "size_mode": size,
        "module": module,
        "guide_gray": GUIDE_GRAY,
        "baseline_frac": BASELINE_FRAC,
        "xheight_frac": XHEIGHT_FRAC,
        "pages": pages,
    }
    return images, layout


def build(module, paper, size, outdir):
    images, layout = render_all(paper, size, module)
    if module == "english":
        # the how-to guide rides along as the first pages of the base module
        # (never scanned - it has no registration marks)
        import make_guide
        images = make_guide.render_pages(paper) + images
    os.makedirs(outdir, exist_ok=True)
    stem = f"{module}-{paper}-{size}"
    pdf_path = os.path.join(outdir, f"handwriting-{stem}.pdf")
    images[0].save(pdf_path, save_all=True, append_images=images[1:], resolution=DPI)
    json_path = os.path.join(outdir, f"layout-{stem}.json")
    with open(json_path, "w") as f:
        json.dump(layout, f, indent=1)
    print(f"wrote {pdf_path}  ({len(images)} pages)")
    print(f"wrote {json_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--paper", choices=["a4", "letter", "both"], default="both")
    ap.add_argument("--size", choices=["normal", "book", "all"], default="all")
    ap.add_argument("--modules", default=",".join(MODULES),
                    help=f"comma-separated subset of: {', '.join(MODULES)}")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "templates"))
    args = ap.parse_args()
    modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    unknown = set(modules) - set(MODULES)
    if unknown:
        ap.error(f"unknown modules: {', '.join(sorted(unknown))}")
    papers = ["a4", "letter"] if args.paper == "both" else [args.paper]
    sizes = ["normal", "book"] if args.size == "all" else [args.size]
    for module in modules:
        for paper in papers:
            for size in sizes:
                build(module, paper, size, args.outdir)


if __name__ == "__main__":
    main()
