"""Compare the equation check with and without the sub/superscript test (development helper)."""
import sys
from pathlib import Path
from types import SimpleNamespace
import pypdfium2 as pdfium
from pdfdown.engine import convert
from pdfdown.document import from_docling
from pdfdown.cleanup import clean
from pdfdown.pdftext import PdfText
from pdfdown.export import area, render
from pdfdown.equations import Pix2Tex, check, clean_latex, pdf_scripts

model = Pix2Tex()
for name in sys.argv[1:]:
    pdf = Path(name).expanduser()
    doc = clean(from_docling(convert(pdf), pdf))
    d, text = pdfium.PdfDocument(str(pdf)), PdfText(pdf)
    old = new = 0
    for i, b in enumerate(doc.of_kind("equation"), 1):
        page, box = area(b)
        chars = text.page(page).inside(box)
        latex, _ = clean_latex(model(render(d, page, box)))
        a = check(latex, [SimpleNamespace(ch=c.ch) for c in chars]).ok
        r = check(latex, chars)
        old += a; new += r.ok
        if a != r.ok:
            print(f"  {pdf.stem[:12]} eq{i}: was ok, now rejected: {r.reason}\n      {latex[:110]}\n      pdf small: {dict(pdf_scripts(chars))}")
    print(f"{pdf.stem}: {len(doc.of_kind('equation'))} equations, passed before {old}, after {new}")
