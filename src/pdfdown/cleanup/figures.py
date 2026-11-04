"""Figures: drop text that belongs inside a figure (axis labels, legends, panel letters).

Docling sometimes reports the labels drawn inside a vector chart as separate
text blocks ("Time Time" under Nature's Fig. 1). Any short text block that
lies mostly inside a figure on the same page is part of the picture, which
pdfdown crops as an image anyway.
"""

from __future__ import annotations

from pdfdown.document import Box, Document


def _inside_share(inner: Box, outer: Box) -> float:
    w = max(0.0, min(inner.r, outer.r) - max(inner.l, outer.l))
    h = max(0.0, min(inner.b, outer.b) - max(inner.t, outer.t))
    area = max(inner.width * inner.height, 1e-6)
    return w * h / area


def drop_inner_text(doc: Document, pdf=None) -> None:
    figures = [b for b in doc.blocks if b.kind == "figure" and b.box]
    kept, dropped = [], 0
    for b in doc.blocks:
        if b.kind in ("paragraph", "list_item", "heading") and b.box and len(b.text) < 200:
            holders = [f for f in figures if f.page == b.page and _inside_share(b.box, f.box) > 0.6]
            if holders and not (b.kind == "heading" and all(_ornament(f, b, doc) for f in holders)):
                dropped += 1
                continue
            if _label_beside_figure(b, figures):
                dropped += 1
                continue
        kept.append(b)
    doc.blocks = kept
    if dropped:
        doc.notes.append(f"Dropped {dropped} text fragments drawn inside figures (axis labels and legends).")


def _ornament(figure, heading, doc: Document) -> bool:
    """A decoration behind a chapter title: no caption, and the title is the only text drawn on it."""
    if figure.extra.get("caption_refs"):
        return False
    return not any(o is not heading and o.page == figure.page and o.box and o.kind not in ("figure", "furniture")
                   and _inside_share(o.box, figure.box) > 0.6 for o in doc.blocks)


def _label_beside_figure(b, figures) -> bool:
    """A few words with no sentence punctuation, right at a figure's edge: an axis title or legend."""
    words = b.text.split()
    if b.kind != "paragraph" or len(words) > 4 or len(b.text) > 40 or b.text.rstrip().endswith((".", ":", ";")):
        return False
    for f in figures:
        if f.page != b.page or b.box.overlap_x(f.box) < 0.5 * b.box.width:
            continue
        gap = max(b.box.t - f.box.b, f.box.t - b.box.b, 0)
        if gap < 25:
            return True
    return False


ICON = 24.0  # points; a figure smaller than this both ways is a logo or badge


def drop_icons(doc: Document, pdf=None) -> None:
    """Drop tiny images without a caption, such as a journal's "Check for updates" badge."""
    keep = [b for b in doc.blocks if not (b.kind == "figure" and not b.extra.get("caption")
                                          and b.box.width < ICON and b.box.height < ICON)]
    dropped = len(doc.blocks) - len(keep)
    doc.blocks = keep
    if dropped:
        doc.notes.append(f"Dropped {dropped} tiny image{'s' * (dropped != 1)} without a caption (logos and badges).")
