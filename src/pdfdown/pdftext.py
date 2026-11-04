"""Read text straight from the PDF's characters, with size and position.

Docling's text drops two things research articles depend on: superscripts
(citations such as "discovery¹", "AI²⁻⁹") and subscripts ("BERT_BASE"), and it
keeps the PDF's line breaks and end-of-line hyphens. This module rebuilds the
text of a block from pypdfium2's character boxes:

* characters whose centre lies inside the block's box are collected,
* grouped into lines by baseline,
* marked as superscript or subscript when they are clearly smaller than the
  line's main text and raised or lowered,
* lines are joined with spaces, and end-of-line hyphens are removed only when
  the document itself suggests the word is not normally hyphenated.
"""

from __future__ import annotations

import bisect
import re
import ctypes
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from pdfdown.document import Box

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}

# TeX's big-symbol font (cmex) has no Unicode map in many PDFs, so its glyphs come out as the ASCII
# letters at their positions: "X" for a display sum, "p" for a root, '"' and "#" for big brackets.
# Known operators are translated; everything else in that font is a delimiter or a piece of one.
CMEX = {"P": "∑", "X": "∑", "Q": "∏", "Y": "∏", "R": "∫", "Z": "∫", "S": "∮", "[": "∮",
        "T": "⋃", "\\": "⋃", "U": "⋂", "]": "⋂", "W": "⋀", "_": "⋀", "o": "⋁", "a": "∐", "`": "∐",
        "p": "√", "q": "√", "r": "√", "s": "√", "t": "√"}
BIG_SYMBOL_FONTS = re.compile(r"CMEX|MathExtension|LMEX|TXEX|PXEX|EUEX", re.I)  # Computer and Latin Modern, tx/px fonts


@dataclass
class Char:
    ch: str
    l: float
    t: float
    r: float
    b: float  # top-left origin, points
    size: float
    generated: bool  # a space pdfium inferred between words
    idx: int = 0  # pdfium's order; breaks ties when two characters start at the same x
    pt: float = 0.0  # the true point size (font size times the text's scale); 0 when unknown
    font: str = ""  # font name, for letters and digits only: equations use it to tell bold and calligraphic letters


class PageText:
    """All characters of one page, with a fast lookup by box."""

    def __init__(self, page: pdfium.PdfPage):
        self.height = page.get_height()
        self.width = page.get_width()
        tp = page.get_textpage()
        self.chars: list[Char] = []
        font_name = ctypes.create_string_buffer(256)
        matrix = pdfium_c.FS_MATRIX()
        for i in range(tp.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(tp.raw, i)
            ch = chr(code) if code else ""
            if ch == "\x02":
                ch = "-"  # pdfium's marker for a hyphen at the end of a line
            if not ch or ch in "\r\n":
                continue
            # Loose boxes are sized by the font, not the glyph: letters on a line share a height and
            # touch their neighbours. FPDFText_GetFontSize is unreliable (1.0 in PDFs that scale text
            # through the text matrix, like Nature's), so the loose box height is the font size.
            l, bottom, r, top = tp.get_charbox(i, loose=True)
            size = top - bottom
            generated = bool(pdfium_c.FPDFText_IsGenerated(tp.raw, i))
            font = _font(tp, i, font_name) if not generated and (ch.isascii() or ch.isalnum()) else ""
            if font and ch.isascii() and BIG_SYMBOL_FONTS.search(font):
                ch = CMEX.get(ch, "")
                if not ch:
                    continue
            if not -1 <= (l + r) / 2 <= self.width + 1 or not -1 <= self.height - (bottom + top) / 2 <= self.height + 1:
                continue  # off the page: some books are cut from two-page spreads that keep the other half beside it
            self.chars.append(Char(LIGATURES.get(ch, ch), l, self.height - top, r, self.height - bottom, size, generated, i,
                                   _point_size(tp, i, matrix), font if ch.isalnum() else ""))

    def text_in(self, box: Box) -> str:
        """The text in a box in the order the PDF stores it, not by position (Bijoy blocks need it: their vowel
        signs are stored before or after the letter they sit on). A character belongs to the box its centre is in,
        so a vowel sign hanging below the last line of one paragraph does not start the next one."""
        out, last = [], None
        for c in sorted(self.inside(box), key=lambda c: c.idx):
            if last is not None and c.idx > last + 1 and out and not out[-1].isspace() and not c.ch.isspace():
                out.append(" ")  # a line break pdfium stored between them
            out.append(c.ch)
            last = c.idx
        return "".join(out)

    def inside(self, box: Box, slack: float = 1.0) -> list[Char]:
        return [c for c in self.chars
                if box.l - slack <= (c.l + c.r) / 2 <= box.r + slack and box.t - slack <= (c.t + c.b) / 2 <= box.b + slack]


def _point_size(tp, index: int, matrix) -> float:
    """Font size times the vertical scale of the text matrix.

    The loose box height differs from font to font (TeX's roman and math italic fonts give 14.1 and 10.0
    at the same 10 pt), so equations, which mix fonts, need this to tell scripts from full-size symbols.
    """
    size = pdfium_c.FPDFText_GetFontSize(tp.raw, index)
    if not pdfium_c.FPDFText_GetMatrix(tp.raw, index, ctypes.byref(matrix)):
        return size
    return size * (matrix.c ** 2 + matrix.d ** 2) ** 0.5


def _font(tp, index: int, buffer) -> str:
    flags = ctypes.c_int()
    pdfium_c.FPDFText_GetFontInfo(tp.raw, index, buffer, ctypes.sizeof(buffer), ctypes.byref(flags))
    return buffer.value.decode("latin-1", "replace")


class PdfText:
    def __init__(self, path: str | Path):
        self.pdf = pdfium.PdfDocument(str(path))
        self._pages: dict[int, PageText] = {}

    def text_in(self, number: int, box: Box) -> str:
        return self.page(number).text_in(box)

    def page(self, number: int) -> PageText:
        if number not in self._pages:
            self._pages[number] = PageText(self.pdf[number - 1])
        return self._pages[number]

    def close(self) -> None:
        self.pdf.close()


def _lines(chars: list[Char]) -> list[list[Char]]:
    """Group characters into lines, left to right, top to bottom.

    Full-size characters form the lines, by the distance between their centres
    (not by box edges, which overlap on tightly set titles). Small characters
    (superscripts, subscripts) then join the line they overlap most, so a
    citation at the start of a line is not mistaken for a subscript of the
    line above.
    """
    body = [c for c in chars if c.ch.strip()]
    if not body:
        return []
    # Box heights, not point sizes, decide which characters anchor the lines: inline math in another font
    # has the same point size but boxes at a different height, and joins its line by overlap like a script.
    main = statistics.median(c.size for c in body)
    full = [c for c in chars if c.size >= 0.85 * main or not c.ch.strip()]
    small = [c for c in chars if c.ch.strip() and c.size < 0.85 * main]
    lines: list[list[Char]] = []
    centres: list[float] = []
    for c in sorted(full, key=lambda c: ((c.t + c.b) / 2, c.l)):
        mid = (c.t + c.b) / 2
        for k, centre in enumerate(centres):
            if abs(mid - centre) < 0.4 * (max(c.size, main * 0.5) if c.ch.strip() else main):
                lines[k].append(c)
                break
        else:
            lines.append([c])
            centres.append(mid)
    for c in sorted(small, key=lambda c: c.ch in _ACCENTS):  # accents last, once their letters have a line
        if c.ch in _ACCENTS:
            home = _accent_line(c, lines)
            if home is not None:
                lines[home].append(c)
                continue
        best, best_overlap = None, 0.0
        for k, line in enumerate(lines):
            top = min(x.t for x in line)
            bottom = max(x.b for x in line)
            overlap = min(c.b, bottom) - max(c.t, top)
            if overlap > best_overlap:
                best, best_overlap = k, overlap
        if best is None:
            lines.append([c])
        else:
            lines[best].append(c)
    for line in lines:
        # Sort left to right; on ties (a generated space sits exactly at the next letter's x) keep pdfium's order.
        line.sort(key=lambda c: (round(c.l * 2) / 2, c.idx))
    lines.sort(key=lambda line: statistics.median((c.t + c.b) / 2 for c in line if c.ch.strip()) if any(c.ch.strip() for c in line) else 0)
    return [line for line in lines if any(c.ch.strip() for c in line)]


def _render_line(line: list[Char]) -> str:
    """One line of text, with <sup>/<sub> marks and spaces from the PDF's gaps."""
    line, composed = _attach_accents(line)
    sized = [c for c in line if c.ch.strip()]
    if not sized:
        return ""
    main = statistics.median(c.size for c in sized)  # geometry: gaps and heights
    sizes = sorted(_pt(c) for c in sized)
    pt_main = statistics.median(sizes[len(sizes) // 2:])  # the text size, even when a line is mostly scripts
    full = [c for c in sized if _pt(c) >= 0.85 * pt_main] or sized
    line_mid = statistics.median((c.t + c.b) / 2 for c in full)
    out: list[str] = []
    mode = ""
    prev: Char | None = None
    # Spaces are placed by pdfium's order, not by position: a space goes between two letters when
    # pdfium emitted one between them. (Letters like "j" overhang to the left of the space's x.)
    space_idx = sorted(c.idx for c in line if not c.ch.strip())
    for c in [c for c in line if c.ch.strip()]:
        if prev is not None and out and not out[-1].endswith(" "):
            lo, hi = sorted((prev.idx, c.idx))
            k = bisect.bisect_right(space_idx, lo)
            if k < len(space_idx) and space_idx[k] < hi:
                out.append(" ")
        small = _pt(c) < 0.82 * pt_main and c.ch not in BIG_OPERATORS
        new_mode = ""
        if small:
            # A small character above the line's centre is a superscript, below it a subscript.
            # Fonts lower subscripts very little (Nature's t0: 0.7 pt), so compare centres, not edges.
            centre = (c.t + c.b) / 2
            if centre < line_mid - 0.12 * main:
                new_mode = "sup"
            elif centre > line_mid + 0.12 * main:
                new_mode = "sub"
            elif mode and out and (out[-1] != " " or (len(out) > 1 and out[-2].endswith(","))):
                new_mode = mode  # in between, right after a script: it continues it ("1, †" after an author)
        if (prev is not None and prev.ch.strip() and c.l - prev.r > 0.12 * main and out and not out[-1].endswith(" ")
                and not (_bengali(prev.ch) and _bengali(c.ch))):  # Bangla leaves gaps inside words: trust the PDF's spaces
            out.append(" ")  # a visible gap without an explicit space character
        if new_mode != mode:
            if mode:
                if out and out[-1] == " ":
                    out.pop()
                    out.append(f"</{mode}> ")
                else:
                    out.append(f"</{mode}>")
            if new_mode:
                if out and out[-1] == " " and new_mode == "sup":
                    out.pop()  # "discovery ¹" -> "discovery<sup>1</sup>"
                out.append(f"<{new_mode}>")
            mode = new_mode
        out.append(composed.get(id(c), c.ch))
        prev = c
    if mode:
        out.append(f"</{mode}>")
    text = "".join(out)
    return re.sub(r"\s+", " ", text).strip()


BIG_OPERATORS = set("√∑∏∫∮⋃⋂⋀⋁∐")  # drawn from small fonts but hanging low; never a script themselves


def bengali_share(text: str) -> float:
    """Share of the letters in `text` that are Bengali script."""
    letters = [ch for ch in text if ch.isalpha() or _bengali(ch)]
    return sum(_bengali(ch) for ch in letters) / len(letters) if letters else 0.0


def _bengali(ch: str) -> bool:
    return any("\u0980" <= x <= "\u09ff" for x in ch)


def _pt(c: Char) -> float:
    """The size that tells scripts from text. Box heights differ between fonts at the same size (TeX's bold
    and symbol fonts come out smaller), so use the true point size when the PDF gives it."""
    return c.pt if c.pt > 0 else c.size


# TeX draws an accent as its own character placed over its letter: "Juzeliūnas" arrives as "Juzeli¯unas", and
# "Saulėtekio" as "Saule˙tekio" (the dot after its e). Each accent joins the letter it sits over.
_ACCENTS = {"¨": "\u0308", "´": "\u0301", "`": "\u0300", "ˆ": "\u0302", "˜": "\u0303", "¯": "\u0304",
            "ˇ": "\u030c", "˘": "\u0306", "˙": "\u0307", "˚": "\u030a", "¸": "\u0327", "˝": "\u030b", "˛": "\u0328"}


def _sits_on(accent: Char, letter: Char) -> bool:
    """The accent is over (or, for a cedilla, on) this letter, not a line away."""
    centre, middle, height = (accent.l + accent.r) / 2, (accent.t + accent.b) / 2, letter.b - letter.t
    return (letter.l - 0.5 <= centre <= letter.r + 0.5
            and letter.t - 0.7 * height <= middle <= letter.t + 0.65 * height)


def _accent_line(accent: Char, lines: list[list[Char]]) -> int | None:
    """The line holding the letter an accent sits on. A tall neighbouring line (a big ∑) can overlap the
    accent more than its own line does, so accents do not join lines by overlap."""
    for k, line in enumerate(lines):
        if any((c.ch.isalpha() or c.ch in "ıȷ") and c.ch not in _ACCENTS and _sits_on(accent, c) for c in line):
            return k
    return None


def _attach_accents(line: list[Char]) -> tuple[list[Char], dict[int, str]]:
    import unicodedata

    accents = [c for c in line if c.ch in _ACCENTS]
    if not accents:
        return line, {}
    letters = [c for c in line if (c.ch.isalpha() or c.ch in "ıȷ") and c.ch not in _ACCENTS]  # ˆ and ˇ count as letters in Unicode
    composed: dict[int, str] = {}
    used: set[int] = set()
    for a in accents:
        used.add(id(a))  # an accent with no letter beneath it belongs to text outside this block: drop it
        centre = (a.l + a.r) / 2
        under = [c for c in letters if _sits_on(a, c)]
        if not under:
            continue
        letter = min(under, key=lambda c: abs((c.l + c.r) / 2 - centre))
        base = composed.get(id(letter), {"ı": "i", "ȷ": "j"}.get(letter.ch, letter.ch))
        composed[id(letter)] = unicodedata.normalize("NFC", base + _ACCENTS[a.ch])
    return [c for c in line if id(c) not in used], composed


_HYPHEN_END = re.compile(r"([A-Za-z]+)-$")
_WORD_START = re.compile(r"^([a-z]+)")


def join_lines(lines: list[str], vocabulary: Counter | None = None) -> str:
    """Join lines into one paragraph, removing end-of-line hyphenation where it is safe."""
    out = ""
    for line in lines:
        if not line:
            continue
        if not out:
            out = line
            continue
        m, n = _HYPHEN_END.search(out), _WORD_START.match(line)
        if m and n:
            left, right = m.group(1), n.group(1)
            hyphenated, joined = f"{left}-{right}".lower(), f"{left}{right}".lower()
            keep = False
            if vocabulary is not None:
                keep = vocabulary[hyphenated] > vocabulary[joined]
            if left[-1].isupper() or any(ch.isdigit() for ch in left):
                keep = True  # "AI-" + "augmented", "COVID-" + "19"
            out = out[:-1] + ("-" if keep else "") + line
        else:
            out = out + " " + line
    return out


def block_text(pdf: PdfText, parts: list[tuple[int, Box]], vocabulary: Counter | None = None) -> tuple[str, int]:
    """Text of a block (all its parts, possibly on several pages). Returns (text, number of characters seen)."""
    rendered: list[str] = []
    seen = 0
    for page, box in parts:
        chars = pdf.page(page).inside(box)
        seen += len(chars)
        rendered.extend(_render_line(line) for line in _lines(chars))
    return join_lines(rendered, vocabulary), seen


def vocabulary(pdf: PdfText, pages: list[int]) -> Counter:
    """Word counts from the whole document, used to decide end-of-line hyphens."""
    counts: Counter = Counter()
    for p in pages:
        pieces: list[str] = []
        prev: Char | None = None
        for c in pdf.page(p).chars:
            if prev is not None and abs((c.t + c.b) / 2 - (prev.t + prev.b) / 2) > 0.5 * max(prev.size, 1):
                pieces.append("\n")  # a new line: "interpre-" and "tation" must not count as one hyphenated word
            pieces.append(c.ch)
            prev = c
        text = "".join(pieces)
        counts.update(w.lower() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", text))
    return counts
