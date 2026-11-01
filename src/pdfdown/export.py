"""Write a cleaned Document as Markdown, with figure, table and equation crops.

Output layout, for `paper.pdf` converted into `out/`:

    out/paper/paper.md
    out/paper/figures/figure-1.png      cropped from the page at 216 dpi (vector figures stay sharp)
    out/paper/tables/table-1.png        always kept, used when a table cannot be rebuilt as text
    out/paper/equations/eq-1.png        always kept; LaTeX replaces it only when it passes the render check
"""

from __future__ import annotations

import re
from pathlib import Path

import pypdfium2 as pdfium

from pdfdown.document import Block, Box, Document

SCALE = 3.0  # 72 dpi * 3 = 216 dpi
PAD = 3.0  # points of margin around crops


def render(pdf: pdfium.PdfDocument, page: int, box: Box, scale: float = SCALE, pad: float = PAD):
    """The part of a page inside `box`, as a PIL image."""
    p = pdf[page - 1]
    w, h = p.get_width(), p.get_height()
    left, top = max(box.l - pad, 0), max(box.t - pad, 0)
    right, bottom = min(box.r + pad, w), min(box.b + pad, h)
    return p.render(scale=scale, crop=(left, h - bottom, w - right, top)).to_pil()


def crop(pdf: pdfium.PdfDocument, page: int, box: Box, path: Path, scale: float = SCALE) -> Path:
    image = render(pdf, page, box, scale)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    return path


def use_latex(block: Block) -> bool:
    """LaTeX when it passed the checks, unless the person chose otherwise in the TUI."""
    if not block.extra.get("latex"):
        return False
    choice = block.extra.get("use")
    return choice == "latex" if choice else bool(block.extra.get("latex_ok"))


def area(block: Block) -> tuple[int, Box]:
    """The page and box to crop: the person's adjusted box, or the union of the block's parts on its first page."""
    if block.extra.get("crop"):
        return block.page, Box(*block.extra["crop"])
    return detected_area(block)


def detected_area(block: Block) -> tuple[int, Box]:
    """The box the layout model found, ignoring any adjustment."""
    page = block.parts[0][0]
    box = block.parts[0][1]
    for pg, bx in block.parts[1:]:
        if pg == page:
            box = box.union(bx)
    return page, box


_TAG = re.compile(r"<(?!/?su[bp]>)")


def inline(text: str) -> str:
    """Escape what Markdown would misread, keeping our <sup>/<sub> tags."""
    text = _TAG.sub("&lt;", text)
    text = re.sub(r"(?<!\\)\*", r"\\*", text)
    return text


def _list_line(text: str) -> str:
    m = re.match(r"^\s*(\d+)[.)]\s+(.*)$", text)
    if m:
        return f"{m.group(1)}. {inline(m.group(2))}"
    text = re.sub(r"^\s*[•●▪◦‣∙·\-–-]\s*", "", text)  #  and friends: Word's Symbol-font bullets
    return f"- {inline(text)}"


def write(doc: Document, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    stem = doc.source.stem
    root = out_dir / stem
    root.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(doc.source))
    lines: list[str] = []
    eq_count = 0
    title_done = False
    used_names: set[str] = set()
    try:
        for b in doc.blocks:
            if b.kind in ("title",) or (b.kind == "heading" and not title_done and b.page == 1 and not b.extra.get("generated")):
                lines += [f"# {inline(b.text)}", ""]
                title_done = True
                doc.title = doc.title or b.text
            elif b.kind == "heading":
                lines += [f"{'#' * min(b.level + 1, 4)} {inline(b.text)}", ""]
            elif b.kind == "paragraph":
                lines += [inline(b.text), ""]
            elif b.kind == "list_item":
                lines += [_list_line(b.text)]
                lines += [""] if not _next_is(doc, b, "list_item") else []
            elif b.kind in ("footnote", "reference"):
                lines += [inline(b.text), ""]
            elif b.kind == "caption":
                lines += [f"*{inline(b.text)}*", ""]
            elif b.kind == "code":
                lines += ["```", b.text, "```", ""]
            elif b.extra.get("hidden"):
                continue
            elif b.kind == "figure":
                name = _unique(f"figure-{b.extra.get('number', '')}".lower(), used_names, _shares_caption(doc, b))
                rel = Path("figures") / f"{name}.png"
                page, box = area(b)
                crop(pdf, page, box, root / rel)
                b.extra["image"] = str(rel)
                caption = b.extra.get("caption", "")
                alt = re.sub(r"<[^>]+>", "", caption)[:150] or f"Figure on page {page}"
                lines += [f"![{alt}]({rel.as_posix()})", ""]
                if caption and not _next_shares_caption(doc, b):  # panels of one figure: caption once, after the last
                    lines += [f"*{inline(caption)}*", ""]
            elif b.kind == "table":
                rel = Path("tables") / f"table-{b.extra.get('number', '')}".lower()
                rel = rel.with_suffix(".png")
                page, box = area(b)
                crop(pdf, page, box, root / rel)
                b.extra["image"] = str(rel)
                if b.extra.get("caption"):
                    lines += [f"*{inline(b.extra['caption'])}*", ""]
                if b.extra.get("grid") and not b.extra.get("spans") and b.extra.get("markdown"):
                    lines += [b.extra["markdown"], ""]
                elif b.extra.get("html"):
                    lines += [re.sub(r"<caption>.*?</caption>", "", b.extra["html"], flags=re.S), ""]
                else:
                    lines += [f"![Table]({rel.as_posix()})", ""]
            elif b.kind == "equation":
                eq_count += 1
                rel = Path("equations") / f"eq-{eq_count}.png"
                page, box = area(b)
                crop(pdf, page, box, root / rel)
                b.extra["image"] = str(rel)
                if use_latex(b):
                    lines += ["$$", b.extra["latex"], "$$", ""]
                else:
                    lines += [f"![Equation {eq_count}]({rel.as_posix()})", ""]
    finally:
        pdf.close()
    text = "\n".join(lines).rstrip() + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    md = root / f"{stem}.md"
    md.write_text(text, encoding="utf-8")
    return md


def _next_is(doc: Document, block: Block, kind: str) -> bool:
    i = doc.blocks.index(block)
    return i + 1 < len(doc.blocks) and doc.blocks[i + 1].kind == kind


def _shares_caption(doc: Document, block: Block) -> bool:
    cap = block.extra.get("caption")
    return bool(cap) and sum(1 for b in doc.blocks if b.kind == block.kind and b.extra.get("caption") == cap) > 1


def _next_shares_caption(doc: Document, block: Block) -> bool:
    i = doc.blocks.index(block)
    nxt = doc.blocks[i + 1] if i + 1 < len(doc.blocks) else None
    return bool(nxt and nxt.kind == block.kind and block.extra.get("caption") and nxt.extra.get("caption") == block.extra.get("caption"))


def _unique(name: str, used: set[str], panels: bool) -> str:
    """figure-2 -> figure-2a, figure-2b when one caption covers several images; never overwrite a file."""
    if panels or name in used:
        for letter in "abcdefghijklmnopqrstuvwxyz":
            if f"{name}{letter}" not in used:
                name = f"{name}{letter}"
                break
    used.add(name)
    return name
