"""Equations: image first, LaTeX only when it can be trusted.

Every display equation is cropped as an image by the exporter, so the
Markdown is complete at once. This module then reads each crop with an
equation model (pix2tex by default, under a second per equation on a laptop),
cleans the LaTeX, and accepts it only when it passes two checks:

1. it renders: latex2mathml converts it without errors;
2. it matches the PDF: the letters, digits and symbols in the LaTeX agree
   with the characters in the PDF's own text layer inside the equation's box.
   A model that reads "α" as "Q" fails this check.

When either check fails, or the PDF has no text layer for the equation (a
scanned page), the image stays. Each equation records why, for the TUI.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from pdfdown.document import Block, Document

# --------------------------------------------------------------- cleaning

_TRAILING_NUMBER = re.compile(r"(?:\\q?quad|\\[,;:!]|\\hspace\{[^}]*\}|~|\s)*\(\s*(\d+[a-z]?)\s*\)\s*\.?\s*$")


def clean_latex(latex: str) -> tuple[str, str | None]:
    """Tidy model output; returns (latex, equation number or None)."""
    latex = latex.strip().strip("$").strip()
    number = None
    m = _TRAILING_NUMBER.search(latex)
    if m:
        number = m.group(1)
        latex = latex[: m.start()]
    latex = re.sub(r"(?:\\q?quad|\\[,;:!]|\s)+$", "", latex)  # trailing spacing
    latex = _strip_command(latex, "underline")  # a model artefact; equations almost never underline
    latex = re.sub(r"[,.]\s*$", "", latex) if number else latex
    latex = re.sub(r"(?<![\\\w])((?:[A-Za-z] ){2,}[A-Za-z])(?![\w])",
                   lambda m: r"\mathrm{" + m.group(1).replace(" ", "") + "}", latex)  # "A t t e n t i o n"
    latex = re.sub(r"\s+", " ", latex).strip()
    if number:
        latex = f"{latex} \\tag{{{number}}}"
    return latex, number


def _strip_command(latex: str, name: str) -> str:
    """\\underline{x} -> x, keeping balanced braces."""
    key = "\\" + name + "{"
    while key in latex:
        start = latex.index(key)
        depth, i = 1, start + len(key)
        while i < len(latex) and depth:
            depth += {"{": 1, "}": -1}.get(latex[i], 0)
            i += 1
        latex = latex[:start] + latex[start + len(key): i - 1] + latex[i:]
    return latex


# --------------------------------------------------------------- checks

_IGNORE = set(" ,.;:()[]{}|!'′√\u2009\u200a\u00a0")  # MathML draws roots without a √ character
_SAME = {"−": "-", "–": "-", "∗": "*", "×": "*", "·": "*", "⋅": "*", "∣": "|", "′": "'", "→": "->", "⟶": "->"}


def _norm_symbol(ch: str) -> str:
    import unicodedata

    ch = _SAME.get(ch, ch)
    if ord(ch[0]) >= 0x1D400:  # 𝑥 -> x
        ch = unicodedata.normalize("NFKC", ch)
    return ch


# Letter styles change meaning in equations: bold r is a vector, r a number; calligraphic O is "order of".
# A styled letter counts as its own symbol, written "bold:r", "cal:O" or "bb:R".
_VARIANT_STYLE = {"bold": "bold", "bold-italic": "bold", "bold-sans-serif": "bold", "sans-serif-bold-italic": "bold",
                  "script": "cal", "bold-script": "cal", "double-struck": "bb", "fraktur": "frak", "bold-fraktur": "frak"}
_FONT_STYLES = [("bb", re.compile(r"MSBM|BBold|DoubleStruck", re.I)),
                ("cal", re.compile(r"CMSY|LMSY|MathSymbols|RSFS|EUSM|Script", re.I)),
                ("bold", re.compile(r"Bold|CMBX|CMMIB|CMBSY|LMMIB|-Bd\b|Semibold", re.I))]


def _unicode_style(ch: str) -> str:
    import unicodedata

    if ord(ch) < 0x2100:
        return ""
    name = unicodedata.name(ch, "")
    if "DOUBLE-STRUCK" in name:
        return "bb"
    if "SCRIPT" in name:
        return "cal"
    if "FRAKTUR" in name or "BLACK-LETTER" in name:
        return "frak"
    if "MATHEMATICAL BOLD" in name or "MATHEMATICAL SANS-SERIF BOLD" in name:
        return "bold"
    return ""


def _styled(ch: str, style: str = "") -> str:
    import unicodedata

    style = _unicode_style(ch) or style
    base = _norm_symbol(ch)
    plain = unicodedata.normalize("NFKC", base)  # ℝ -> R, ℬ -> B, 𝐫 -> r
    if not plain.isalpha():
        return base  # digits and operators: a bold 1 is still a 1
    if not style or (style in ("cal", "bb", "frak") and not plain.isupper()):
        return plain  # these styles are for capitals (𝒪, ℝ); TeX also draws ℏ and ℓ from such fonts. Ω (ohm) -> Ω
    return f"{style}:{plain}"


def _pdf_style(c) -> str:
    font = getattr(c, "font", "")
    for style, pattern in _FONT_STYLES:
        if font and pattern.search(font):
            return style
    return ""


def latex_symbols(latex: str) -> Counter | None:
    """Letters, digits and operators in the LaTeX, via MathML. None when it does not render."""
    import latex2mathml.converter

    try:
        mathml = latex2mathml.converter.convert(re.sub(r"\\tag\{[^}]*\}", "", latex))
    except Exception:
        return None
    out: Counter = Counter()
    for digit in "".join(re.findall(r"\\tag\{([^}]*)\}", latex)):
        out[digit] += 1  # the equation number is printed in the PDF too
    for tag, attrs, text in re.findall(r"<(mi|mn|mo|mtext)([^>]*)>([^<]*)</\1>", mathml):
        text = html.unescape(text)
        variant = re.search(r'mathvariant="([^"]+)"', attrs)
        style = _VARIANT_STYLE.get(variant.group(1), "") if variant else ""
        for ch in text:  # "softmax", "max": each letter counts
            if ch not in _IGNORE:
                out[_styled(ch, style)] += 1
    return out


_SCRIPTED = {"msub", "msup", "msubsup", "munder", "mover", "munderover", "mroot"}


def latex_scripts(latex: str) -> Counter | None:
    """Letters and digits the LaTeX puts in subscripts, superscripts, limits and root indices."""
    import xml.etree.ElementTree as ET

    import latex2mathml.converter

    try:
        root = ET.fromstring(latex2mathml.converter.convert(re.sub(r"\\tag\{[^}]*\}", "", latex)))
    except Exception:
        return None
    out: Counter = Counter()

    def walk(element, scripted: bool) -> None:
        tag = element.tag.rsplit("}", 1)[-1]
        children = list(element)
        if tag in _SCRIPTED and children:
            walk(children[0], scripted)
            for child in children[1:]:
                walk(child, True)
            return
        if scripted and tag in ("mi", "mn", "mo", "mtext"):
            for ch in html.unescape(element.text or ""):
                if ch.isalnum():
                    out[_norm_symbol(ch)] += 1
        for child in children:
            walk(child, scripted)

    walk(root, False)
    return out


def pdf_scripts(chars) -> Counter:
    """Letters and digits the PDF draws small: a size below 0.82 of the equation's main size, as in pdftext."""
    import statistics

    def size(c) -> float:
        return getattr(c, "pt", 0) or c.size  # the true point size when the PDF gives it

    sized = sorted((c for c in chars if c.ch.strip() and size(c) > 0), key=size)
    if not sized:
        return Counter()
    main = statistics.median(size(c) for c in sized[len(sized) // 2:])  # big operators and scripts do not move it
    return Counter(_norm_symbol(ch) for c in sized if size(c) < 0.82 * main for ch in c.ch if ch.isalnum())


def pdf_symbols(chars) -> Counter:
    out: Counter = Counter()
    for c in chars:
        for ch in c.ch:
            if ch.strip() and ch not in _IGNORE:
                out[_styled(ch, _pdf_style(c))] += 1
    return out


@dataclass
class Check:
    ok: bool
    reason: str
    precision: float = 0.0  # share of the LaTeX's symbols that the PDF has
    recall: float = 0.0  # share of the PDF's symbols that the LaTeX has


def check(latex: str, chars) -> Check:
    symbols = latex_symbols(latex)
    if symbols is None:
        return Check(False, "the LaTeX does not render")
    pdf = pdf_symbols(chars)
    if sum(pdf.values()) < 3:
        return Check(False, "the PDF has no text layer for this equation, so the LaTeX cannot be verified")
    common = sum((symbols & pdf).values())
    precision = common / max(sum(symbols.values()), 1)
    recall = common / max(sum(pdf.values()), 1)
    # Letters and digits must match the PDF exactly, count for count: a model that writes
    # "Atention", "d_mode" or "V V" for "V W" looks plausible but is wrong. Brackets, bars and
    # operators may differ a little, because PDFs often draw them as lines rather than characters.
    alnum_latex = Counter({k: v for k, v in symbols.items() if k.split(":")[-1].isalnum()})
    alnum_pdf = Counter({k: v for k, v in pdf.items() if k.split(":")[-1].isalnum()})
    extra, missing = alnum_latex - alnum_pdf, alnum_pdf - alnum_latex
    if extra:
        return Check(False, f"the LaTeX has symbols the PDF does not: {_show(extra)}", precision, recall)
    if symbols["-"] != pdf["-"]:  # a minus is always a character in the PDF; "GPU-h" read as "GPU. h" changes the text
        return Check(False, f"the LaTeX has {symbols['-']} minus signs, the PDF {pdf['-']}", precision, recall)
    if missing:
        return Check(False, f"the LaTeX is missing symbols the PDF has: {_show(missing)}", precision, recall)
    # The same letters can still sit at the wrong height: "headi" for head with a subscript i.
    if any(getattr(c, "size", 0) for c in chars):
        small_latex, small_pdf = latex_scripts(latex) or Counter(), pdf_scripts(chars)
        if small_latex != small_pdf:
            wrong = (small_pdf - small_latex) or (small_latex - small_pdf)
            where = "small in the PDF but not a sub- or superscript in the LaTeX" if small_pdf - small_latex \
                else "a sub- or superscript in the LaTeX but full size in the PDF"
            return Check(False, f"{_show(wrong)} is {where}", precision, recall)
    if precision < 0.9 or recall < 0.9:
        return Check(False, f"the LaTeX matches only {min(precision, recall):.0%} of the PDF's symbols", precision, recall)
    return Check(True, f"matches the PDF ({precision:.0%} / {recall:.0%})", precision, recall)


def _show(counts: Counter) -> str:
    return " ".join(k if n == 1 else f"{k}×{n}" for k, n in counts.most_common(6))


# --------------------------------------------------------------- models


class Pix2Tex:
    """pix2tex (LaTeX-OCR, MIT licence). Loads once; under a second per equation on a laptop."""

    name = "pix2tex"

    def __init__(self) -> None:
        import sys
        import warnings

        # pix2tex imports readline, which on macOS (libedit) switches the terminal back to line mode
        # with echo: inside the TUI, keys stop arriving and mouse moves print as text. Its import is
        # optional in pix2tex, so make it fail; pdfdown never needs readline.
        sys.modules.setdefault("readline", None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pix2tex.cli import LatexOCR

            self._model = LatexOCR()
        self._model.args.temperature = 1e-8  # always the most likely reading: the same PDF gives the same LaTeX

    def __call__(self, image) -> str:
        return self._model(image)


def recognise(doc: Document, root, pdf_text, model: Callable | None = None,
              progress: Callable[[int, int, Block], None] | None = None) -> int:
    """Fill in LaTeX for every equation that has an image; returns how many passed the checks."""
    from PIL import Image

    equations = [b for b in doc.blocks if b.kind == "equation" and b.extra.get("image") and not b.extra.get("latex_by")]
    if not equations:
        return 0
    model = model or Pix2Tex()
    passed = 0
    for i, b in enumerate(equations, start=1):
        raw = model(Image.open(root / b.extra["image"]))
        latex, number = clean_latex(raw)
        chars = [c for page, box in b.parts for c in pdf_text.page(page).inside(box)]
        result = check(latex, chars)
        b.extra.update(latex=latex, latex_raw=raw, latex_ok=result.ok, latex_check=result.reason,
                       latex_model=getattr(model, "name", "custom"))
        if number:
            b.extra["number"] = number
        passed += result.ok
        if progress:
            progress(i, len(equations), b)
    n = len(equations)
    doc.notes.append(f"Read {n} equation{'s' * (n != 1)} as LaTeX: {passed} passed the checks and replace their images, "
                     f"{n - passed} stay as images.")
    return passed


def try_harder(block: Block, pdf, pdf_text, model: Callable | None = None,
               progress: Callable[[int, int], None] | None = None) -> Check:
    """Read the equation again from crops at other sizes and margins; keep the first reading that passes.

    The model reads small or tightly cropped equations worse, so a sharper or roomier crop often
    fixes one wrong symbol. Ten readings take a few seconds. When none passes, the reading closest
    to the PDF is kept for the person to fix by hand, and the image stays in the Markdown.
    """
    from pdfdown.export import area, render

    model = model or Pix2Tex()
    page, box = area(block)
    chars = [c for c in pdf_text.page(page).inside(box)]
    tries = [(scale, pad) for scale in (3.0, 4.0, 2.0, 5.0) for pad in (3.0, 8.0, 1.0)][:10]
    best: tuple[float, str, str, Check] | None = None
    for i, (scale, pad) in enumerate(tries, start=1):
        raw = model(render(pdf, page, box, scale=scale, pad=pad))
        latex, _number = clean_latex(raw)
        result = check(latex, chars)
        score = 2.0 if result.ok else min(result.precision, result.recall)
        if best is None or score > best[0]:
            best = (score, latex, raw, result)
        if progress:
            progress(i, len(tries))
        if result.ok:
            break
    _score, latex, raw, result = best
    block.extra.update(latex=latex, latex_raw=raw, latex_ok=result.ok, latex_check=result.reason,
                       latex_model=getattr(model, "name", "custom"), latex_by="try harder")
    return result
