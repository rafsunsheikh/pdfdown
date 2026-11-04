"""Reading order on two-column pages, and author lines mistaken for headings.

The layout step usually reads two columns correctly, but not always: on the
first page of the LLaMA paper it read the right column before the abstract in
the left one. This step puts every two-column page into the order a person
reads it. Blocks that cross the middle of the page (a title, an author list, a
wide figure) split the page into bands; within each band the left column is
read from top to bottom, then the right column. Pages with no block wholly in
each column are left as they are.
"""

from __future__ import annotations

import re

from pdfdown.document import Block, Document

TEXT = {"title", "heading", "paragraph", "list_item", "caption", "footnote", "reference", "code", "equation"}
STRADDLE = 4.0  # points a block must reach past the middle of the page, on both sides, to count as full width


def run(doc: Document, pdf=None) -> None:
    pages: dict[int, list[int]] = {}
    for i, b in enumerate(doc.blocks):
        if b.kind != "furniture" and b.box is not None:
            pages.setdefault(b.page, []).append(i)
    changed = 0
    for page, positions in pages.items():
        width = doc.page_sizes.get(page, (612.0, 792.0))[0]
        blocks = [doc.blocks[i] for i in positions]
        ordered = _read_order(blocks, width / 2)
        if ordered is not blocks and ordered != blocks:
            for i, b in zip(positions, ordered):
                doc.blocks[i] = b
            changed += 1
    _join_split_title(doc)
    _authors_are_not_headings(doc)
    _bangla_sentences_are_not_headings(doc)
    if changed:
        doc.notes.append(f"Put {changed} two-column page{'s' * (changed != 1)} into reading order (left column, then right).")


def _side(b: Block, mid: float) -> str:
    if b.box.l < mid - STRADDLE and b.box.r > mid + STRADDLE:
        return "full"
    return "left" if (b.box.l + b.box.r) / 2 < mid else "right"


def _two_columns(blocks: list[Block], sides: dict[int, str]) -> bool:
    """At least two text blocks in each column, and columns of similar width (a narrow sidebar is not a column)."""
    left = [b.box.width for b in blocks if b.kind in TEXT and sides[id(b)] == "left"]
    right = [b.box.width for b in blocks if b.kind in TEXT and sides[id(b)] == "right"]
    if len(left) < 2 or len(right) < 2:
        return False
    ratio = max(left) / max(max(right), 1.0)
    return 0.7 <= ratio <= 1.4


def _right_before_left(blocks: list[Block], sides: dict[int, str]) -> bool:
    """Did the layout step read right-column text before left-column text that sits beside it?"""
    for i, a in enumerate(blocks):
        if sides[id(a)] != "right" or a.kind not in TEXT:
            continue
        for b in blocks[i + 1:]:
            if sides[id(b)] == "left" and b.kind in TEXT and b.box.t < a.box.b:  # b is not wholly below a
                return True
    return False


def _read_order(blocks: list[Block], mid: float) -> list[Block]:
    sides = {id(b): _side(b, mid) for b in blocks}
    if not _two_columns(blocks, sides) or not _right_before_left(blocks, sides):
        return blocks  # one column, a sidebar layout, or already in reading order: keep the layout step's order
    full = sorted((b for b in blocks if sides[id(b)] == "full"), key=lambda b: b.box.t)
    columns = [b for b in blocks if sides[id(b)] != "full"]
    out: list[Block] = []
    top = float("-inf")
    for separator in [*full, None]:
        bottom = separator.box.t if separator else float("inf")
        band = [b for b in columns if top <= (b.box.t + b.box.b) / 2 < bottom]
        out += sorted((b for b in band if sides[id(b)] == "left"), key=lambda b: b.box.t)
        out += sorted((b for b in band if sides[id(b)] == "right"), key=lambda b: b.box.t)
        if separator:
            out.append(separator)
            top = (separator.box.t + separator.box.b) / 2
    missing = [b for b in blocks if b not in out]  # never lose a block, whatever its position
    return out + missing


def _join_split_title(doc: Document) -> None:
    """'Direct Preference Optimization:' and the line under it are one title, not a title and a heading."""
    first = next((i for i, b in enumerate(doc.blocks) if b.page == 1 and b.kind in ("title", "heading")), None)
    if first is None or first + 1 >= len(doc.blocks):
        return
    title, nxt = doc.blocks[first], doc.blocks[first + 1]
    unfinished = re.search(r"[:\-–—,]\s*$|\b(of|and|for|the|in|on|with|to|a|an)\s*$", title.text, re.I)
    close = nxt.box is not None and title.box is not None and 0 <= nxt.box.t - title.box.b < title.box.height
    if nxt.page == 1 and nxt.kind == "heading" and unfinished and close:
        title.text = f"{title.text.rstrip()} {nxt.text.strip()}"
        title.box = title.box.union(nxt.box)
        title.parts += nxt.parts
        del doc.blocks[first + 1]


_NAME_LIST = re.compile(r"(?:[A-Z][\w’'.-]+\s+){1,3}[A-Z][\w’'.-]+(?:<sup>[^<]*</sup>|[∗*†‡§¶\d,])*\s*,")


def _authors_are_not_headings(doc: Document) -> None:
    """On the first page, a 'heading' that is a list of names before the first real section is the author line."""
    seen_title = False
    for b in doc.blocks:
        if b.page != 1:
            break
        if b.kind in ("title", "heading") and not seen_title:
            seen_title = True
            continue
        if b.kind == "heading" and re.match(r"^\s*(abstract|\d|[IVX]+\.|introduction)", b.text, re.I):
            break
        if b.kind == "heading" and len(_NAME_LIST.findall(b.text)) >= 2:
            b.kind = "paragraph"


def _bangla_sentences_are_not_headings(doc: Document) -> None:
    """The last line of a Bangla paragraph at the foot of a page ("ঘোরাচ্ছেন।") can be taken for a heading.
    A heading does not end with । ? or !; such a block is a paragraph, and stitching joins it to its sentence."""
    from pdfdown.pdftext import bengali_share

    for b in doc.blocks:
        if b.kind == "heading" and bengali_share(b.text) > 0.3 and re.search(r"[।?!]['’”\"*]*\s*$", b.text):
            b.kind = "paragraph"
