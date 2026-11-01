"""Pop-up screens: add PDFs, edit an equation's LaTeX, adjust a crop."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import ImageDraw
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Footer, Input, Label, Static, TextArea
from textual_image.widget import Image

from pdfdown.document import Block, Box
from pdfdown.locks import pdfium_lock


class PdfTree(DirectoryTree):
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() == ".pdf")]


class AddScreen(ModalScreen[list[Path]]):
    """Pick a PDF in the tree, or type a path to a PDF or a folder."""

    BINDINGS = [Binding("escape", "dismiss([])", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add PDFs: choose a file below, or type a path to a PDF or a folder and press Enter")
            yield Input(placeholder="~/Papers/attention.pdf", id="path")
            yield PdfTree(Path.cwd(), id="tree")
            yield Footer()

    @on(Input.Submitted)
    def typed(self, event: Input.Submitted) -> None:
        from pdfdown.cli import expand

        path = Path(event.value.strip()).expanduser()
        if not path.exists():
            self.notify(f"Not found: {path}", severity="error")
            return
        pdfs = [p for p in expand([path]) if p.suffix.lower() == ".pdf"]
        if not pdfs:
            self.notify("No PDFs there", severity="warning")
            return
        self.dismiss(pdfs)

    @on(DirectoryTree.FileSelected)
    def picked(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss([event.path])


class LatexScreen(ModalScreen[str | None]):
    """Type or fix LaTeX; it is checked against the PDF as you type."""

    BINDINGS = [Binding("ctrl+s", "save", "Use this LaTeX"), Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, block: Block, image_path: Path | None, chars) -> None:
        super().__init__()
        self.block, self.image_path, self.chars = block, image_path, chars

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("The equation in the PDF:")
            if self.image_path and self.image_path.is_file():
                yield Image(str(self.image_path), classes="equation")
            yield Label("LaTeX (Ctrl+S to use it, Esc to cancel):")
            yield TextArea(self.block.extra.get("latex", ""), id="latex", soft_wrap=True)
            yield Static(id="verdict")
            yield Footer()

    def on_mount(self) -> None:
        self._verdict(self.query_one(TextArea).text)

    @on(TextArea.Changed)
    def changed(self, event: TextArea.Changed) -> None:
        self._verdict(event.text_area.text)

    def _verdict(self, latex: str) -> None:
        from pdfdown.equations import check

        result = check(latex.strip(), self.chars)
        mark = "[green]✓ passes the check[/]" if result.ok else "[yellow]✗ does not pass[/]"
        self.query_one("#verdict", Static).update(f"{mark}: {result.reason}. It will be used either way if you save.")

    def action_save(self) -> None:
        self.dismiss(self.query_one(TextArea).text.strip())


EDGES = ("top", "right", "bottom", "left")
STEPS = (1.0, 5.0, 20.0)


class CropScreen(ModalScreen[Box | None]):
    """Move the four edges of a crop, with the page around it for context."""

    BINDINGS = [
        Binding("tab", "edge", "Next edge"),
        Binding("up", "move(0, -1)", "Up", show=False),
        Binding("down", "move(0, 1)", "Down", show=False),
        Binding("left", "move(-1, 0)", "Left", show=False),
        Binding("right", "move(1, 0)", "Right", show=False),
        Binding("s", "step", "Step size"),
        Binding("r", "reset", "Reset"),
        Binding("enter", "save", "Use this crop"),
        Binding("escape", "dismiss(None)", "Cancel"),
    ]

    def __init__(self, pdf_path: Path, page: int, box: Box, original: Box, page_size: tuple[float, float]) -> None:
        super().__init__()
        self.pdf_path, self.page, self.original, self.page_size = pdf_path, page, original, page_size
        self.box = Box(box.l, box.t, box.r, box.b)
        self.edge, self.step = 0, 1

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(id="crop-help")
            yield Image(id="crop-view")
            yield Footer()

    def on_mount(self) -> None:
        self._update()

    def _update(self) -> None:
        b = self.box
        self.query_one("#crop-help", Static).update(
            f"Moving the [b]{EDGES[self.edge]}[/] edge by {STEPS[self.step]:g} pt with the arrow keys (Tab: next edge, s: step size). "
            f"Box: left {b.l:.0f}, top {b.t:.0f}, right {b.r:.0f}, bottom {b.b:.0f} pt. Red is the crop.")
        self._draw()

    @work(thread=True, exclusive=True)
    def _draw(self) -> None:
        import pypdfium2 as pdfium

        b, margin, scale = self.box, 36.0, 2.0
        w, h = self.page_size
        view = Box(max(b.l - margin, 0), max(b.t - margin, 0), min(b.r + margin, w), min(b.b + margin, h))
        with pdfium_lock:
            pdf = pdfium.PdfDocument(str(self.pdf_path))
            try:
                page = pdf[self.page - 1]
                image = page.render(scale=scale, crop=(view.l, h - view.b, w - view.r, view.t)).to_pil().convert("RGB")
            finally:
                pdf.close()
        draw = ImageDraw.Draw(image)
        rect = [(b.l - view.l) * scale, (b.t - view.t) * scale, (b.r - view.l) * scale, (b.b - view.t) * scale]
        draw.rectangle(rect, outline=(220, 30, 30), width=3)
        self.app.call_from_thread(setattr, self.query_one("#crop-view", Image), "image", image)

    def action_edge(self) -> None:
        self.edge = (self.edge + 1) % 4
        self._update()

    def action_step(self) -> None:
        self.step = (self.step + 1) % len(STEPS)
        self._update()

    def action_move(self, dx: int, dy: int) -> None:
        d, b, edge = STEPS[self.step], self.box, EDGES[self.edge]
        w, h = self.page_size
        if edge == "top" and dy:
            b.t = min(max(b.t + dy * d, 0), b.b - 4)
        elif edge == "bottom" and dy:
            b.b = max(min(b.b + dy * d, h), b.t + 4)
        elif edge == "left" and dx:
            b.l = min(max(b.l + dx * d, 0), b.r - 4)
        elif edge == "right" and dx:
            b.r = max(min(b.r + dx * d, w), b.l + 4)
        else:
            self.notify(f"The {edge} edge moves {'up and down' if edge in ('top', 'bottom') else 'left and right'}")
            return
        self._update()

    def action_reset(self) -> None:
        o = self.original
        self.box = Box(o.l, o.t, o.r, o.b)
        self._update()

    def action_save(self) -> None:
        self.dismiss(self.box)
