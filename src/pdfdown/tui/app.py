"""The pdfdown TUI: a queue of PDFs, the Markdown they become, and every figure, table and equation.

    ┌ Files ─────────┬ Markdown │ Source │ Element │ Page │ Report │ Log ┐
    │ ✓ paper.pdf    │                                                    │
    │ ⟳ bert.pdf     │   the converted Markdown, or the selected element  │
    ├ Elements ──────┤   with its crop, LaTeX and why it was chosen       │
    │ Figure 1       │                                                    │
    │ Eq 2  LaTeX ✓  │                                                    │
    │ Eq 3  image    │                                                    │
    └────────────────┴────────────────────────────────────────────────────┘

Conversion runs in a background thread, one PDF at a time. Every change made
here (LaTeX or image, edited LaTeX, crop, hide) is saved in pdfdown-edits.json
beside the Markdown and the Markdown is written again at once.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw
from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Footer, Header, Label, ListItem, ListView, Markdown, ProgressBar, RichLog, Static, TabbedContent,
                             TabPane, TextArea)
from textual_image.widget import Image

from pdfdown import edits
from pdfdown.document import Block, Box, Document
from pdfdown.engine import EngineOptions
from pdfdown.export import area, detected_area, use_latex, write
from pdfdown.locks import pdfium_lock
from pdfdown.tui.progress import JobProgress

ICON = {"queued": "·", "converting": "⟳", "done": "✓", "failed": "✗"}
WELCOME = """# pdfdown

Press **a** to add PDFs. Each one is converted in the background, one at a time.

- **Markdown** shows the result, **Source** the raw text, **Report** what the cleanup changed.
- Pick a figure, table or equation under *Elements* to see its crop and, for equations, the LaTeX.
- Equations go in as images first. LaTeX replaces an image only when it matches the PDF's own text.
"""


SUP = str.maketrans("0123456789+-−–=()n,i", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁻⁼⁽⁾ⁿ˒ⁱ")
SUB = str.maketrans("0123456789+-−=()aeiorx", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑᵢₒᵣₓ")


def preview(markdown: str) -> str:
    """Textual's Markdown viewer shows <sup>/<sub> as plain text, so draw them with Unicode scripts.

    Only the preview changes; the .md file keeps the HTML tags, which every Markdown renderer understands.
    """
    def script(table, mark):
        def swap(m):
            text = m.group(1)
            if all(ord(c) in table for c in text):
                return text.translate(table)
            return f"{mark}({text})"  # no small form for every character: keep it readable
        return swap

    markdown = re.sub(r"<sup>(.*?)</sup>", script(SUP, "^"), markdown)
    return re.sub(r"<sub>(.*?)</sub>", script(SUB, "_"), markdown)


@dataclass
class Job:
    pdf: Path
    status: str = "queued"
    message: str = ""
    doc: Document | None = None
    markdown: Path | None = None
    progress: JobProgress | None = None
    options: EngineOptions | None = None  # per-file choice, such as "read every page with OCR"

    def label(self) -> str:
        if self.status == "converting" and self.progress:
            return f"{ICON[self.status]} {self.pdf.name}  {self.progress.fraction() * 100:.0f}%"
        detail = f"  {self.message}" if self.message and self.status not in ("done", "queued") else ""
        return f"{ICON[self.status]} {self.pdf.name}{detail}"


class JobItem(ListItem):
    def __init__(self, job: Job) -> None:
        super().__init__(Label(job.label()))
        self.job = job


class ElementItem(ListItem):
    def __init__(self, block: Block, text: str) -> None:
        super().__init__(Label(text))
        self.block = block


def element_label(block: Block, eq_number: int) -> str:
    hidden = "  hidden" if block.extra.get("hidden") else ""
    if block.kind in ("figure", "table"):
        name = Path(block.extra.get("image", "")).stem.split("-", 1)[-1] or block.extra.get("number", "?")
        name = "(no number)" if name.startswith("u") else name
        if block.kind == "figure":
            return f"Figure {name}  p{block.page}{hidden}"
        rebuilt = block.extra.get("markdown") or block.extra.get("html")
        return f"Table {name}  {'text' if rebuilt else 'image'}{hidden}"
    if use_latex(block):
        status = "LaTeX (yours)" if block.extra.get("latex_by") == "you" else "LaTeX ✓" if block.extra.get("latex_ok") else "LaTeX ?"
    else:
        status = "image"
    tag = f" ({block.extra['number']})" if block.extra.get("number") else ""
    return f"Eq {eq_number}{tag}  {status}{hidden}"


def _start_helper_processes() -> None:
    """Start Python's multiprocessing resource tracker now, before Textual takes over the terminal.

    Loading the layout model shows a tqdm progress bar, and tqdm's lock starts that tracker. Starting it passes
    sys.stderr's file descriptor to a child process, but inside a Textual app sys.stderr is a capture object with
    no real descriptor, and the start fails with "bad value(s) in fds_to_keep": every PDF converted for the first
    time failed in the app. Once running, the tracker is reused, so later model loads are fine.
    """
    try:
        from multiprocessing import resource_tracker

        resource_tracker.ensure_running()
    except Exception:  # pragma: no cover - platforms without it simply skip this
        pass


class PdfdownApp(App):
    TITLE = "pdfdown"
    CSS = """
    #side { width: 34; border-right: solid $primary-background; }
    #side Label.heading { padding: 0 1; text-style: bold; color: $text-muted; }
    #files { height: 1fr; max-height: 12; }
    #elements { height: 2fr; }
    #element-image, #page-image { width: auto; height: auto; max-height: 30; }
    #element-info, #element-latex, #page-info, #report { padding: 0 1; }
    #element-latex { margin-top: 1; }
    #dialog { width: 90%; height: 90%; background: $panel; border: thick $primary; padding: 1 2; }
    #dialog #tree { height: 1fr; }
    #dialog TextArea { height: 8; }
    #dialog Image.equation { width: auto; height: auto; max-height: 10; }
    #crop-view { width: 100%; height: auto; }
    #progress-panel { height: auto; padding: 1 2; display: none; }
    #progress-title { text-style: bold; margin-bottom: 1; }
    #progress-bar { margin-bottom: 1; }
    #progress-bar Bar { width: 1fr; }
    """
    BINDINGS = [
        Binding("a", "add", "Add PDFs"),
        Binding("t", "toggle", "LaTeX/image"),
        Binding("e", "edit", "Edit LaTeX"),
        Binding("h", "harder", "Try harder"),
        Binding("c", "crop", "Crop"),
        Binding("x", "hide", "Hide"),
        Binding("v", "view", "Open image", show=False),
        Binding("o", "open_folder", "Open folder"),
        Binding("R", "reconvert", "Reconvert", show=False),
        Binding("O", "reconvert_ocr", "OCR all pages", show=False),
        Binding("q", "quit", "Quit"),
    ] + [Binding(str(n), f"tab('{tab}')", tab.capitalize(), show=False)
         for n, tab in enumerate(("markdown", "source", "element", "page", "report", "log"), start=1)]

    def __init__(self, pdfs: list[Path] | None = None, out: Path = Path("pdfdown-output"), latex: bool = True,
                 options: EngineOptions | None = None) -> None:
        _start_helper_processes()
        super().__init__()
        self.out = Path(out).resolve()
        self.latex = latex
        self.options = options or EngineOptions()
        self.jobs: list[Job] = []
        self.current: Job | None = None
        self.block: Block | None = None
        self._initial = list(pdfs or [])
        self._queue_lock = threading.Lock()
        self._converting = False
        self._markdown_stale = True
        self._model = None
        self.watching: Job | None = None  # the job whose progress the Markdown tab shows

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="side"):
                yield Label("Files", classes="heading")
                yield ListView(id="files")
                yield Label("Elements", classes="heading")
                yield ListView(id="elements")
            with TabbedContent(id="tabs"):
                with TabPane("Markdown", id="tab-markdown"):
                    with Vertical(id="progress-panel"):
                        yield Label("", id="progress-title")
                        yield ProgressBar(id="progress-bar", total=100, show_eta=False)
                        yield Static("", id="progress-steps")
                    with VerticalScroll(id="markdown-scroll"):
                        yield Markdown(WELCOME, id="markdown")
                with TabPane("Source", id="tab-source"):
                    yield TextArea("", id="source", read_only=True, soft_wrap=True)
                with TabPane("Element", id="tab-element"):
                    with VerticalScroll():
                        yield Static("Pick a figure, table or equation on the left.", id="element-info")
                        yield Image(id="element-image")
                        yield Static("", id="element-latex")
                with TabPane("Page", id="tab-page"):
                    with VerticalScroll():
                        yield Static("The page of the selected element, with its crop in red.", id="page-info")
                        yield Image(id="page-image")
                with TabPane("Report", id="tab-report"):
                    with VerticalScroll():
                        yield Static("Nothing converted yet.", id="report")
                with TabPane("Log", id="tab-log"):
                    yield RichLog(id="log", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"output: {self.out}"
        self.set_interval(0.25, self.tick_progress)
        if self._initial:
            self.add_pdfs(self._initial)

    # ------------------------------------------------------------------ queue

    def add_pdfs(self, pdfs: list[Path]) -> None:
        files = self.query_one("#files", ListView)
        known = {j.pdf for j in self.jobs}
        new = [Job(p.expanduser().resolve()) for p in pdfs if p.expanduser().resolve() not in known]
        for job in new:
            files.append(JobItem(job))
            self.log_line(f"Queued {job.pdf}")
        if new and len(self.jobs) == 0:
            files.index = 0
        with self._queue_lock:
            self.jobs += new
            start = not self._converting
            self._converting = True
        if start:
            self.convert_queue()

    @work(thread=True, group="convert")
    def convert_queue(self) -> None:
        from pdfdown.cli import _lazy_model
        from pdfdown.pipeline import run

        while True:
            with self._queue_lock:
                job = next((j for j in self.jobs if j.status == "queued"), None)
                if job is None:
                    self._converting = False
                    return
                job.status = "converting"
            if self.latex and self._model is None:
                self._model = _lazy_model()
            started = time.time()
            job.progress = JobProgress(latex=self.latex, reader_loaded=bool(getattr(self._model, "loaded", False)))
            self.call_from_thread(self.job_changed, job, "starting")
            try:
                result = run(job.pdf, self.out, latex=self.latex, options=job.options or self.options, equation_model=self._model,
                             progress=lambda message, job=job: self.call_from_thread(self.job_changed, job, message),
                             step=lambda name, done, total, job=job: self.call_from_thread(job.progress.on_step, name, done, total))
            except Exception as error:  # show it, then carry on with the next PDF
                job.status = "failed"
                self.call_from_thread(self.job_changed, job, f"failed: {error}")
                continue
            job.doc, job.markdown, job.status = result.doc, result.markdown, "done"
            self.call_from_thread(self.job_changed, job, f"done in {time.time() - started:.0f} s: {result.markdown}")

    def job_changed(self, job: Job, message: str) -> None:
        job.message = message[:40]
        if job.status == "converting" and (self.watching is None or self.watching.status != "converting") \
                and (self.current is None or self.current.status != "done"):
            self.watch(job)  # nothing finished on screen yet: follow this conversion
        self.log_line(f"[b]{job.pdf.name}[/b]: {message}")
        for item in self.query_one("#files", ListView).query(JobItem):
            if item.job is job:
                item.query_one(Label).update(job.label())
        if job is self.watching and job.status in ("done", "failed"):
            self.tick_progress()
            if job.status == "done":
                self.unwatch()
        if job.status == "done" and (self.current is None or self.current is job or self.current.status != "done"):
            self.show_job(job)
        elif job.status == "done":
            self.notify(f"{job.pdf.name} is ready")
        if job.status == "failed":
            self.notify(f"{job.pdf.name} could not be converted: {escape(message.removeprefix('failed: '))[:300]}. "
                        "The Log tab (key 6) has the details.", title="Conversion failed", severity="error", timeout=30)

    def log_line(self, text: str) -> None:
        self.query_one("#log", RichLog).write(f"[dim]{time.strftime('%H:%M:%S')}[/] {text}")

    # ------------------------------------------------------------------ showing a document

    @on(ListView.Highlighted, "#files")
    def file_highlighted(self, event: ListView.Highlighted) -> None:
        if not isinstance(event.item, JobItem):
            return
        job = event.item.job
        if job.status == "done":
            if job is self.watching:
                self.unwatch()
            if job is not self.current:
                self.show_job(job)
        elif self.watching is not job:
            self.watch(job)

    # ------------------------------------------------------------------ progress

    def watch(self, job: Job) -> None:
        """Show this job's progress in the Markdown tab instead of a document."""
        self.watching = job
        self.query_one("#progress-panel").display = True
        self.query_one("#markdown-scroll").display = False
        self.tick_progress()

    def unwatch(self) -> None:
        self.watching = None
        self.query_one("#progress-panel").display = False
        self.query_one("#markdown-scroll").display = True

    def tick_progress(self) -> None:
        for item in self.query_one("#files", ListView).query(JobItem):
            if item.job.status == "converting":
                item.query_one(Label).update(item.job.label())
        job = self.watching
        if job is None:
            return
        title, bar, steps = (self.query_one("#progress-title", Label), self.query_one("#progress-bar", ProgressBar),
                             self.query_one("#progress-steps", Static))
        if job.status == "queued":
            ahead = sum(1 for j in self.jobs if j.status in ("queued", "converting") and self.jobs.index(j) < self.jobs.index(job))
            title.update(f"{escape(job.pdf.name)} is waiting: {ahead} PDF{'s' * (ahead != 1)} ahead of it")
            bar.update(progress=0)
            steps.update("")
        elif job.status == "failed":
            title.update(f"[red]{escape(job.pdf.name)} could not be converted[/]")
            steps.update("The reason is in the Log tab (key 6).")
        elif job.progress:
            p = job.progress
            title.update(f"Converting {escape(job.pdf.name)}  {p.fraction() * 100:.0f}%  [dim]{p.elapsed():.0f} s so far[/]")
            bar.update(progress=p.fraction() * 100)
            steps.update("\n".join(p.lines()))

    def show_job(self, job: Job) -> None:
        self.current, self.block = job, None
        self.refresh_elements()
        self.refresh_text()

    def refresh_elements(self) -> None:
        job, view = self.current, self.query_one("#elements", ListView)
        selected = self.block
        view.clear()
        if not job or not job.doc:
            return
        eq = 0
        items = []
        for block in job.doc.blocks:
            if block.kind not in ("figure", "table", "equation"):
                continue
            eq += block.kind == "equation"
            items.append(ElementItem(block, element_label(block, eq)))
        view.extend(items)
        if selected is not None:
            for i, item in enumerate(items):
                if item.block is selected:
                    view.index = i

    def refresh_text(self) -> None:
        job = self.current
        if not job or not job.markdown or not job.markdown.is_file():
            return
        text = job.markdown.read_text(encoding="utf-8")
        self.query_one("#source", TextArea).load_text(text)
        self._markdown_stale = True
        if self.query_one("#tabs", TabbedContent).active == "tab-markdown":
            self.load_markdown()
        self.query_one("#report", Static).update(self.report(job))
        self.sub_title = str(job.markdown)

    def load_markdown(self) -> None:
        job = self.current
        if self._markdown_stale and job and job.markdown and job.markdown.is_file():
            self.query_one("#markdown", Markdown).update(preview(job.markdown.read_text(encoding="utf-8")))
            self._markdown_stale = False

    @on(TabbedContent.TabActivated)
    def tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-markdown":
            self.load_markdown()

    def report(self, job: Job) -> str:
        from pdfdown.quality import scan

        doc = job.doc
        equations = doc.of_kind("equation")
        as_latex = sum(use_latex(b) for b in equations)
        lines = [f"[b]{job.pdf.name}[/b]  →  {job.markdown}", "",
                 f"{len(doc.of_kind('figure'))} figures, {len(doc.of_kind('table'))} tables, "
                 f"{len(equations)} equations ({as_latex} as LaTeX, {len(equations) - as_latex} as images)", "",
                 "[b]What the cleanup did[/b]"]
        lines += [f"• {note}" for note in doc.notes] or ["• nothing"]
        findings = scan(job.markdown)
        lines += ["", "[b]Possible problems left[/b]"]
        lines += [f"• {f}" for f in findings] or ["• none found"]
        return "\n".join(lines)

    # ------------------------------------------------------------------ the selected element

    @on(ListView.Highlighted, "#elements")
    def element_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, ElementItem):
            self.block = event.item.block
            self.show_element()

    @on(ListView.Selected, "#elements")
    def element_selected(self, event: ListView.Selected) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-element"

    def show_element(self) -> None:
        block, job = self.block, self.current
        if not block or not job:
            return
        page, box = area(block)
        kind = {"figure": "Figure", "table": "Table", "equation": "Equation"}[block.kind]
        info = [f"[b]{kind} {block.extra.get('number', '')}[/b]  page {page}"
                + ("  [yellow](hidden: not in the Markdown)[/]" if block.extra.get("hidden") else "")]
        if block.extra.get("crop"):
            info.append("Crop adjusted by you (r in the crop screen resets it).")
        if block.extra.get("caption"):
            info.append(escape(preview(block.extra["caption"][:300])))
        if block.kind == "table":
            how = ("Markdown table" if block.extra.get("grid") and not block.extra.get("spans") and block.extra.get("markdown")
                   else "HTML table (it has merged cells)" if block.extra.get("html") else "image")
            info.append(f"Written as: {how}")
        if block.kind == "equation":
            info.append(f"Written as: {'LaTeX' if use_latex(block) else 'image'}"
                        + (f"  (your choice)" if block.extra.get("use") else "  (automatic)"))
            if block.extra.get("latex_check"):
                by = block.extra.get("latex_by") or block.extra.get("latex_model", "")
                info.append(f"Check: {escape(block.extra['latex_check'])}" + (f"  [dim]LaTeX from {by}[/]" if by else ""))
            info.append("[dim]t LaTeX/image · e edit LaTeX · h try harder · c crop · x hide · v open image[/]")
        else:
            info.append("[dim]c crop · x hide · v open image[/]")
        self.query_one("#element-info", Static).update("\n".join(info))
        latex = block.extra.get("latex", "") if block.kind == "equation" else ""
        self.query_one("#element-latex", Static).update(f"LaTeX:\n{escape(latex)}" if latex else "")
        path = self.image_path(block)
        if path and path.is_file():
            with PILImage.open(path) as image:
                self.query_one("#element-image", Image).image = image.copy()
        self.render_page(job, block)

    def image_path(self, block: Block) -> Path | None:
        job = self.current
        if not job or not job.markdown or not block.extra.get("image"):
            return None
        return job.markdown.parent / block.extra["image"]

    @work(thread=True, exclusive=True, group="page")
    def render_page(self, job: Job, block: Block) -> None:
        import pypdfium2 as pdfium

        page_no, box = area(block)
        scale = 1.5
        with pdfium_lock:
            pdf = pdfium.PdfDocument(str(job.pdf))
            try:
                image = pdf[page_no - 1].render(scale=scale).to_pil().convert("RGB")
            finally:
                pdf.close()
        ImageDraw.Draw(image).rectangle([box.l * scale, box.t * scale, box.r * scale, box.b * scale],
                                        outline=(220, 30, 30), width=3)
        self.call_from_thread(self._show_page, page_no, image)

    def _show_page(self, page_no: int, image) -> None:
        self.query_one("#page-info", Static).update(f"Page {page_no}. The red box is what gets cropped.")
        self.query_one("#page-image", Image).image = image

    # ------------------------------------------------------------------ changes

    def _has_element(self, equation_only: bool = False) -> bool:
        if not self.block or not self.current or not self.current.doc:
            self.notify("Pick a figure, table or equation first", severity="warning")
            return False
        if equation_only and self.block.kind != "equation":
            self.notify("That works on equations only", severity="warning")
            return False
        return True

    def changed(self, block: Block, message: str, recheck: bool = False) -> None:
        """Save the edit, write the Markdown again and refresh the screen."""
        edits.remember(self.current.doc, self.out, block)
        self.log_line(f"{self.current.pdf.name}: {message}")
        self.rewrite(self.current, block, message, recheck)

    @work(thread=True, exclusive=True, group="rewrite")
    def rewrite(self, job: Job, block: Block, message: str, recheck: bool) -> None:
        from pdfdown.pdftext import PdfText

        with pdfium_lock:
            if recheck and block.extra.get("latex"):
                text = PdfText(job.pdf)
                try:
                    edits.recheck(block, text)
                finally:
                    text.close()
            job.markdown = write(job.doc, self.out)
        self.call_from_thread(self._rewritten, job, message)

    def _rewritten(self, job: Job, message: str) -> None:
        if job is self.current:
            self.refresh_elements()
            self.refresh_text()
            self.show_element()
        self.notify(message)

    def action_toggle(self) -> None:
        if not self._has_element(equation_only=True):
            return
        block = self.block
        if use_latex(block):
            block.extra["use"] = "image"
            self.changed(block, "Equation now goes in as an image")
        elif block.extra.get("latex"):
            block.extra["use"] = "latex"
            note = "" if block.extra.get("latex_ok") else " (it did not pass the check: worth a look)"
            self.changed(block, f"Equation now goes in as LaTeX{note}")
        else:
            self.notify("No LaTeX yet: press h to try harder, or e to type it", severity="warning")

    def action_edit(self) -> None:
        if self._has_element(equation_only=True):
            self.with_pdf_text(self._open_editor)

    def _open_editor(self, chars) -> None:
        block = self.block

        def done(latex: str | None) -> None:
            if latex is None:
                return
            if not latex:
                for key in ("latex", "latex_by", "use", "latex_ok", "latex_check"):
                    block.extra.pop(key, None)
                self.changed(block, "Removed the LaTeX; the equation goes in as an image")
                return
            block.extra.update(latex=latex, latex_by="you", use="latex")
            self.changed(block, "Using your LaTeX", recheck=True)

        from pdfdown.tui.screens import LatexScreen

        self.push_screen(LatexScreen(block, self.image_path(block), chars), done)

    @work(thread=True, group="pdftext")
    def with_pdf_text(self, then) -> None:
        """The PDF's characters inside the selected element, read off the UI thread."""
        from pdfdown.pdftext import PdfText

        job, block = self.current, self.block
        page, box = area(block)
        with pdfium_lock:
            text = PdfText(job.pdf)
            try:
                chars = list(text.page(page).inside(box))
            finally:
                text.close()
        self.call_from_thread(then, chars)

    def action_harder(self) -> None:
        if not self._has_element(equation_only=True):
            return
        self.notify("Reading the equation again at other sizes; this takes a few seconds")
        self.try_harder(self.current, self.block)

    @work(thread=True, group="harder")
    def try_harder(self, job: Job, block: Block) -> None:
        import pypdfium2 as pdfium

        from pdfdown.cli import _lazy_model
        from pdfdown.equations import try_harder
        from pdfdown.pdftext import PdfText

        self._model = self._model or _lazy_model()
        with pdfium_lock:
            pdf, text = pdfium.PdfDocument(str(job.pdf)), PdfText(job.pdf)
            try:
                result = try_harder(block, pdf, text, self._model)
            finally:
                text.close()
                pdf.close()
        block.extra.pop("use", None)  # let the check decide again
        message = ("Found LaTeX that matches the PDF" if result.ok
                   else f"Still no match ({result.reason}); kept the image. Press e to fix the closest reading by hand")
        self.call_from_thread(self.changed, block, message)

    def action_crop(self) -> None:
        if not self._has_element():
            return
        from pdfdown.tui.screens import CropScreen

        block, doc = self.block, self.current.doc
        page, box = area(block)
        _page, original = detected_area(block)

        def done(new: Box | None) -> None:
            if new is None:
                return
            if (new.l, new.t, new.r, new.b) == (original.l, original.t, original.r, original.b):
                block.extra.pop("crop", None)
            else:
                block.extra["crop"] = [round(v, 1) for v in (new.l, new.t, new.r, new.b)]
            self.changed(block, "Crop updated", recheck=block.kind == "equation")

        self.push_screen(CropScreen(self.current.pdf, page, box, original, doc.page_sizes[page]), done)

    def action_hide(self) -> None:
        if not self._has_element():
            return
        block = self.block
        block.extra["hidden"] = not block.extra.get("hidden")
        self.changed(block, "Hidden from the Markdown" if block.extra["hidden"] else "Back in the Markdown")

    def action_view(self) -> None:
        if self._has_element() and (path := self.image_path(self.block)):
            self._open(path)

    def action_open_folder(self) -> None:
        if self.current and self.current.markdown:
            self._open(self.current.markdown.parent)
        else:
            self._open(self.out) if self.out.exists() else self.notify("Nothing written yet")

    def _open(self, path: Path) -> None:
        command = "open" if sys.platform == "darwin" else "explorer" if sys.platform == "win32" else "xdg-open"
        try:
            subprocess.Popen([command, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.notify(f"Could not open {path}", severity="error")

    def action_reconvert_ocr(self) -> None:
        """Convert the selected PDF again, reading every page with OCR (for a scan whose text layer is wrong)."""
        from dataclasses import replace

        job = self.watching or self.current
        if not job or job.status not in ("done", "failed"):
            self.notify("Pick a converted PDF first", severity="warning")
            return
        job.options = replace(job.options or self.options, ocr="all")
        self.notify(f"Converting {job.pdf.name} again, reading every page with OCR")
        self._requeue(job)

    def action_reconvert(self) -> None:
        job = self.current
        if job and job.status in ("done", "failed"):
            self._requeue(job)

    def _requeue(self, job: Job) -> None:
        if job.status in ("done", "failed"):
            job.status = "queued"
            with self._queue_lock:
                start = not self._converting
                self._converting = True
            if start:
                self.convert_queue()

    def action_tab(self, name: str) -> None:
        self.query_one("#tabs", TabbedContent).active = f"tab-{name}"

    def action_add(self) -> None:
        from pdfdown.tui.screens import AddScreen

        self.push_screen(AddScreen(), lambda pdfs: self.add_pdfs(pdfs) if pdfs else None)
