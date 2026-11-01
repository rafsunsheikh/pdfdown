"""Rebuild block text from the PDF's characters (superscripts, subscripts, hyphenation).

Docling's text is kept when the PDF has no usable character layer for the
block (a scanned page) or when the rebuilt text is clearly incomplete.
"""

from __future__ import annotations

import re

from pdfdown.document import Document
from pdfdown.pdftext import PdfText, block_text, vocabulary

REBUILT = {"title", "heading", "paragraph", "list_item", "caption", "footnote", "reference"}


def _plain(text: str) -> str:
    return re.sub(r"</?su[bp]>|\s+", "", text)


def run(doc: Document, pdf: PdfText) -> None:
    vocab = vocabulary(pdf, sorted(doc.page_sizes))
    rebuilt = 0
    for b in doc.blocks:
        if b.kind not in REBUILT or not b.parts:
            continue
        text, seen = block_text(pdf, b.parts, vocab)
        old = re.sub(r"\s+", "", b.text)
        # Accept the rebuilt text when it covers roughly the same characters as Docling's.
        if seen and old and 0.85 <= len(_plain(text)) / max(len(old), 1) <= 1.2:
            b.text = text
            rebuilt += 1
    if rebuilt:
        doc.notes.append(f"Rebuilt {rebuilt} text blocks from the PDF's characters, restoring superscripts and subscripts and joining lines.")
