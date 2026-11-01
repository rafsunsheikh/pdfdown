"""Small, fast checks of the rules, without models."""

from collections import Counter

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
