"""Command line: `pdfdown` opens the TUI; `pdfdown --batch a.pdf b.pdf` converts without it.

    pdfdown                          open the TUI and pick PDFs there
    pdfdown paper.pdf more/*.pdf     open the TUI with these PDFs queued
    pdfdown --batch paper.pdf        convert in the terminal, no TUI (also when output is piped)
    pdfdown check out/paper/paper.md list problems left in a converted file
    pdfdown setup                    download every model now (the installers run this)
    pdfdown --batch --json paper.pdf convert and print a JSON summary, for scripts and coding agents
    pdfdown mcp                      run as an MCP server, so coding agents can convert PDFs themselves
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
    p.add_argument("--json", action="store_true",
                   help="with --batch: print one JSON summary on stdout (progress goes to stderr); made for scripts and coding agents")
    p.add_argument("--no-latex", action="store_true", help="keep every equation as an image (skips the 97 MB equation model)")
    p.add_argument("--ocr", nargs="?", const="all", default="auto", choices=["auto", "all", "off"],
                   help="auto (default): read pages that have no text layer with OCR; all (also plain --ocr): read every "
                        "page with OCR, for PDFs whose text layer is wrong; off: never")
    p.add_argument("--lang", default="", metavar="CODES",
                   help="language of the text, for OCR: bn for Bangla, bn+en for Bangla with English words, en (default)")
    p.add_argument("--no-tables", action="store_true", help="crop tables as images instead of rebuilding them")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"], help="where the layout models run")
    p.add_argument("--version", action="version", version=f"pdfdown {__version__}")
    return p


def engine_options(tables: bool = True, ocr: str = "auto", lang: str = "", device: str = "auto"):
    """Engine options from user-facing choices; a language that the default OCR engine cannot read picks one that can."""
    from pdfdown.engine import EngineOptions, ocr_choice

    engine, languages = ocr_choice(lang)
    return EngineOptions(tables=tables, ocr=ocr, ocr_engine=engine, ocr_lang=languages, device=device)


def expand(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        path = path.expanduser()
        if path.is_dir():
            out += sorted(p for p in path.rglob("*") if p.suffix.lower() == ".pdf")
        else:
            out.append(path)
    return out


def _windows_runtime_hint() -> None:
    """PyTorch on Windows needs the Microsoft Visual C++ Runtime. The installers add it; after a plain `pip install`
    it may be missing, and the first conversion would then fail with a cryptic DLL error. Say how to fix it."""
    if sys.platform != "win32":
        return
    import winreg

    for key in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                if winreg.QueryValueEx(handle, "Installed")[0] == 1:
                    return
        except OSError:
            continue
    print("pdfdown: the Microsoft Visual C++ Runtime is not installed, and the layout models need it. Install it with\n"
          "    winget install Microsoft.VCRedist.2015+.x64\n"
          "or from https://aka.ms/vs/17/release/vc_redist.x64.exe, then run pdfdown again.", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        # Windows writes to a pipe in the old code page (cp1252), which cannot hold Bangla or most file names in
        # other scripts: `pdfdown --batch --json` piped to an agent would crash. Always write UTF-8.
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    _windows_runtime_hint()
    if argv[:1] == ["check"]:
        return _check(argv[1:])
    if argv[:1] == ["setup"]:
        if set(argv[1:]) & {"-h", "--help"}:
            print("usage: pdfdown setup\n\nDownload every model pdfdown can need (about 1 GB), so the first conversion "
                  "runs at full speed and later ones work offline. Running it again only checks them.")
            return 0
        from pdfdown.setup import run

        return run()
    if argv[:1] == ["mcp"]:
        from pdfdown.mcp_server import serve

        serve()
        return 0
    args = _parser().parse_args(argv)
    from pdfdown.engine import EngineOptions

    options = engine_options(tables=not args.no_tables, ocr=args.ocr, lang=args.lang, device=args.device)
    pdfs = expand(args.pdfs)
    missing = [p for p in pdfs if not p.is_file()]
    if missing:
        print(f"pdfdown: no such file: {missing[0]}", file=sys.stderr)
        return 2
    if args.batch or not sys.stdout.isatty():
        if not pdfs:
            print("pdfdown: give at least one PDF with --batch", file=sys.stderr)
            return 2
        return _batch(pdfs, args.out, not args.no_latex, options, as_json=args.json)
    from pdfdown.tui.app import PdfdownApp

    PdfdownApp(pdfs, args.out, latex=not args.no_latex, options=options).run()
    return 0


def _batch(pdfs: list[Path], out: Path, latex: bool, options, as_json: bool = False) -> int:
    import json

    from pdfdown.pipeline import run, summary

    say = (lambda text: print(text, file=sys.stderr, flush=True)) if as_json else (lambda text: print(text, flush=True))
    model = _lazy_model() if latex else None
    results, failed = [], []
    for n, pdf in enumerate(pdfs, start=1):
        start = time.time()
        say(f"[{n}/{len(pdfs)}] {pdf.name}")
        try:
            result = run(pdf, out, latex=latex, options=options, equation_model=model,
                         progress=lambda message: say(f"    {message}"))
        except Exception as error:  # one bad PDF should not stop the batch
            failed.append({"source": str(pdf), "error": str(error)})
            print(f"    failed: {error}", file=sys.stderr)
            continue
        if as_json:
            results.append(summary(result))
        else:
            for note in result.doc.notes:
                say(f"    - {note}")
        say(f"    done in {time.time() - start:.0f} s: {result.markdown}")
    if as_json:
        print(json.dumps({"results": results, "failed": failed}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


def _lazy_model():
    """Load pix2tex only when the first equation needs it."""
    from pdfdown.equations import Pix2Tex

    class Lazy:
        name = "pix2tex"
        _model = None

        @property
        def loaded(self) -> bool:
            return self._model is not None

        def warm(self) -> None:
            if self._model is None:
                self._model = Pix2Tex()

        def __call__(self, image):
            self.warm()
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
