"""Repair what OCR typically gets wrong in Bangla, on OCR pages only (text from a PDF's text layer is left alone).

Measured on a scanned letterpress novel:
  * the vowel sign া is read as ৷ (a Bengali currency sign that looks the same): "রান৷" for "রানা";
  * the দাঁড়ি । is read as ৷, 1 or | when it stands apart from the word, as old books print it ("হল ।");
  * closing quotes come out as * and opening ones as €;
  * dialogue lines, indented like list items, are taken for a list with no bullet.
"""

from __future__ import annotations

import re

from pdfdown.document import Document
from pdfdown.pdftext import bengali_share

CONSONANT = "ক-হড়-য়"


def fix_text(text: str) -> str:
    text = re.sub(f"(?<=[{CONSONANT}়])৷", "া", text)  # রান৷ -> রানা
    text = text.replace("৷", "।")  # a ৷ that is not after a letter is a দাঁড়ি
    text = re.sub(r"(?<=[ঀ-৿])(\s+)[1|l](?=['’”\"*]?(\s|$))", r"\1।", text)  # "হল 1" -> "হল ।"
    text = re.sub(r"(?<=[।?!])\s*\*", "'", text)  # "।*" -> "।'"
    text = re.sub(r"(?<=[ঀ-৿])\*(?=\s|$)", "'", text)
    text = re.sub(r"(?:^|(?<=\s))€(?=[ঀ-৿])", "'", text)
    return text


def run(doc: Document, pdf=None) -> None:
    pages = set(doc.ocr_pages)
    if not pages:
        return
    fixed = lists = 0
    for b in doc.blocks:
        if b.page not in pages or not b.text or bengali_share(b.text) < 0.5:
            continue
        new = fix_text(b.text)
        fixed += new != b.text
        b.text = new
        if b.kind == "list_item" and not b.extra.get("marker") and not re.match(r"\s*(?:[•●◦▪\-–]|[\d০-৯]+[.)])", b.text):
            b.kind = "paragraph"  # indented dialogue, not a list
            lists += 1
    numbers = _chapter_numbers(doc, pdf, pages)
    if numbers:
        doc.notes.append(f"Read {numbers} chapter numbers printed in large type (taken for pictures or misread).")
    if fixed or lists:
        doc.notes.append(f"Repaired common Bangla OCR misreadings in {fixed} blocks"
                         + (f" and turned {lists} indented lines without bullets back into paragraphs." if lists else "."))


NUMERAL = re.compile(r"[০-৯]{1,3}")


def _chapter_numbers(doc: Document, pdf, pages: set[int]) -> int:
    """A large chapter number ("১২") on a scanned page comes through as a small picture, or as a heading read wrong.

    Read each such crop again as one line of text; a Bangla number becomes the chapter heading.
    """
    from pdfdown import tesseract

    if pdf is None or not tesseract.available():
        return 0
    if sum(bengali_share(b.text) > 0.5 for b in doc.blocks if b.page in pages and b.text) < 5:
        return 0  # not a Bangla scan
    found = 0
    renders: dict[int, object] = {}
    for b in doc.blocks:
        if b.page not in pages or not b.box:
            continue
        width, height = doc.page_sizes.get(b.page, (0, 0))
        # large (twice the text size or more) and in the upper part of the page: not a page number in the footer
        large = 15 <= b.box.height < 0.12 * height and b.box.width < 0.25 * width and b.box.t < 0.6 * height
        picture = b.kind == "figure" and large and not b.extra.get("caption_refs")
        number_heading = b.kind == "heading" and NUMERAL.fullmatch(b.text.strip())
        if not (picture or number_heading):
            continue
        if b.page not in renders:
            renders[b.page] = pdf.pdf[b.page - 1].render(scale=300 / 72).to_pil()
        scale, pad = 300 / 72, 20  # white space around the number helps Tesseract
        crop = renders[b.page].crop((int((b.box.l - pad) * scale), int((b.box.t - pad) * scale),
                                     int((b.box.r + pad) * scale), int((b.box.b + pad) * scale)))
        text = tesseract.read_number(crop)
        if NUMERAL.fullmatch(text):
            b.kind, b.text, b.level = "heading", text, 1
            b.extra.pop("image", None)
            found += 1
    _fill_sequence([b for b in doc.blocks if b.kind == "heading" and b.page in pages and NUMERAL.fullmatch(b.text)])
    return found


DIGITS = "০১২৩৪৫৬৭৮৯"


def _number(text: str) -> int:
    return int("".join(str(DIGITS.index(ch)) for ch in text))


def _fill_sequence(chapters: list) -> None:
    """Chapters count up by one: a number between ৯ and ১১ is ১০, whatever OCR read ("৬০")."""
    for before, block, after in zip(chapters, chapters[1:], chapters[2:]):
        a, b = _number(before.text), _number(after.text)
        if b == a + 2 and _number(block.text) != a + 1:
            block.text = "".join(DIGITS[int(d)] for d in str(a + 1))
