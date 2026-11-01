"""Make a side-by-side picture: a PDF page on the left, the same part of the Markdown on the right.

The Markdown is rendered in headless Chrome with GitHub's stylesheet and MathJax, so the right side
looks as it does on github.com. Development helper for the README's examples.

    .venv/bin/python scripts/side_by_side.py examples/dpo/dpo.md examples/dpo/dpo.pdf 4 \\
        "start of the section" "start of the next part" docs/images/example-dpo.png
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTH = 820  # CSS pixels of the Markdown column; screenshots are taken at 2x
PAGE = """<!doctype html><html><head><meta charset="utf-8"><base href="{base}">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/github-markdown-light.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script>window.MathJax = {{tex: {{tags: 'ams'}}, chtml: {{scale: 1.0}}}};</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js" async></script>
<style>body{{margin:0;background:#fff}} .markdown-body{{box-sizing:border-box;width:{width}px;padding:28px 36px}}
.markdown-body img{{max-width:100%}}</style></head>
<body><article class="markdown-body" id="md"></article>
<script>document.getElementById('md').innerHTML = marked.parse({source});</script></body></html>"""


def chunk(md: str, start: str, end: str) -> str:
    i = md.index(start)
    j = md.index(end, i) if end else len(md)
    i = md.rfind("\n\n", 0, i) + 2 if md.rfind("\n\n", 0, i) >= 0 else i  # whole paragraph
    return md[i:j].strip()


def protect_math(md: str) -> str:
    """Keep $$ blocks away from the Markdown parser; MathJax renders them."""
    return re.sub(r"\$\$\n(.*?)\n\$\$", lambda m: '<div>\\[' + html.escape(m.group(1)) + '\\]</div>', md, flags=re.S)


def trim(image: Image.Image, margin: int = 24) -> Image.Image:
    background = Image.new(image.mode, image.size, (255, 255, 255))
    box = ImageChops.difference(image.convert("RGB"), background.convert("RGB")).getbbox()
    if not box:
        return image
    return image.crop((0, 0, image.width, min(box[3] + margin, image.height)))


def main(md_path: str, pdf_path: str, page: int, start: str, end: str, out: str) -> None:
    md_file, out_file = Path(md_path).resolve(), Path(out).resolve()
    source = protect_math(chunk(md_file.read_text(encoding="utf-8"), start, end))
    work = out_file.with_suffix(".work.html")
    work.write_text(PAGE.format(base=md_file.parent.as_uri() + "/", width=WIDTH, source=_js(source)), encoding="utf-8")
    shot = out_file.with_suffix(".md.png")
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--allow-file-access-from-files", "--virtual-time-budget=15000",
                    f"--window-size={WIDTH},4000", f"--screenshot={shot}", work.as_uri()],
                   check=True, capture_output=True)
    right = trim(Image.open(shot))
    pdf = pdfium.PdfDocument(str(pdf_path))
    left = pdf[page - 1].render(scale=2.4).to_pil().convert("RGB")
    pdf.close()
    height = max(left.height, right.height)
    left = left.resize((round(left.width * right.height / left.height), right.height)) if right.height > left.height else left
    height = max(left.height, right.height)
    gap = 40
    canvas = Image.new("RGB", (left.width + gap + right.width, height), (255, 255, 255))
    canvas.paste(left, (0, 0))
    canvas.paste(Image.new("RGB", (4, height), (208, 215, 222)), (left.width + gap // 2 - 2, 0))
    canvas.paste(right, (left.width + gap, 0))
    canvas.thumbnail((2400, 2400))
    canvas.save(out_file, optimize=True)
    work.unlink()
    shot.unlink()
    print(f"{out_file}: {canvas.width}x{canvas.height}")


def _js(text: str) -> str:
    import json

    return json.dumps(text).replace("</", "<\\/")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6])
