"""The whole conversion: engine, cleanup, Markdown with images, then LaTeX for equations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pdfdown.cleanup import clean
from pdfdown import edits
from pdfdown.document import Document, from_docling
from pdfdown.engine import EngineOptions, convert
from pdfdown.export import write
from pdfdown.locks import pdfium_lock
from pdfdown.pdftext import PdfText


@dataclass
class Result:
    doc: Document
    markdown: Path


def run(pdf: str | Path, out_dir: str | Path = "pdfdown-output", latex: bool = True, options: EngineOptions | None = None,
        progress: Callable[[str], None] | None = None, equation_model=None) -> Result:
    say = progress or (lambda message: None)
    pdf = Path(pdf).expanduser().resolve()
    doc = from_docling(convert(pdf, options, progress=say), pdf)
    with pdfium_lock:  # Docling has finished with pdfium; everything below reads the PDF directly
        text = PdfText(pdf)
        try:
            say("Cleaning up: page furniture, captions, paragraphs, superscripts")
            clean(doc, text)
            edits.apply(doc, edits.load(doc, out_dir), text)
            md = write(doc, out_dir)
            say(f"Wrote {md} (equations as images)")
            if latex and doc.of_kind("equation"):
                from pdfdown.equations import recognise

                say("Reading equations as LaTeX")
                recognise(doc, md.parent, text, model=equation_model,
                          progress=lambda i, n, b: say(f"Equation {i}/{n}: {'LaTeX' if b.extra.get('latex_ok') else 'image'}"))
                md = write(doc, out_dir)
        finally:
            text.close()
    return Result(doc, md)


def summary(result: Result) -> dict:
    """What a person or a coding agent needs to know about a conversion, as plain data (also `pdfdown --batch --json`)."""
    from pdfdown.export import element_list
    from pdfdown.quality import scan

    doc, md = result.doc, result.markdown.resolve()
    elements = element_list(doc)
    equations = [e for e in elements if e["kind"] == "equation"]
    as_images = [e for e in equations if e["written_as"] == "image"]
    return {
        "source": str(doc.source),
        "markdown": str(md),
        "folder": str(md.parent),
        "pages": len(doc.page_sizes),
        "figures": sum(e["kind"] == "figure" for e in elements),
        "tables": sum(e["kind"] == "table" for e in elements),
        "equations": {
            "total": len(equations),
            "latex": len(equations) - len(as_images),
            "images": len(as_images),
            "kept_as_images": [{"id": e["id"], "number": e.get("number"), "page": e["page"],
                                "reason": e.get("check") or "no LaTeX reading (equation reading was off)"}
                               for e in as_images],
        },
        "notes": doc.notes,
        "problems": [str(f) for f in scan(md)],
    }
