#!/usr/bin/env python3
"""Segment scans -> build font -> variable font -> proof, archived under
fonts/ with a date-time-stamped name.

Each positional arg is <module>=<scan-image>; the matching
templates/layout-<module>-<paper>-<size>.json is used to segment it, and all
scans land in one shared cell directory so several module sheets merge into a
single font. Output goes to:

    fonts/font-<NN>_<DD-MM>_<HH-MM>/
        font-<NN>_<DD-MM>_<HH-MM>-Regular.ttf   static
        font-<NN>_<DD-MM>_<HH-MM>-VF.ttf        variable (weight axis)
        font-<NN>_<DD-MM>_<HH-MM>-proof.png     specimen

NN auto-increments from whatever is already in fonts/.

Usage:
    python3 scripts/finalize_font.py --family "Adina Hand" \
        english=/path/eng.jpg czech=/path/cz.jpg
"""

import argparse
import glob
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def next_index(fonts_dir):
    mx = 0
    for d in glob.glob(os.path.join(fonts_dir, "font-*")):
        m = re.match(r"font-(\d+)_", os.path.basename(d))
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def run(cmd):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pairs", nargs="+", help="module=scan.jpg (repeatable)")
    ap.add_argument("--family", default="My Hand")
    ap.add_argument("--paper", default="a4")
    ap.add_argument("--size", default="book")
    ap.add_argument("--build-args", default="",
                    help="extra flags forwarded to build_font.py, e.g. "
                         "'--target-gap 35'")
    ap.add_argument("--no-snap", action="store_true",
                    help="disable baseline snapping (on by default; snapping "
                         "sits every letter on the line to cancel float)")
    args = ap.parse_args()

    cells = os.path.join(ROOT, "work", "cells_final")
    subprocess.run(["rm", "-rf", cells])
    os.makedirs(cells, exist_ok=True)
    for pair in args.pairs:
        if "=" not in pair:
            ap.error(f"expected module=scan, got {pair!r}")
        mod, scan = pair.split("=", 1)
        layout = os.path.join(
            ROOT, "templates", f"layout-{mod}-{args.paper}-{args.size}.json")
        if not os.path.exists(layout):
            ap.error(f"no layout for module {mod!r}: {layout}")
        run([sys.executable, os.path.join(ROOT, "segment.py"),
             "--layout", layout, scan, "--outdir", cells])

    fonts = os.path.join(ROOT, "fonts")
    os.makedirs(fonts, exist_ok=True)
    name = f"font-{next_index(fonts):02d}_{datetime.now().strftime('%d-%m_%H-%M')}"
    outdir = os.path.join(fonts, name)
    os.makedirs(outdir, exist_ok=True)
    reg = os.path.join(outdir, f"{name}-Regular.ttf")
    vf = os.path.join(outdir, f"{name}-VF.ttf")
    proof = os.path.join(outdir, f"{name}-proof.png")

    build_flags = args.build_args.split()
    if not args.no_snap:
        build_flags.append("--snap-baseline")
    run([sys.executable, os.path.join(ROOT, "build_font.py"),
         "--cells", cells, "--out", reg, "--family", args.family] + build_flags)
    run([sys.executable, os.path.join(ROOT, "make_variable.py"),
         "--regular", reg, "--out", vf])
    run([sys.executable, os.path.join(ROOT, "proof.py"),
         "--font", vf, "--out", proof])
    print(f"\narchived -> {os.path.relpath(outdir, ROOT)}")


if __name__ == "__main__":
    main()
