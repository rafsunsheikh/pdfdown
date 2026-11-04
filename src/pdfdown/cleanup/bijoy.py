"""Text in old Bijoy fonts (SutonnyMJ, JugantorMJ ...) to Unicode Bangla.

Such PDFs store Bangla as Latin letters ("gvmy` ivbv" for "মাসুদ রানা"). A block whose letters come mostly from a
Bijoy font is converted with pdfdown.bijoy; blocks in other fonts, such as English, are left alone.
"""

from __future__ import annotations

import re
from collections import Counter

from pdfdown.bijoy import is_bijoy_font, to_unicode
from pdfdown.document import Document
from pdfdown.pdftext import PdfText


def _bijoy_share(pdf: PdfText, parts) -> tuple[float, Counter]:
    fonts: Counter = Counter()
    total = 0
    for page, box in parts:
        for c in pdf.page(page).inside(box):
            if c.font:
                total += 1
                if is_bijoy_font(c.font):
                    fonts[c.font.split("+")[-1]] += 1
    return (sum(fonts.values()) / total if total else 0.0), fonts


def run(doc: Document, pdf: PdfText) -> None:
    converted, fonts = 0, Counter()
    for b in doc.blocks:
        if b.kind in ("figure", "equation") or not b.parts:  # furniture too, to match headers merged into text
            continue
        share, used = _bijoy_share(pdf, b.parts)
        if share < 0.5:
            continue
        fonts.update(used)
        if b.kind != "table":
            # pdfium's reading keeps Bijoy words whole; Docling's adds spaces inside them ("Ly wk‡Z" for "Lywk‡Z")
            raw = " ".join(pdf.text_in(page, box) for page, box in b.parts)
            raw = re.sub(r"(?<=[^\s\d])\u2212", "¬", raw)  # this font's ্ল comes through as a minus sign (not after a digit)
            b.text = re.sub(r"\s+", " ", to_unicode(raw)).strip() or b.text
        else:
            b.text = to_unicode(b.text)
        if b.kind == "table":
            for key in ("markdown", "html"):
                if b.extra.get(key):
                    # convert the cell text only, never the markup around it
                    b.extra[key] = re.sub(r"(?<=>)[^<]+(?=<)", lambda m: to_unicode(m.group(0)), b.extra[key]) \
                        if key == "html" else "\n".join(_convert_row(row) for row in b.extra[key].splitlines())
            if b.extra.get("grid"):
                b.extra["grid"] = [[to_unicode(cell) for cell in row] for row in b.extra["grid"]]
        b.extra["bijoy"] = True
        converted += 1
    if converted:
        # Docling also splits a hanging vowel sign (ু, ঁ) out of its word into a block of its own, with no width;
        # the sign is already in its word.
        doc.blocks = [b for b in doc.blocks if not (b.kind == "paragraph" and b.box and b.box.r - b.box.l < 0.5
                                                    and len(b.text) <= 2)]
        names = ", ".join(name for name, _ in fonts.most_common(3))
        doc.notes.append(f"Converted {converted} blocks from an old Bijoy font encoding ({names}) to Unicode Bangla.")


def _convert_row(row: str) -> str:
    if set(row.replace("|", "").strip()) <= set("-: "):
        return row  # the line under the header
    return "|".join(to_unicode(cell) if cell.strip() else cell for cell in row.split("|"))
