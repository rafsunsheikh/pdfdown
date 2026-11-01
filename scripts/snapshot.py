"""Write the cleaned Markdown of every test document into a folder, to diff before and after a change (development helper).

    .venv/bin/python scripts/snapshot.py out/snap-before
"""
import os
import sys
from pathlib import Path

from pdfdown.cleanup import clean
from pdfdown.document import from_docling
from pdfdown.engine import convert
from pdfdown.export import write

DOCS = [*sorted(Path("corpus").glob("*.pdf")), *sorted(Path("out/examples-src").glob("[a-z]*.pdf")),
        Path(os.environ.get("PDFDOWN_NATURE_PDF", "s41586-025-09922-y.pdf"))]
out = Path(sys.argv[1])
for pdf in DOCS:
    if pdf.name in ("ultracold.pdf",) or not pdf.is_file():
        continue
    md = write(clean(from_docling(convert(pdf), pdf)), out / "full")
    (out / f"{pdf.stem}.md").write_text(md.read_text())
    print(pdf.stem)
