# fonts/

Built fonts, one timestamped folder per build so you can compare runs:

```
fonts/font-<NN>_<DD-MM>_<HH-MM>/
    ...-Regular.ttf   static TrueType
    ...-VF.ttf        variable font (Light->Bold weight axis) — install this
    ...-proof.png     specimen sheet
```

`NN` is a running index; the date-time marks when it was built. Produce a new
dated build with:

```bash
python3 scripts/finalize_font.py --family "Adina's Handwriting" \
    english=/path/to/english-scan.jpg czech=/path/to/czech-scan.jpg
```

Add more `module=scan.jpg` pairs (slovak, polish, symbols, ligatures,
small-caps) to fold them into the same font. Pass tuning through
`--build-args`, e.g. `--build-args "--target-gap 35"`.
