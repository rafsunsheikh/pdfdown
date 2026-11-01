"""Command line: `pdfdown` opens the TUI; `pdfdown --batch a.pdf b.pdf` converts without it.

    pdfdown                          open the TUI and pick PDFs there
    pdfdown paper.pdf more/*.pdf     open the TUI with these PDFs queued
    pdfdown --batch paper.pdf        convert in the terminal, no TUI (also when output is piped)
    pdfdown check out/paper/paper.md list problems left in a converted file
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pdfdown import __version__


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfdown",
        description="Convert PDFs (research articles first) to clean Markdown, with figures, tables and equations.",
        epilog="Example: pdfdown --batch paper.pdf -o notes/  writes notes/paper/paper.md and its images.",
    )
    p.add_argument("pdfs", nargs="*", type=Path, help="PDF files or folders of PDFs")
    p.add_argument("-o", "--out", type=Path, default=Path("pdfdown-output"),
                   help="output folder; each PDF gets its own subfolder (default: ./pdfdown-output)")
    p.add_argument("--batch", action="store_true", help="convert without the TUI")
    p.add_argument("--no-latex", action="store_true", help="keep every equation as an image (skips the 97 MB equation model)")
    p.add_argument("--ocr", action="store_true", help="run OCR, for scanned PDFs without a text layer")
    p.add_argument("--no-tables", action="store_true", help="crop tables as images instead of rebuilding them")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"], help="where the layout models run")
    p.add_argument("--version", action="version", version=f"pdfdown {__version__}")
    return p


def expand(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        path = path.expanduser()
        if path.is_dir():
            out += sorted(p for p in path.rglob("*") if p.suffix.lower() == ".pdf")
        else:
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["check"]:
        return _check(argv[1:])
    args = _parser().parse_args(argv)
    from pdfdown.engine import EngineOptions

    options = EngineOptions(tables=not args.no_tables, ocr=args.ocr, device=args.device)
    pdfs = expand(args.pdfs)
    missing = [p for p in pdfs if not p.is_file()]
    if missing:
        print(f"pdfdown: no such file: {missing[0]}", file=sys.stderr)
        return 2
    if args.batch or not sys.stdout.isatty():
        if not pdfs:
            print("pdfdown: give at least one PDF with --batch", file=sys.stderr)
            return 2
        return _batch(pdfs, args.out, not args.no_latex, options)
    from pdfdown.tui.app import PdfdownApp

    PdfdownApp(pdfs, args.out, latex=not args.no_latex, options=options).run()
    return 0


def _batch(pdfs: list[Path], out: Path, latex: bool, options) -> int:
    from pdfdown.pipeline import run

    model = None
    failed = 0
    for n, pdf in enumerate(pdfs, start=1):
        start = time.time()
        print(f"[{n}/{len(pdfs)}] {pdf.name}", flush=True)
        try:
            if latex and model is None:
                model = _lazy_model()
            result = run(pdf, out, latex=latex, options=options, equation_model=model,
                         progress=lambda message: print(f"    {message}", flush=True))
        except Exception as error:  # one bad PDF should not stop the batch
            failed += 1
            print(f"    failed: {error}", file=sys.stderr)
            continue
        for note in result.doc.notes:
            print(f"    - {note}")
        print(f"    done in {time.time() - start:.0f} s: {result.markdown}")
    return 1 if failed else 0


def _lazy_model():
    """Load pix2tex only when the first equation needs it."""
    from pdfdown.equations import Pix2Tex

    class Lazy:
        name = "pix2tex"
        _model = None

        def __call__(self, image):
            if self._model is None:
                self._model = Pix2Tex()
            return self._model(image)

    return Lazy()


def _check(argv: list[str]) -> int:
    from pdfdown.quality import scan

    if not argv:
        print("usage: pdfdown check FILE.md ...", file=sys.stderr)
        return 2
    bad = 0
    for name in argv:
        findings = scan(Path(name))
        print(f"{name}: {'no problems found' if not findings else ''}")
        for finding in findings:
            print(f"  - {finding}")
        bad += bool(findings)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
