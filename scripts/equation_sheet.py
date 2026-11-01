"""Review sheet: each equation written as LaTeX, rendered, next to the crop of the original (development helper).

    .venv/bin/python scripts/equation_sheet.py examples/dpo/dpo.md out/review/dpo
writes out/review/dpo-1.png, -2.png, ... with ten equations per picture.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PER_SHEET = 10


def equations(md: str) -> list[tuple[int, str | None]]:
    """(number, LaTeX or None for an image), in the order the exporter numbered them."""
    found = []
    for m in re.finditer(r"!\[Equation (\d+)\]\(equations/eq-\d+\.png\)|\$\$\n(.*?)\n\$\$", md, flags=re.S):
        found.append((len(found) + 1, m.group(2)))
    return found


def main(md_path: str, out_prefix: str) -> None:
    md_file = Path(md_path).resolve()
    out = Path(out_prefix).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    latex = [(n, tex) for n, tex in equations(md_file.read_text(encoding="utf-8")) if tex]
    for sheet, start in enumerate(range(0, len(latex), PER_SHEET), start=1):
        rows = "".join(
            f"<tr><td>{n}</td><td><img src='equations/eq-{n}.png'></td><td>\\[{html.escape(tex)}\\]</td></tr>"
            for n, tex in latex[start:start + PER_SHEET])
        page = out.with_name(f"{out.name}-{sheet}.html")
        page.write_text(f"""<!doctype html><meta charset="utf-8"><base href="{md_file.parent.as_uri()}/">
<script>window.MathJax={{tex:{{tags:'ams'}}}};</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js" async></script>
<style>body{{font:14px sans-serif;margin:10px}} td{{border-bottom:1px solid #ccc;padding:6px;vertical-align:middle}}
img{{max-width:640px;max-height:150px}} td:nth-child(3){{width:640px}}</style>
<table><tr><th>#</th><th>PDF</th><th>LaTeX, rendered</th></tr>{rows}</table>""", encoding="utf-8")
        shot = out.with_name(f"{out.name}-{sheet}.png")
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                        "--virtual-time-budget=15000", "--window-size=1400,2400", f"--screenshot={shot}", page.as_uri()],
                       check=True, capture_output=True)
        image = Image.open(shot)
        pixels = image.convert("L").point(lambda v: 255 if v > 250 else 0)
        box = Image.eval(pixels, lambda v: 255 - v).getbbox()
        if box:
            image.crop((0, 0, image.width, min(box[3] + 10, image.height))).save(shot)
        page.unlink()
        print(shot)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
