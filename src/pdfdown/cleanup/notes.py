"""Footnotes and affiliations: move them out of the reading flow to a Notes section.

On the first page of an article the author affiliations sit at the bottom of
the first column; left in place they interrupt the introduction. They are
moved to the end, before the references when there is a references heading.
"""

from __future__ import annotations

import re

from pdfdown.document import Block, Document

REFERENCES = re.compile(r"^\s*(references|bibliography|literature cited)\s*$", re.I)


def run(doc: Document, pdf=None) -> None:
    notes = [b for b in doc.blocks if b.kind == "footnote"]
    if not notes:
        return
    body = [b for b in doc.blocks if b.kind != "footnote"]
    section = [Block(kind="heading", text="Notes", level=2, extra={"generated": True})] + notes
    refs = next((i for i, b in enumerate(body) if b.kind == "heading" and REFERENCES.match(b.text)), None)
    doc.blocks = body[:refs] + section + body[refs:] if refs is not None else body + section
    doc.notes.append(f"Moved {len(notes)} footnotes and affiliations to a Notes section at the end.")
