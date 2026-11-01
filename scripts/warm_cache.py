"""Run the engine on every test document once, so later steps read from the cache."""
import sys, time
from pathlib import Path
from pdfdown.engine import convert
for path in sys.argv[1:]:
    t = time.time()
    doc = convert(path, progress=lambda m: None)
    print(f"{Path(path).name}: {time.time() - t:.0f}s, {len(doc.pages)} pages", flush=True)
