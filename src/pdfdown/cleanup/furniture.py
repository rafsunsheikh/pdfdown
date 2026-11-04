"""Remove page furniture: running headers and footers, page numbers, journal lines.

Docling marks most of them, but not all: Nature's running header "Article"
comes through as a section heading on every left-hand page. A block is
treated as furniture when its text (with digits ignored) repeats on at least
a third of the pages, near the top or bottom edge.
"""

from __future__ import annotations

import re
from collections import defaultdict

from pdfdown.document import Document

EDGE = 0.09  # top or bottom 9% of the page


def _key(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def run(doc: Document, pdf=None) -> None:
    pages = max(len(doc.page_sizes), 1)
    seen: dict[str, set[int]] = defaultdict(set)
    for b in doc.blocks:
        if b.box and b.text and len(b.text) < 120 and _near_edge(doc, b):
            seen[_key(b.text)].add(b.page)
    repeated = {k for k, ps in seen.items() if len(ps) >= max(2, pages / 3)}
    words = {k for k in repeated if k.replace("#", "").strip() and len(k.split()) <= 3}
    # Running headers Docling marked itself (not always inside the edge band)
    marked_pages: dict[str, set[int]] = defaultdict(set)
    for b in doc.blocks:
        if b.kind == "furniture" and b.box and b.text:
            marked_pages[_key(b.text)].add(b.page)
    marked = {k for k, ps in marked_pages.items()
              if len(ps) >= max(2, pages / 3) and k.replace("#", "").strip() and len(k.split()) <= 3}
    kept, dropped = [], 0
    for b in doc.blocks:
        if b.kind == "heading":
            for key in words:  # "Article Methods": a running header merged into a heading
                if _key(b.text).startswith(key + " ") and len(b.text) > len(key) + 2:
                    b.text = b.text[len(key):].strip()
        elif b.kind == "paragraph" and b.box:
            for key in marked:  # "মুক্ত বিহঙ্গ-১ ১০৩ ..." or "৩৮ মাসুদ রানা-১৬৩ ...": a running header merged into a paragraph
                pattern = r"\s*".join(r"\d+" if part == "#" else re.escape(part) for part in re.split(r"(#)|\s+", key) if part)
                m = re.match(r"(?:\d+\s*)?" + pattern + r"(?=\s|$)\s*\d*\s*", b.text, re.I)
                if m:
                    b.text = b.text[m.end():]
                    break
            if not b.text:
                dropped += 1
                continue
        page_number = bool(re.fullmatch(r"\d{1,4}", b.text)) and b.box is not None and _near_edge(doc, b)
        if b.kind == "furniture" or page_number or (b.text and _key(b.text) in repeated and _near_edge(doc, b)):
            dropped += 1
            continue
        kept.append(b)
    doc.blocks = kept
    if dropped:
        doc.notes.append(f"Removed {dropped} page headers, footers and page numbers.")


def _near_edge(doc: Document, b) -> bool:
    height = doc.page_sizes.get(b.page, (0, 792))[1]
    return b.box.t < EDGE * height or b.box.b > (1 - EDGE) * height


def rescue_headings(doc: Document, pdf=None) -> None:
    """A chapter title Docling took for a page header: printed once, near the top, much larger than the text.

    In a novel each chapter opens with its number ("তিন", "Three") alone at the top of the page. Docling labels
    some of these page headers, which would drop them. Real running headers repeat on many pages; a chapter
    title appears once, in a bigger size.
    """
    if pdf is None:
        return
    from statistics import median

    def size(b) -> float:
        sizes = [c.size for page, box in b.parts for c in pdf.page(page).inside(box) if c.ch.strip()]
        return median(sizes) if sizes else 0.0

    body = [s for s in (size(b) for b in [b for b in doc.blocks if b.kind == "paragraph"][:300]) if s]
    if not body:
        return
    body_size = median(body)
    pages: dict[str, set[int]] = defaultdict(set)
    for b in doc.blocks:
        if b.text and b.box:
            pages[_key(b.text)].add(b.page)
    rescued = 0
    for b in doc.blocks:
        if b.kind != "furniture" or not b.box or not b.text or len(b.text) > 40 or re.fullmatch(r"[\d\s.]+", b.text):
            continue
        height = doc.page_sizes.get(b.page, (0, 792))[1]
        if b.box.t > 0.3 * height or len(pages[_key(b.text)]) > 1 or size(b) < 1.25 * body_size:
            continue
        b.kind, b.level = "heading", 1
        rescued += 1
    if rescued:
        doc.notes.append(f"Kept {rescued} chapter titles that looked like page headers (printed once, in large type).")
