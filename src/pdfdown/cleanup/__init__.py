"""The cleanup layer: small steps that turn Docling's blocks into a clean article.

Each step takes the Document and rewrites doc.blocks in place, adding a short
plain-language note to doc.notes about what it changed. Order matters:
text is rebuilt before captions are parsed, and paragraphs are stitched only
after floats and furniture have been sorted out.
"""

from __future__ import annotations

from pdfdown.cleanup import captions, figures, furniture, notes, order, retext, stitch
from pdfdown.document import Document
from pdfdown.pdftext import PdfText

STEPS = [
    ("furniture", furniture.run),
    ("order", order.run),
    ("figure text", figures.drop_inner_text),
    ("retext", retext.run),
    ("captions", captions.run),
    ("icons", figures.drop_icons),
    ("stitch", stitch.run),
    ("notes", notes.run),
]


def clean(doc: Document, pdf: PdfText | None = None) -> Document:
    own = pdf is None
    pdf = pdf or PdfText(doc.source)
    try:
        for _name, step in STEPS:
            step(doc, pdf)
    finally:
        if own:
            pdf.close()
    return doc
