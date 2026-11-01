"""Convert one PDF end to end and print the cleanup notes (development helper)."""
import sys, time
from pdfdown.cleanup import clean
from pdfdown.document import from_docling
from pdfdown.engine import convert
from pdfdown.export import write
src, out = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out"
t = time.time()
doc = clean(from_docling(convert(src), src))
md = write(doc, out)
print(f"{md}  ({time.time() - t:.1f}s)")
for note in doc.notes:
    print(" -", note)
