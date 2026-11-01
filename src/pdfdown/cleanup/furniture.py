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
    kept, dropped = [], 0
    for b in doc.blocks:
        if b.kind == "heading":
            for key in words:  # "Article Methods": a running header merged into a heading
                if _key(b.text).startswith(key + " ") and len(b.text) > len(key) + 2:
                    b.text = b.text[len(key):].strip()
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
