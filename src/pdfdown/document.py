"""pdfdown's own document model: an ordered list of blocks.

Every cleanup step reads and rewrites this list, so the steps stay small
and testable, and do not depend on Docling's internal types. Positions are
in PDF points with the origin at the TOP-LEFT of the page (y grows down),
which is what both pypdfium2 cropping and people expect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

TEXT_KINDS = {"title", "heading", "paragraph", "list_item", "caption", "footnote", "reference", "code"}
FLOAT_KINDS = {"figure", "table", "equation"}


@dataclass
class Box:
    l: float
    t: float
    r: float
    b: float

    @property
    def width(self) -> float:
        return self.r - self.l

    @property
    def height(self) -> float:
        return self.b - self.t

    @property
    def cx(self) -> float:
        return (self.l + self.r) / 2

    def union(self, other: Box) -> Box:
        return Box(min(self.l, other.l), min(self.t, other.t), max(self.r, other.r), max(self.b, other.b))

    def contains(self, other: Box, slack: float = 2.0) -> bool:
        return (other.l >= self.l - slack and other.r <= self.r + slack
                and other.t >= self.t - slack and other.b <= self.b + slack)

    def overlap_x(self, other: Box) -> float:
        return max(0.0, min(self.r, other.r) - max(self.l, other.l))


@dataclass
class Block:
    kind: str  # title, heading, paragraph, list_item, caption, footnote, reference, code, figure, table, equation, furniture
    text: str = ""
    page: int = 0  # 1-based
    box: Box | None = None
    level: int = 1  # heading level
    extra: dict = field(default_factory=dict)  # table markdown/html, latex, image path, figure number, caption ...
    parts: list[tuple[int, Box]] = field(default_factory=list)  # every (page, box) merged into this block

    def __post_init__(self) -> None:
        if not self.parts and self.box is not None:
            self.parts = [(self.page, self.box)]


@dataclass
class Document:
    source: Path
    blocks: list[Block]
    page_sizes: dict[int, tuple[float, float]]  # page -> (width, height) in points
    title: str = ""
    notes: list[str] = field(default_factory=list)  # what the cleanup did, shown in the TUI and the report
    ocr_pages: list[int] = field(default_factory=list)  # pages whose text came from OCR, not from the PDF's text layer

    def of_kind(self, *kinds: str) -> list[Block]:
        return [b for b in self.blocks if b.kind in kinds]


_LABEL_KIND = {
    "title": "title",
    "section_header": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list_item": "list_item",
    "caption": "caption",
    "footnote": "footnote",
    "reference": "reference",
    "code": "code",
    "formula": "equation",
    "picture": "figure",
    "chart": "figure",
    "table": "table",
    "page_header": "furniture",
    "page_footer": "furniture",
    "checkbox_selected": "paragraph",
    "checkbox_unselected": "paragraph",
    "key_value_region": "paragraph",
    "form": "paragraph",
    "document_index": "paragraph",
}


def from_docling(doc, source: str | Path) -> Document:
    """Flatten a DoclingDocument into pdfdown blocks, in Docling's reading order."""
    from docling_core.types.doc import ContentLayer, TableItem

    sizes = {no: (p.size.width, p.size.height) for no, p in doc.pages.items()}
    blocks: list[Block] = []
    layers = {ContentLayer.BODY, ContentLayer.FURNITURE}
    for item, _level in doc.iterate_items(with_groups=False, included_content_layers=layers):
        label = str(getattr(item, "label", "text")).split(".")[-1].lower()
        kind = _LABEL_KIND.get(label, "paragraph")
        if getattr(item, "content_layer", None) == ContentLayer.FURNITURE:
            kind = "furniture"
        prov = item.prov or []
        parts = []
        for p in prov:
            height = sizes.get(p.page_no, (0, 0))[1]
            bb = p.bbox.to_top_left_origin(page_height=height)
            parts.append((p.page_no, Box(bb.l, bb.t, bb.r, bb.b)))
        if not parts:
            continue
        page, box = parts[0]
        block = Block(kind=kind, text=(getattr(item, "text", "") or "").strip(), page=page, box=box, parts=parts)
        block.extra["ref"] = item.self_ref
        if getattr(item, "captions", None):
            block.extra["caption_refs"] = [c.cref for c in item.captions]
        if kind == "heading":
            block.level = int(getattr(item, "level", 1) or 1)
        if isinstance(item, TableItem):
            md = item.export_to_markdown(doc=doc)
            block.extra["markdown"] = md[md.index("|"):] if "|" in md else md  # Docling puts the caption above the table
            block.extra["html"] = item.export_to_html(doc=doc, add_caption=False)
            block.extra["grid"] = [[cell.text for cell in row] for row in item.data.grid]
            block.extra["spans"] = any(c.row_span > 1 or c.col_span > 1 for c in item.data.table_cells)
        if kind == "equation":
            block.extra["latex_docling"] = (getattr(item, "text", "") or "").strip()
            block.extra["orig"] = (getattr(item, "orig", "") or "").strip()
        blocks.append(block)
    return Document(source=Path(source), blocks=blocks, page_sizes=sizes)
