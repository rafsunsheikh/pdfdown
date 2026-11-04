"""Small, fast checks of the rules, without models."""

from collections import Counter
from pathlib import Path

from pdfdown.cleanup.captions import number_of
from pdfdown.cleanup.stitch import ends_sentence
from pdfdown.equations import check, clean_latex
from pdfdown.pdftext import Char, _lines, _render_line, join_lines


def ch(text, l, top, size=10.0, idx=0):
    return Char(text, l, top, l + size * 0.5, top + size, size, False, idx)


def test_superscript_and_subscript_by_centre():
    line = [ch("x", 0, 100, idx=0), ch("2", 5, 98, size=6, idx=1), ch("t", 8, 100, idx=2), ch("0", 13, 105, size=6, idx=3)]
    assert _render_line(line) == "x<sup>2</sup>t<sub>0</sub>"


def test_spaces_follow_pdfium_order_not_position():
    # A generated space at the same x as the next letter, and a "j" that overhangs to the left of it.
    space = Char(" ", 10.85, 100, 10.85, 100, 0, True, 1)
    line = [ch("y", 5, 100, idx=0), space, Char("j", 10.16, 100, 13.6, 110, 10, False, 2), ch("o", 13.6, 100, idx=3)]
    assert _render_line(sorted(line, key=lambda c: (round(c.l * 2) / 2, c.idx))) == "y jo"


def test_two_line_title_is_not_interleaved():
    top = [ch(c, i * 6, 100, size=20, idx=i) for i, c in enumerate("Artificial")]
    bottom = [ch(c, i * 6, 121, size=20, idx=20 + i) for i, c in enumerate("science")]
    lines = _lines(bottom + top)
    assert ["".join(c.ch for c in line) for line in lines] == ["Artificial", "science"]


def test_hyphen_joining_uses_the_documents_own_words():
    vocab = Counter({"interpretation": 3, "state-of-the-art": 2})
    assert join_lines(["an interpre-", "tation of"], vocab) == "an interpretation of"
    assert join_lines(["AI-", "augmented papers"], vocab) == "AI-augmented papers"


def test_caption_numbers():
    assert number_of("Fig. 2 | AI enlarges paper impact") == ("figure", "2")
    assert number_of("Table 1: GLUE Test results") == ("table", "1")
    assert number_of("Extended Data Fig. 3 | Robustness") == ("figure", "ED3")
    assert number_of("Figure shows the trend") is None


def test_sentence_ends():
    assert ends_sentence("as shown before.") and ends_sentence("prior work<sup>12</sup>.")
    assert ends_sentence("in science<sup>10</sup>.") and not ends_sentence("on the basis of")


def test_latex_cleanup():
    latex, number = clean_latex(r"P(t)=\lambda e^{-\lambda t},t>0,\qquad\qquad(3)")
    assert (latex, number) == (r"P(t)=\lambda e^{-\lambda t},t>0 \tag{3}", "3")
    assert clean_latex(r"S=\underline{{1-x}}")[0] == "S={1-x}"


class FakeChar:
    def __init__(self, ch):
        self.ch = ch


def pdf_chars(text):
    return [FakeChar(c) for c in text if not c.isspace()]


def test_latex_must_match_the_pdf_letter_for_letter():
    pdf = pdf_chars("st=αxt+(1−α)st−1")
    assert check(r"s_{t}=\alpha x_{t}+(1-\alpha)s_{t-1}", pdf).ok
    wrong = check(r"S_{t}\longrightarrow Q X_{t}+(1-Q)S_{t-1}", pdf)  # pix2tex's reading of the office equation
    assert not wrong.ok and "Q" in wrong.reason
    typo = check(r"\mathrm{Atention}(Q)", pdf_chars("Attention(Q)"))
    assert not typo.ok and "missing" in typo.reason
    assert not check(r"\frac{a}{", pdf).ok  # does not render
    assert not check(r"x", pdf_chars("")).ok  # no text layer: cannot verify


def test_letters_must_sit_at_the_same_height():
    # "where head_i": the i is small in the PDF. pix2tex once wrote "headi", with every letter right.
    chars = [Char(c, 0, 0, 1, 1, 10.0, False) for c in "whereheadQ"] + [Char("i", 0, 0, 1, 1, 7.0, False)]
    assert check(r"\mathrm{where}\;\mathrm{head}_{i}Q", chars).ok
    flat = check(r"\mathrm{where\;headi}Q", chars)
    assert not flat.ok and "small in the PDF" in flat.reason


def test_preview_draws_scripts():
    from pdfdown.tui.app import preview

    assert preview("Hao<sup>1</sup>, prizes<sup>2–9</sup>, N(t<sub>0</sub>)") == "Hao¹, prizes²⁻⁹, N(t₀)"
    assert preview("BERT<sub>BASE</sub>") == "BERT_(BASE)"  # no Unicode for these: keep it readable
    assert preview("ω<sub>λ</sub>") == "ω_(λ)"


def test_letter_styles_must_match():
    def char(ch, font):
        return Char(ch, 0, 0, 1, 1, 10.0, False, 0, 10.0, font)

    pdf = [char("O", "LMMathSymbols10-Regular"), char("t", "LMMathItalic10-Regular"), char("r", "LMRoman10-Bold"),
           char("R", "MSBM10"), char("+", ""), char("∈", "")]
    assert check(r"\mathcal{O}(t)+\mathbf{r}\in\mathbb{R}", pdf).ok
    assert not check(r"O(t)+\mathbf{r}\in\mathbb{R}", pdf).ok  # "order of" read as a plain O
    assert not check(r"\mathcal{O}(t)+r\in\mathbb{R}", pdf).ok  # a vector read as a number


def test_accents_join_the_letter_beneath():
    # "Juzeli¯unas": the accent comes first; "Saule˙tekio": it comes after its letter, so use positions.
    def word(spec):
        return [Char(ch, x, 100, x + 5, 110, 10.0, False, i, 10.0) for i, (ch, x) in enumerate(spec)]

    assert _render_line(word([("l", 0), ("¯", 6.2), ("u", 5)])) == "lū"
    assert _render_line(word([("l", 0), ("e", 5), ("˙", 6.2), ("t", 10)])) == "lėt"
    assert _render_line(word([("n", 0), ("¨", 6), ("ı", 5), ("v", 10)])) == "nïv"


def test_hbar_from_a_blackboard_font_is_still_hbar():
    chars = [Char(c, 0, 0, 1, 1, 10.0, False, 0, 10.0, "LMMathItalic10-Regular") for c in "Ex"]
    chars += [Char("=", 0, 0, 1, 1, 10.0, False, 0, 10.0, ""), Char("ℏ", 0, 0, 1, 1, 10.0, False, 0, 10.0, "MSBM10")]
    assert check(r"E=\hbar x", chars).ok


def test_hat_goes_on_its_letter():
    # In DPO the hat over r comes before it in the PDF, and ˆ is itself a "letter" to Unicode.
    line = [Char("ˆ", 214.7, 166.3, 219.7, 175.1, 10.0, False, 0, 10.0), Char("r", 214.3, 166.3, 218.8, 175.1, 10.0, False, 1, 10.0)]
    assert _render_line(line) == "r̂"


def test_a_line_that_is_mostly_scripts():
    # "ŝ2j = s": more script characters than full-size ones must not make the scripts the "normal" size.
    def c(ch, x, top, pt, i):
        return Char(ch, x, top, x + 4, top + (9 if pt > 9 else 6), 9.0 if pt > 9 else 6.2, False, i, pt)

    line = [c("s", 0, 170.4, 9.96, 0), c("2", 4, 167.9, 6.97, 1), c("j", 4.5, 175.0, 6.97, 2), c("α", 9, 175, 6.97, 3),
            c("β", 13, 175, 6.97, 4), c("=", 18, 170.4, 9.96, 5)]
    assert _render_line(line).startswith("s<sup>2</sup><sub>jαβ</sub>")


def test_bangla_sentence_ends_and_continues():
    from pdfdown.cleanup.stitch import _continues

    assert ends_sentence("পদ্মা নদী বাংলাদেশের প্রধান নদী।")
    assert not ends_sentence("পদ্মা নদী বাংলাদেশের প্রধান")
    assert _continues("নদী। এটি হিমালয়ে উৎপন্ন")


def test_bijoy_to_unicode():
    import unicodedata

    from pdfdown.bijoy import is_bijoy_font, to_unicode

    cases = {
        "gvmy` ivbv": "মাসুদ রানা",
        "cvU©‡mi": "পার্টসের",       # reph before its consonant, ে after the next one
        "M‡Z©i": "গর্তের",
        "Awbw`©óKvj": "অনির্দিষ্টকাল",
        "Wvwj©s": "ডার্লিং",
        "†PvL": "চোখ",               # ে ... া is ো
        "†VuvU": "ঠোঁট",              # ঁ typed before the vowel sign
        "euvav": "বাঁধা",
        "wKš‘": "কিন্তু",             # no doubled ্
        "GwÄ‡b": "এঞ্জিনে",          # words that crashed the bijoy2unicode library
        "†b‡P": "নেচে",
        "h‡š¿i": "যন্ত্রের",          # the vowel sign typed inside a conjunct
        "BZ¯ÍZ": "ইতস্তত",           # ¯Í is স্ত
        "Aw¯’i": "অস্থির",
        "wew¯§Z": "বিস্মিত",
        "AšÍZ": "অন্তত",              # šÍ is ন্ত, not ন্ত্ম
        "wPšÍvq": "চিন্তায়",
        "AvZ¥v": "আত্মা",             # a real ত্ম
    }
    for bijoy, want in cases.items():
        assert unicodedata.normalize("NFC", to_unicode(bijoy)) == unicodedata.normalize("NFC", want), bijoy
    assert to_unicode("mgq").endswith("য়")  # য় stays one code point, so search finds it
    assert is_bijoy_font("LAMOAH+JugantorMJ") and is_bijoy_font("SutonnyMJ") and not is_bijoy_font("Times-Roman")
    assert is_bijoy_font("JugantorMJBold") and is_bijoy_font("SutonnyMJ-Italic")  # headings use the bold and italic cuts


def _book(blocks, pages=6):
    from pdfdown.document import Document

    return Document(source=Path("book.pdf"), blocks=blocks, page_sizes={p: (342.0, 504.0) for p in range(1, pages + 1)})


def test_running_header_merged_into_a_paragraph():
    from pdfdown.cleanup import furniture
    from pdfdown.document import Block, Box

    blocks = [Block("furniture", f"মুক্ত বিহঙ্গ-১ {p}", p, Box(36, 440, 300, 452)) for p in range(1, 7)]
    blocks.append(Block("paragraph", "৩৮ মুক্ত বিহঙ্গ-১ ১০৩ প্রথম বাঁকেই খুদে একটা রেস্তোরাঁ", 3, Box(36, 300, 300, 452)))
    blocks.append(Block("paragraph", "মুক্ত বিহঙ্গের মত উড়ে গেল", 4, Box(36, 300, 300, 452)))  # a word, not the header
    doc = _book(blocks)
    furniture.run(doc)
    assert [b.text for b in doc.blocks] == ["প্রথম বাঁকেই খুদে একটা রেস্তোরাঁ", "মুক্ত বিহঙ্গের মত উড়ে গেল"]


class _Sizes:
    """Stands in for PdfText: every block's letters have the size given by its text."""

    def __init__(self, sizes):
        self.sizes = sizes

    def page(self, number):
        return self

    def inside(self, box):
        return [Char("x", 0, 0, 1, 1, self.sizes[box.t], False)]


def test_chapter_title_taken_for_a_page_header():
    from pdfdown.cleanup import figures, furniture
    from pdfdown.document import Block, Box

    title = Block("furniture", "wZb", 3, Box(150, 67, 190, 90))          # তিন, once, large
    header = [Block("furniture", "gvmy` ivbv", p, Box(36, 20, 120, 31)) for p in range(1, 7)]
    text = [Block("paragraph", "...", p, Box(36, 100 + p, 300, 400)) for p in range(1, 7)]
    ornament = Block("figure", "", 3, Box(100, 50, 240, 95))
    doc = _book([ornament, title, *header, *text])
    sizes = {67: 20.7, 20: 15.7, 50: 0.0, **{100 + p: 15.7 for p in range(1, 7)}}
    furniture.rescue_headings(doc, _Sizes(sizes))
    assert title.kind == "heading" and all(h.kind == "furniture" for h in header)
    figures.drop_inner_text(doc)
    assert title in doc.blocks  # the only text on an uncaptioned picture: a chapter ornament, not a chart label


def test_bangla_ocr_repairs():
    from pdfdown.cleanup.bangla_ocr import fix_text

    assert fix_text("রান৷ হেসে") == "রানা হেসে"           # ৷ (a currency sign) after a letter is া
    assert fix_text("দরজা বন্ধ হল 1") == "দরজা বন্ধ হল ।"   # a lone 1 after a word is a দাঁড়ি
    assert fix_text("পরবে ৷") == "পরবে ।"
    assert fix_text("'তোমার স্যুটকেস ।*") == "'তোমার স্যুটকেস ।'"
    assert fix_text("১৯৭১ সালে 1971") == "১৯৭১ সালে 1971"   # real numbers stay


def test_chapter_numbers_count_up():
    from pdfdown.cleanup.bangla_ocr import _fill_sequence
    from pdfdown.document import Block

    chapters = [Block("heading", t) for t in ("৯", "৬০", "১১", "১২")]
    _fill_sequence(chapters)
    assert [b.text for b in chapters] == ["৯", "১০", "১১", "১২"]
    gap = [Block("heading", t) for t in ("৩", "৫", "৬")]  # ৪ is missing, not misread: nothing to fix
    _fill_sequence(gap)
    assert [b.text for b in gap] == ["৩", "৫", "৬"]


def test_language_choice(monkeypatch):
    from pdfdown import tesseract
    from pdfdown.engine import ocr_choice

    monkeypatch.setattr(tesseract, "available", lambda: True)
    assert ocr_choice("bn") == ("tesseract", ("bn",))
    assert ocr_choice("bn+en") == ("tesseract", ("bn", "en"))
    assert ocr_choice("Bangla") == ("tesseract", ("bn",))
    assert ocr_choice("en") == ("auto", ())
    monkeypatch.setattr(tesseract, "available", lambda: False)
    assert ocr_choice("bn") == ("easyocr", ("bn", "en"))
