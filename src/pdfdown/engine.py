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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ENGINE_VERSION = 1  # bump to invalidate caches when the conversion options change meaning


@dataclass(frozen=True)
class EngineOptions:
    tables: bool = True
    formulas: bool = False  # Docling's formula model: slow, CPU only on macOS; pdfdown runs it per equation later
    ocr: bool = False  # only needed for scanned PDFs
    device: str = "auto"  # auto, cpu, mps, cuda

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
            progress: Callable[[str], None] | None = None):
    """Return a DoclingDocument for `pdf`, from the cache when possible."""
    from docling_core.types.doc import DoclingDocument

    pdf = Path(pdf).expanduser().resolve()
    options = options or EngineOptions()
    cached = cache_path(pdf, options)
    if use_cache and cached.is_file():
        if progress:
            progress("Using cached layout analysis")
        return DoclingDocument.load_from_json(cached)

    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    device = _device(options.device)
    if options.formulas and device == "mps":
        device = "cpu"  # the formula model does not support Apple GPUs
    pipeline = PdfPipelineOptions(
        do_table_structure=options.tables,
        do_formula_enrichment=options.formulas,
        do_ocr=options.ocr,
        generate_page_images=False,
        generate_picture_images=False,  # pdfdown renders its own crops at high resolution
        accelerator_options=AcceleratorOptions(device=device),
    )
    if progress:
        progress(f"Analysing layout with Docling on {device} (about 5 seconds a page; cached afterwards)")
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)})
    result = converter.convert(pdf)
    doc = result.document
    doc.save_as_json(cached)
    return doc
