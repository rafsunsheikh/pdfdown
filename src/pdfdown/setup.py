"""`pdfdown setup`: download every model pdfdown can need, now instead of during the first conversion.

The installers run it, so the first PDF a user opens converts at full speed, and so a laptop that will later be
offline has everything. Each step loads an engine exactly as a conversion would, which makes it download its
model files into the usual caches; running it again only checks they are there.
"""

from __future__ import annotations

import sys
import time

STEPS = [
    ("layout", "Page layout, tables and English OCR models"),
    ("bangla", "Bangla OCR models"),
    ("speckled", "OCR model for speckled scans"),
    ("equations", "Equation reader"),
]


def _layout() -> None:
    from docling.datamodel.base_models import InputFormat

    from pdfdown.engine import EngineOptions, make_converter

    make_converter(EngineOptions(), do_ocr=True).initialize_pipeline(InputFormat.PDF)


def _bangla() -> None:
    from docling.datamodel.base_models import InputFormat

    from pdfdown import tesseract
    from pdfdown.engine import EngineOptions, make_converter

    tesseract.tessdata(("bn",))  # the Tesseract Bangla and script models
    if tesseract.available():
        make_converter(EngineOptions(ocr_engine="tesseract", ocr_lang=("bn",)), do_ocr=True).initialize_pipeline(InputFormat.PDF)


def _speckled() -> None:
    from docling.datamodel.base_models import InputFormat

    from pdfdown.engine import EngineOptions, make_converter

    make_converter(EngineOptions(ocr_engine="easyocr", ocr_lang=("bn", "en")), do_ocr=True).initialize_pipeline(InputFormat.PDF)


def _equations() -> None:
    from pdfdown.equations import Pix2Tex

    Pix2Tex()


ACTIONS = {"layout": _layout, "bangla": _bangla, "speckled": _speckled, "equations": _equations}


def run() -> int:
    print("pdfdown setup: downloading the models (about 1 GB the first time; later runs only check them).", flush=True)
    failed = []
    for i, (key, label) in enumerate(STEPS, start=1):
        print(f"  [{i}/{len(STEPS)}] {label} ...", end=" ", flush=True)
        start = time.time()
        try:
            ACTIONS[key]()
        except Exception as error:  # keep going: one engine missing should not stop the others
            failed.append(label)
            print(f"failed: {error}", flush=True)
            continue
        print(f"ready ({time.time() - start:.0f} s)", flush=True)
    if failed:
        print("Some models could not be downloaded (see above). pdfdown still works and will try again when it "
              "needs them; check the internet connection and run `pdfdown setup` again.", file=sys.stderr)
        return 1
    print("All set. Run `pdfdown` to open the app.")
    return 0
