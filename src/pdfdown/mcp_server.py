"""pdfdown as an MCP server, so coding agents (Claude Code, Cursor, Claude Desktop ...) can convert PDFs themselves.

    claude mcp add pdfdown -- uvx pdfdown mcp

Tools:
    convert_pdf          convert a PDF; returns where the Markdown is and what happened (no giant text)
    markdown_outline     the headings of a converted Markdown file, with line numbers
    read_markdown        a slice of the Markdown, by line, so a long paper never floods the agent's context
    list_elements        every figure, table and equation, with LaTeX or image status and the reason
    get_element_image    the cropped image of one element, for the agent to look at
    set_equation_latex   propose LaTeX for an equation; kept only if it passes the same check against the PDF

Everything runs on the user's computer; the agent and pdfdown share the same files.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError  # its message reaches the agent; other errors are hidden
from mcp.types import ToolAnnotations

INSTRUCTIONS = """pdfdown converts PDFs (research articles first) to Markdown on this computer.
Call convert_pdf first; it returns the Markdown path and a summary. The first conversion of a PDF can take a
minute or more (and the first ever run downloads about 1 GB of models); later ones reuse a cache.
Read long results with markdown_outline and read_markdown instead of loading the whole file.
Equations: an equation is LaTeX in the Markdown only if the LaTeX matched the PDF's own characters; otherwise it
is an exact image of the original. Never guess an equation from its image without set_equation_latex: that tool
checks your LaTeX against the PDF and keeps it only if it passes."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
server = MCPServer("pdfdown", instructions=INSTRUCTIONS)
_model = None
_model_lock = threading.Lock()


def _equation_model():
    global _model
    with _model_lock:
        if _model is None:
            from pdfdown.cli import _lazy_model

            _model = _lazy_model()
        return _model


def _pdf(path: str) -> Path:
    pdf = Path(path).expanduser().resolve()
    if not pdf.is_file():
        raise ToolError(f"No such file: {pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise ToolError(f"Not a PDF: {pdf}")
    return pdf


def _markdown(path: str) -> Path:
    md = Path(path).expanduser().resolve()
    if not md.is_file():
        raise ToolError(f"No such Markdown file: {md}. Convert the PDF with convert_pdf first.")
    return md


def _elements(md: Path) -> dict:
    from pdfdown.export import ELEMENTS

    path = md.parent / ELEMENTS
    if not path.is_file():
        raise ToolError(f"{md} was not written by this version of pdfdown; convert the PDF again with convert_pdf.")
    return json.loads(path.read_text(encoding="utf-8"))


async def _convert(pdf: Path, out_dir: Path, read_equations: bool, ctx: Context | None, options=None):
    """Run the pipeline in a worker thread, passing its progress messages to the agent."""
    from pdfdown.pipeline import run

    steps = 0

    def progress(message: str) -> None:
        nonlocal steps
        steps += 1
        if ctx is not None:
            try:
                anyio.from_thread.run(ctx.report_progress, steps, None, message)
            except Exception:  # a client that does not take progress must not stop the conversion
                pass

    model = _equation_model() if read_equations else None
    return await anyio.to_thread.run_sync(
        lambda: run(pdf, out_dir, latex=read_equations, options=options, equation_model=model, progress=progress))


@server.tool()
async def convert_pdf(path: str, output_dir: str | None = None, read_equations: bool = True, ocr: str = "auto",
                      language: str = "", ctx: Context | None = None) -> dict[str, Any]:
    """Convert a PDF to Markdown, with figures, tables and equations cropped into image files.

    Args:
        path: the PDF on this computer.
        output_dir: where to write; the PDF gets its own folder inside it. Default: a "pdfdown-output" folder
            next to the PDF.
        read_equations: read display equations as LaTeX (checked against the PDF). False keeps every equation
            as an image and is faster.
        ocr: "auto" (default) reads pages without a text layer (scans) with OCR; "all" reads every page with OCR,
            for scans whose text layer is wrong or garbled; "off" never uses OCR.
        language: the language for OCR: "bn" for Bangla, "bn+en" for Bangla with English words; default: found
            from the text or the page images.

    Returns where the Markdown is, counts of figures, tables and equations, which equations stayed images and
    why, what the cleanup did, and possible problems left. Read the Markdown with read_markdown.
    """
    from pdfdown.pipeline import summary

    pdf = _pdf(path)
    out = Path(output_dir).expanduser().resolve() if output_dir else pdf.parent / "pdfdown-output"
    if ocr not in ("auto", "all", "off"):
        raise ToolError('ocr must be "auto", "all" or "off"')
    from pdfdown.cli import engine_options

    result = await _convert(pdf, out, read_equations, ctx, engine_options(ocr=ocr, lang=language))
    return summary(result)


@server.tool(annotations=READ_ONLY)
def markdown_outline(markdown_path: str) -> dict[str, Any]:
    """The headings of a converted Markdown file with their line numbers, and its size.

    Use the line numbers with read_markdown to read one section at a time.
    """
    md = _markdown(markdown_path)
    lines = md.read_text(encoding="utf-8").splitlines()
    headings = [{"line": n, "level": len(line) - len(line.lstrip("#")), "title": line.lstrip("#").strip()}
                for n, line in enumerate(lines, start=1) if line.startswith("#")]
    return {"markdown": str(md), "lines": len(lines), "characters": sum(len(line) + 1 for line in lines),
            "headings": headings}


@server.tool(annotations=READ_ONLY)
def read_markdown(markdown_path: str, start_line: int = 1, max_characters: int = 20000) -> dict[str, Any]:
    """Read part of a converted Markdown file, from start_line, up to about max_characters (whole lines).

    Returns the text and next_start_line to continue from (null at the end of the file). Image links are
    relative to the Markdown file's folder.
    """
    md = _markdown(markdown_path)
    lines = md.read_text(encoding="utf-8").splitlines()
    start = max(start_line, 1)
    chunk, size, end = [], 0, start - 1
    for n in range(start - 1, len(lines)):
        if chunk and size + len(lines[n]) + 1 > max(max_characters, 1000):
            break
        chunk.append(lines[n])
        size += len(lines[n]) + 1
        end = n + 1
    return {"text": "\n".join(chunk), "start_line": start, "end_line": end, "total_lines": len(lines),
            "next_start_line": end + 1 if end < len(lines) else None}


@server.tool(annotations=READ_ONLY)
def list_elements(markdown_path: str, kind: str | None = None) -> dict[str, Any]:
    """Every figure, table and equation in a converted Markdown file.

    Args:
        markdown_path: the Markdown file convert_pdf returned.
        kind: only "figure", "table" or "equation".

    For equations: written_as is "latex" or "image", with the LaTeX and the result of the check against the PDF.
    Ids (eq-3, figure-2a, table-1) work with get_element_image and set_equation_latex.
    """
    data = _elements(_markdown(markdown_path))
    items = [e for e in data["elements"] if not kind or e["kind"] == kind]
    return {"markdown": data["markdown"], "source": data["source"], "elements": items}


@server.tool(annotations=READ_ONLY)
def get_element_image(markdown_path: str, element_id: str) -> Image:
    """The cropped image of a figure, table or equation (by id from list_elements), to look at."""
    md = _markdown(markdown_path)
    element = next((e for e in _elements(md)["elements"] if e["id"] == element_id), None)
    if element is None:
        raise ToolError(f"No element {element_id!r}; list_elements shows the ids.")
    return Image(path=md.parent / element["image"])


@server.tool()
async def set_equation_latex(markdown_path: str, element_id: str, latex: str, ctx: Context | None = None) -> dict[str, Any]:
    """Propose LaTeX for an equation that is still an image (look at it with get_element_image first).

    The LaTeX is checked against the characters printed in the PDF: the same letters and digits, the same ones
    in subscripts and superscripts, the same letter styles, and it must render. If it passes, it replaces the
    image in the Markdown and is saved for later runs; if not, nothing changes and the reason is returned.
    """
    from pdfdown import edits
    from pdfdown.document import Box
    from pdfdown.equations import check, clean_latex
    from pdfdown.locks import pdfium_lock
    from pdfdown.pdftext import PdfText

    md = _markdown(markdown_path)
    data = _elements(md)
    element = next((e for e in data["elements"] if e["id"] == element_id), None)
    if element is None or element["kind"] != "equation":
        raise ToolError(f"No equation {element_id!r}; list_elements(kind='equation') shows the ids.")
    latex, _number = clean_latex(latex)

    def verdict():
        with pdfium_lock:
            text = PdfText(data["source"])
            try:
                return check(latex, text.page(element["page"]).inside(Box(*element["box"])))
            finally:
                text.close()

    result = await anyio.to_thread.run_sync(verdict)
    if not result.ok:
        return {"accepted": False, "reason": result.reason, "latex": latex,
                "hint": "Compare with get_element_image and try again; the equation stays an image until LaTeX passes."}
    path = md.parent / edits.FILE
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    saved[element["ref"]] = {**saved.get(element["ref"], {}), "latex": latex, "latex_by": "agent", "use": "latex"}
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    await _convert(Path(data["source"]), md.parent.parent, True, ctx)  # quick: layout and readings are cached
    return {"accepted": True, "reason": result.reason, "latex": latex, "markdown": str(md)}


def serve() -> None:
    """Run over stdio (how coding agents start MCP servers)."""
    server.run()
