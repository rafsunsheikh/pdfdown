"""Run Docling on a PDF once and cache the result.

Docling does the heavy model work: page layout, reading order, table
structure and (optionally) formula recognition. A 24-page article takes
about two minutes on a laptop, so the result is cached as Docling JSON,
keyed by the PDF's content and the options. Every later step (cleanup,
export, the TUI) reads the cached document and runs in seconds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ENGINE_VERSION = 4  # bump to invalidate caches when the conversion options change meaning


@dataclass(frozen=True)
class EngineOptions:
    tables: bool = True
    formulas: bool = False  # Docling's formula model: slow, CPU only on macOS; pdfdown runs it per equation later
    ocr: str = "auto"  # auto: OCR pages without a text layer; all: OCR every page (bad text layers); off
    ocr_engine: str = "auto"  # auto (RapidOCR), rapidocr, tesseract and easyocr (Bangla), mac (Apple Vision, macOS only)
    ocr_lang: tuple[str, ...] = ()  # OCR languages, e.g. ("bn", "en"); empty: the engine's default
    device: str = "auto"  # auto, cpu, mps, cuda

    def __post_init__(self) -> None:
        if isinstance(self.ocr, bool):  # older callers passed True/False
            object.__setattr__(self, "ocr", "all" if self.ocr else "off")

    def key(self) -> str:
        return hashlib.sha256(json.dumps({**asdict(self), "v": ENGINE_VERSION}, sort_keys=True).encode()).hexdigest()[:16]


def cache_dir() -> Path:
    root = os.environ.get("PDFDOWN_CACHE") or os.path.join(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"), "pdfdown")
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:24]


def cache_path(pdf: Path, options: EngineOptions) -> Path:
    return cache_dir() / f"{file_hash(pdf)}-{options.key()}.json"


def _device(name: str) -> str:
    if name != "auto":
        return name
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def convert(pdf: str | Path, options: EngineOptions | None = None, use_cache: bool = True,
            progress: Callable[[str], None] | None = None, scanned: list[int] | None = None):
    """Return a DoclingDocument for `pdf`, from the cache when possible.

    `scanned` lists the pages without a text layer (see scanned_pages); with ocr="auto", OCR runs only when there
    are any, and Docling then reads only the image areas, so pages with real text keep it.
    """
    from docling_core.types.doc import DoclingDocument

    pdf = Path(pdf).expanduser().resolve()
    options = options or EngineOptions()
    cached = cache_path(pdf, options)
    if use_cache and cached.is_file():
        if progress:
            progress("Using cached layout analysis")
        return DoclingDocument.load_from_json(cached)

    device = _device(options.device)
    if options.formulas and device == "mps":
        device = "cpu"  # the formula model does not support Apple GPUs
    do_ocr = options.ocr == "all" or (options.ocr == "auto" and bool(scanned))
    converter = make_converter(options, do_ocr, device)
    if progress:
        reading = (" and reading every page with OCR" if options.ocr == "all"
                   else f" and reading {len(scanned)} scanned page{'s' * (len(scanned) != 1)} with OCR" if do_ocr else "")
        progress(f"Analysing layout{reading} on {device} (cached afterwards)")
    result = converter.convert(pdf)
    doc = result.document
    doc.save_as_json(cached)
    return doc


def make_converter(options: EngineOptions, do_ocr: bool, device: str = "cpu"):
    """Docling's converter for these options (also used by `pdfdown setup` to download the models ahead)."""
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline = PdfPipelineOptions(
        do_table_structure=options.tables,
        do_formula_enrichment=options.formulas,
        do_ocr=do_ocr,
        ocr_options=_ocr_options(options),
        generate_page_images=False,
        generate_picture_images=False,  # pdfdown renders its own crops at high resolution
        accelerator_options=AcceleratorOptions(device=device),
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)})


def _ocr_options(options: EngineOptions):
    from docling.datamodel import pipeline_options as P

    mode = P.OcrMode.FULL_PAGE if options.ocr == "all" else P.OcrMode.DEFAULT
    lang = list(options.ocr_lang)
    if options.ocr_engine == "mac":
        return P.OcrMacOptions(mode=mode, **({"lang": lang} if lang else {}))
    if options.ocr_engine in ("rapidocr", "auto"):
        # The default, chosen on the benchmark in scripts/ocr_bench: as good as Apple Vision on clean English scans
        # and far better on poor ones (5.6% against 34.6% words wrong), and it runs everywhere. Named explicitly,
        # because Docling's own "auto" picks whatever happens to be installed.
        return P.RapidOcrOptions(mode=mode, backend="torch")  # PyTorch comes with pdfdown
    if options.ocr_engine == "easyocr":
        # EasyOCR is unsure of Bangla: 61% of the text it read correctly on a clean test scan scored below 0.5, which
        # Docling's default threshold throws away (79.6% of characters wrong, against 16.6% keeping everything).
        threshold = 0.1 if "bn" in lang else 0.5
        return P.EasyOcrOptions(mode=mode, confidence_threshold=threshold, **({"lang": lang} if lang else {}))
    if options.ocr_engine == "tesseract":
        from pdfdown.tesseract import CODES, program, tessdata

        languages = options.ocr_lang or ("bn",)
        folder = tessdata(languages)
        # The program reads whole pages and does better on old print (5.5% of letters wrong on a scanned book,
        # against 8.6% for the bundled library, which reads line by line); every install has the library.
        kind = P.TesseractCliOcrOptions if program() else P.TesseractOcrOptions
        return kind(mode=mode, lang=[CODES.get(code, code) for code in languages], path=str(folder),
                    scale=300 / 72)  # old print needs 300 dpi
    raise ValueError(f"unknown OCR engine {options.ocr_engine!r}: use rapidocr, tesseract, easyocr or mac")


def scanned_pages(pdf, min_chars: int = 30, min_image_share: float = 0.3) -> list[int]:
    """Pages (1-based) that look scanned: almost no text characters, and mostly covered by images.

    `pdf` is an open pypdfium2 PdfDocument; call it while holding pdfdown.locks.pdfium_lock.
    """
    import pypdfium2.raw as pdfium_c

    out = []
    for number in range(1, len(pdf) + 1):
        page = pdf[number - 1]
        textpage = page.get_textpage()
        chars = sum(1 for i in range(textpage.count_chars()) if chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i) or 32).strip())
        if chars >= min_chars:
            continue
        area = page.get_width() * page.get_height()
        covered = 0.0
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
            left, bottom, right, top = obj.get_bounds()
            covered += max(right - left, 0) * max(top - bottom, 0)
        if area and covered / area >= min_image_share:
            out.append(number)
    return out


# Which OCR engine reads which language (measured in scripts/ocr_bench and on a scanned book; see the README).
# RapidOCR, Docling's default, has no Bengali model and Apple Vision does not support Bangla. Tesseract reads Bangla
# best; EasyOCR is the fallback when the Tesseract program is not installed.


def ocr_choice(lang: str) -> tuple[str, tuple[str, ...]]:
    """(engine, languages) for a --lang value such as "bn", "bn+en" (Bangla with English words) or "en"."""
    from pdfdown import tesseract

    aliases = {"bangla": "bn", "bengali": "bn", "ben": "bn", "english": "en", "eng": "en"}
    codes = tuple(dict.fromkeys(aliases.get(c, c) for c in re.split(r"[+,\s]+", lang.strip().lower()) if c))
    if "bn" not in codes:
        return "auto", ()
    if tesseract.available():
        return "tesseract", codes
    return "easyocr", ("bn", "en")  # EasyOCR's Bangla model is trained with English


def looks_bangla(pdf, sample_pages: int = 12) -> bool:
    """Is the PDF's text mostly Bangla, in Unicode or in an old Bijoy font? Then its scanned pages need Bangla OCR.

    `pdf` is an open pypdfium2 PdfDocument; call it while holding pdfdown.locks.pdfium_lock.
    """
    import ctypes

    import pypdfium2.raw as pdfium_c

    from pdfdown.bijoy import is_bijoy_font

    bangla = letters = 0
    name = ctypes.create_string_buffer(256)
    flags = ctypes.c_int()
    step = max(len(pdf) // sample_pages, 1)
    for number in range(0, len(pdf), step):
        textpage = pdf[number].get_textpage()
        for i in range(0, textpage.count_chars(), 7):  # every 7th character is plenty
            ch = chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i) or 32)
            if not ch.isalpha():
                continue
            letters += 1
            if "\u0980" <= ch <= "\u09ff":
                bangla += 1
            else:
                pdfium_c.FPDFText_GetFontInfo(textpage.raw, i, name, ctypes.sizeof(name), ctypes.byref(flags))
                bangla += is_bijoy_font(name.value.decode("latin-1", "replace"))
    return letters > 50 and bangla > 0.5 * letters
