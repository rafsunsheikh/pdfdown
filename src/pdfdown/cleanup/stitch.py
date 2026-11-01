"""Stitch paragraphs that a column break, page break or figure interrupted.

PDFs end a block wherever the column or page ends, so a sentence like
"... on the basis of" / "41,298,433 papers ..." arrives as two paragraphs,
sometimes with a figure, caption or footnote between them. A paragraph that
does not end a sentence is joined with the next body paragraph; anything that
sat between them (figures, tables, footnotes) moves to just after the joined
paragraph, so floats still appear next to the text that surrounds them.
"""

from __future__ import annotations

import re

from pdfdown.document import Document

END = re.compile(r"""[.!?:;](?:["'”’)\]]|</sup>|\s*<sup>[^<]*</sup>)*\s*$""")
FLOATING = {"figure", "table", "footnote", "caption"}


def ends_sentence(text: str) -> bool:
    return bool(END.search(text))


def run(doc: Document, pdf=None) -> None:
    out = []
    joined = 0
    i = 0
    blocks = doc.blocks
    while i < len(blocks):
        b = blocks[i]
        if b.kind != "paragraph":
            out.append(b)
            i += 1
            continue
        held = []
        while not ends_sentence(b.text):
            j = i + 1
            between = []
            while j < len(blocks) and blocks[j].kind in FLOATING:
                between.append(blocks[j])
                j += 1
            if j < len(blocks) and blocks[j].kind == "paragraph" and _continues(blocks[j].text):
                nxt = blocks[j]
                b.text = b.text.rstrip() + " " + nxt.text.lstrip()
                b.parts = b.parts + nxt.parts
                held += between
                i = j
                joined += 1
            else:
                break
        out.append(b)
        out.extend(held)
        i += 1
    doc.blocks = out
    if joined:
        doc.notes.append(f"Joined {joined} paragraphs split across columns, pages or figures.")


def _continues(text: str) -> bool:
    """A continuation starts in lowercase, with a digit, or with punctuation, never with a new heading-like line."""
    stripped = re.sub(r"^<su[bp]>[^<]*</su[bp]>", "", text.lstrip())
    return bool(stripped) and (stripped[0].islower() or stripped[0].isdigit() or stripped[0] in ",;:)]–-")
