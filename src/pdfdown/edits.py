"""Changes a person makes in the TUI, kept beside the Markdown so they survive a re-run.

    out/paper/pdfdown-edits.json
    {"#/texts/41": {"use": "image"},
     "#/texts/57": {"latex": "s_t = \\\\alpha x_t", "use": "latex"},
     "#/pictures/3": {"crop": [72.0, 140.5, 540.0, 380.0]},
     "#/pictures/9": {"hidden": true}}

Keys are Docling's element references, which stay the same for the same PDF.
Each value holds only what the person changed:

- use: "latex" or "image", overriding the automatic choice for an equation;
- latex, latex_by: LaTeX the person typed ("you") or got with "try harder"; it is checked again,
  but the person's choice wins;
- crop: the box to crop, in points from the top-left of the page;
- hidden: leave the element out of the Markdown.
"""

from __future__ import annotations

import json
from pathlib import Path

from pdfdown.document import Block, Document

FILE = "pdfdown-edits.json"
FIELDS = ("use", "latex", "latex_by", "crop", "hidden")


def path_for(doc: Document, out_dir: str | Path) -> Path:
    return Path(out_dir) / doc.source.stem / FILE


def load(doc: Document, out_dir: str | Path) -> dict:
    path = path_for(doc, out_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply(doc: Document, edits: dict, pdf_text=None) -> int:
    """Put saved edits back on the blocks; returns how many blocks changed."""
    by_ref = {b.extra.get("ref"): b for b in doc.blocks}
    changed = 0
    for ref, edit in edits.items():
        block = by_ref.get(ref)
        if block is None:
            continue
        for key in FIELDS:
            if key in edit:
                block.extra[key] = edit[key]
        if "latex" in edit:
            block.extra.setdefault("latex_by", "you")
            if pdf_text is not None:
                recheck(block, pdf_text)
        changed += 1
    if changed:
        doc.notes.append(f"Applied your saved changes to {changed} elements ({FILE}).")
    return changed


def remember(doc: Document, out_dir: str | Path, block: Block) -> None:
    """Save this block's edit fields, replacing what was saved for it before."""
    edits = load(doc, out_dir)
    ref = block.extra.get("ref")
    values = {key: block.extra[key] for key in FIELDS if block.extra.get(key) not in (None, False)}
    if not block.extra.get("latex_by"):
        values.pop("latex", None)  # LaTeX from the first automatic reading is not an edit
    if values:
        edits[ref] = values
    else:
        edits.pop(ref, None)
    path = path_for(doc, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(edits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def recheck(block: Block, pdf_text) -> None:
    from pdfdown.equations import check
    from pdfdown.export import area

    page, box = area(block)
    chars = pdf_text.page(page).inside(box)
    result = check(block.extra["latex"], chars)
    block.extra.update(latex_ok=result.ok, latex_check=result.reason)
