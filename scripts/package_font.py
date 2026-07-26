#!/usr/bin/env python3
"""Package a variable font into everything you actually need to install and
use it:

    <Family>-VF.ttf        variable, Light->Bold slider (modern macOS/Windows)
    <Family>-Regular.ttf   static  - installs anywhere, Mac and Windows
    <Family>-Bold.ttf      static  - so apps' "bold" button works
    <Family>-VF.woff2      web (CSS font-face with a weight range)
    <Family>-Regular.woff2 web, single weight (Excalidraw, simple sites)

Statics are pinned instances of the variable font, so they inherit the same
weights the VF shows at wght=400 / wght=700.

Usage:
    python3 scripts/package_font.py --vf work/MyHandVF.ttf \
        --family "Adina Hand" --outdir fonts/font-03_25-07_12-30
"""

import argparse
import os

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

WIN, MAC = (3, 1, 0x409), (1, 0, 0)


def ps_safe(text):
    """PostScript names must not carry spaces or punctuation, so an
    apostrophe in a family name ("Adina's Handwriting") has to go - the
    human-readable family keeps it, the machine name does not."""
    return "".join(c for c in text if c.isalnum())


def set_names(font, family, style, version="1.000"):
    """Write a coherent name table for a static instance."""
    name = font["name"]
    ps = f"{ps_safe(family)}-{ps_safe(style)}"
    records = {
        1: family,
        2: style,
        3: f"{version};{family} {style}",
        4: f"{family} {style}",
        6: ps,
        5: f"Version {version}",
    }
    for nid, value in records.items():
        for plat, enc, lang in (WIN, MAC):
            name.setName(value, nid, plat, enc, lang)
    # typographic family/subfamily: drop them so Regular/Bold pair as one family
    for nid in (16, 17):
        name.removeNames(nid)


def set_weight_bits(font, weight_class, bold):
    os2, head = font["OS/2"], font["head"]
    os2.usWeightClass = weight_class
    os2.fsSelection = (os2.fsSelection & ~(1 << 5) & ~(1 << 6)) | (
        (1 << 5) if bold else (1 << 6))
    head.macStyle = (head.macStyle & ~1) | (1 if bold else 0)


def static(vf_path, family, style, wght, bold, outdir, version):
    font = TTFont(vf_path)
    instantiateVariableFont(font, {"wght": wght}, inplace=True, updateFontNames=False)
    set_names(font, family, style, version)
    set_weight_bits(font, wght, bold)
    out = os.path.join(outdir, f"{ps_safe(family)}-{style}.ttf")
    font.save(out)
    return out, font


def as_woff2(ttf_path):
    font = TTFont(ttf_path)
    font.flavor = "woff2"
    out = ttf_path[:-4] + ".woff2"
    font.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vf", required=True, help="variable font from make_variable.py")
    ap.add_argument("--family", default="My Hand")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--version", default="1.000")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    stem = ps_safe(args.family)
    written = []

    vf_out = os.path.join(args.outdir, f"{stem}-VF.ttf")
    vf = TTFont(args.vf)
    set_names(vf, args.family, "Regular", args.version)
    # a variable font keeps its typographic family so the slider stays exposed
    vf["name"].setName(args.family, 16, *WIN)
    vf["name"].setName("Regular", 17, *WIN)
    vf.save(vf_out)
    written.append(vf_out)

    for style, wght, bold in (("Regular", 400, False), ("Bold", 700, True)):
        path, _ = static(args.vf, args.family, style, wght, bold,
                         args.outdir, args.version)
        written.append(path)

    written.append(as_woff2(vf_out))
    written.append(as_woff2(os.path.join(args.outdir, f"{stem}-Regular.ttf")))

    for p in written:
        print(f"  {os.path.basename(p):32s} {os.path.getsize(p) / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
