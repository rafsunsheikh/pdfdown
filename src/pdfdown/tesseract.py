"""Tesseract for Bangla scans: its models, its settings, and finding out which script a scanned page is in.

Measured on a scanned 1970s letterpress novel (see the README): Tesseract's Bangla model got 5.5% to 8.6% of the
letters wrong where EasyOCR got 34%, and it is faster. Tesseract comes inside the tesserocr package, a pdfdown
dependency with prebuilt files for macOS 15 and later, Linux and Windows, so nothing has to be installed by hand.
An installed `tesseract` program (Homebrew brings it) is used first, because it reads whole pages and does a little
better on old print. pdfdown downloads the Bangla model (11 MB, Apache 2.0) into its cache the first time. Without
either, Bangla falls back to EasyOCR.

Heavy bold Bangla in old books is often read as Latin letters ("ঠিক" as "OB"). When the user has not asked for
English, Latin letters are switched off, and Tesseract then picks the Bangla reading.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

MODELS = {
    "ben": "https://github.com/tesseract-ocr/tessdata_best/raw/main/ben.traineddata",
    "eng": "https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata",
    "osd": "https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata",  # page orientation and script
}
CODES = {"bn": "ben", "en": "eng"}
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BANGLA_DIGITS = "০১২৩৪৫৬৭৮৯"
_blacklist = {"latin": False}  # read by the hook on Docling's Tesseract model (see _hook_docling)


def library() -> bool:
    """Is the bundled Tesseract (the tesserocr package) usable here?"""
    try:
        import tesserocr  # noqa: F401
    except ImportError:
        return False
    return True


def program() -> bool:
    return shutil.which("tesseract") is not None


def available() -> bool:
    return library() or program()


def _model(code: str, say=None) -> Path:
    from pdfdown.engine import cache_dir

    folder = cache_dir() / "tessdata" / "models"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{code}.traineddata"
    if path.is_file():
        return path
    if say:
        say(f"Downloading Tesseract's {code} model (once)")
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(MODELS[code], timeout=120) as response, open(tmp, "wb") as f:
        shutil.copyfileobj(response, f)
    tmp.replace(path)
    return path


def tessdata(languages: tuple[str, ...], say=None) -> Path:
    """A tessdata folder with the models for `languages` (pdfdown codes: bn, en), for both ways of running Tesseract.

    Without English, Latin letters are switched off: through the hook for the library, and through the settings file
    the program reads (configs/tsv).
    """
    from pdfdown.engine import cache_dir

    codes = [CODES.get(lang, lang) for lang in languages]
    folder = cache_dir() / "tessdata" / "+".join(codes)
    (folder / "configs").mkdir(parents=True, exist_ok=True)
    for code in [*codes, "osd"]:
        target = folder / f"{code}.traineddata"
        if not target.exists():
            shutil.copyfile(_model(code, say), target)
    settings = "tessedit_create_tsv 1\n"  # tsv: Docling reads word boxes from it
    if "eng" not in codes:
        settings += f"tessedit_char_blacklist {LATIN}\n"
    (folder / "configs" / "tsv").write_text(settings, encoding="utf-8")
    os.environ["TESSDATA_PREFIX"] = str(folder)  # Docling lists the installed languages without passing the folder
    _blacklist["latin"] = "eng" not in codes
    _hook_docling()
    # A cover or a blank page has too few letters to tell its orientation; Docling logs an error and carries on
    for name in ("tesseract_ocr_cli_model", "tesseract_ocr_model"):
        logging.getLogger(f"docling.models.stages.ocr.{name}").setLevel(logging.CRITICAL)
    return folder


def _hook_docling() -> None:
    """Docling's Tesseract model has no setting for forbidden letters; set it on its reader after it is made."""
    try:
        from docling.models.stages.ocr.tesseract_ocr_model import TesseractOcrModel
    except ImportError:
        return
    if getattr(TesseractOcrModel, "_pdfdown_hooked", False):
        return
    original = TesseractOcrModel.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        reader = getattr(self, "_reader", None)
        if reader is not None:
            reader.SetVariable("tessedit_char_blacklist", LATIN if _blacklist["latin"] else "")

    TesseractOcrModel.__init__ = init
    TesseractOcrModel._pdfdown_hooked = True


def _read(image, lang: str, psm: int, folder: Path, variables: dict[str, str]) -> str:
    """Tesseract's text for a PIL image, from the library or, failing that, the program."""
    if library():
        import tesserocr

        with tesserocr.PyTessBaseAPI(path=str(folder), lang=lang, psm=psm) as api:
            for key, value in variables.items():
                api.SetVariable(key, value)
            api.SetImage(image)
            if lang == "osd":
                osd = api.DetectOrientationScript()
                return f"Script: {osd['script_name']}" if osd else ""
            return api.GetUTF8Text()
    if not program():
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        image.save(path)
        command = ["tesseract", str(path), "-", "--psm", str(psm), "--tessdata-dir", str(folder)]
        command += [] if lang == "osd" else ["-l", lang]
        for key, value in variables.items():
            command += ["-c", f"{key}={value}"]
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            return ""


def page_script(pdf, pages: list[int], say=None) -> str:
    """The script Tesseract sees on a few of the given pages (1-based), such as "Bengali" or "Latin"; "" if unsure.

    `pdf` is an open pypdfium2 PdfDocument; call it while holding pdfdown.locks.pdfium_lock.
    """
    if not available() or not pages:
        return ""
    try:
        folder = _model("osd", say).parent
    except OSError:
        return ""
    votes: dict[str, int] = {}
    picks = [pages[len(pages) * k // 4] for k in (1, 2, 3)] if len(pages) >= 4 else pages  # skip covers and blank ends
    for number in dict.fromkeys(picks):
        image = pdf[number - 1].render(scale=300 / 72).to_pil().convert("L")
        try:
            out = _read(image, "osd", 0, folder, {})
        except RuntimeError:  # too few letters to tell
            continue
        match = re.search(r"Script: (\w+)", out)
        if match:
            votes[match.group(1)] = votes.get(match.group(1), 0) + 1
    if not votes:
        return ""
    script, count = max(votes.items(), key=lambda kv: kv[1])
    return script if count * 2 > sum(votes.values()) else ""


def read_number(image) -> str:
    """A number printed large, such as a chapter number, in Bangla digits; "" if Tesseract is unsure.

    Read as a single word with only the ten Bangla digits allowed: on a scanned novel this read 8 of 9 chapter
    numbers right and left the ninth empty, where reading it as a line of text got 3 right and 2 wrong.
    """
    if not available():
        return ""
    folder = tessdata(("bn",))
    return _read(image.convert("L"), "ben", 8, folder, {"tessedit_char_whitelist": BANGLA_DIGITS}).strip()


def speckled(pdf, pages: list[int]) -> bool:
    """Is the scan covered in specks (dust, a bad photocopy, heavy JPEG)? Then EasyOCR may read it better.

    The measure is the share of ink blobs of 1 to 4 pixels at 300 dpi: 0.00 on clean scans, 0.01 to 0.02 on a
    scanned letterpress book, 0.5 to 0.98 on the speckled test scans.
    """
    import numpy as np
    from scipy import ndimage

    picks = [pages[len(pages) * k // 4] for k in (1, 2, 3)] if len(pages) >= 4 else pages
    shares = []
    for number in dict.fromkeys(picks):
        ink = np.array(pdf[number - 1].render(scale=300 / 72).to_pil().convert("L")) < 128
        labels, count = ndimage.label(ink)
        if count:
            shares.append((np.bincount(labels.ravel())[1:] <= 4).sum() / count)
    return bool(shares) and sorted(shares)[len(shares) // 2] > 0.3
