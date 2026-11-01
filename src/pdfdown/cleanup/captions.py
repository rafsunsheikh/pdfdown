"""Captions: join split pieces and attach each caption to its figure or table.

In two-column journals a figure caption often runs across both columns and
Docling returns it in pieces ("Fig. 1 | ... a, ...", then "c, ..."), with
body text from the page in between. Pieces after a caption that starts with
"Fig./Figure/Table N" on the same page, and that do not start a new caption,
are merged into it. Each caption then goes to the nearest figure or table on
its page, and its number names the image file (figure-2.png, table-1.png).
"""

from __future__ import annotations

import re

from pdfdown.document import Block, Document

CAPTION_START = re.compile(r"^\s*(?:<[^>]+>)?\s*(Extended Data\s+)?(Fig(?:ure)?|Table|Supplementary Fig(?:ure)?)\.?\s*([A-Z]?\d+[a-z]?)\b", re.I)


def number_of(text: str) -> tuple[str, str] | None:
    """('figure', '2') for 'Fig. 2 | ...', ('table', '1') for 'Table 1.', ('figure', 'ED3') for 'Extended Data Fig. 3'."""
    m = CAPTION_START.match(text)
    if not m:
        return None
    kind = "table" if m.group(2).lower().startswith("table") else "figure"
    prefix = "ED" if m.group(1) else ("S" if m.group(2).lower().startswith("supplementary") else "")
    return kind, prefix + m.group(3)


PROMOTE = re.compile(r"^\s*(?:Extended Data\s+)?(?:Supplementary\s+)?(?:Fig|Figure|Table)\.?\s*[A-Z]?\d+[a-z]?\s*[|.:]", re.I)


def run(doc: Document, pdf=None) -> None:
    blocks = doc.blocks
    # 1. Promote "Fig. 2 |" and "Extended Data Fig. 3 |" text that Docling labelled as a paragraph
    #    or a heading. The separator after the number keeps "Fig. 2 shows ..." in the body.
    for b in blocks:
        if b.kind in ("paragraph", "heading") and PROMOTE.match(b.text):
            b.kind = "caption"
    # 2. Merge continuation pieces into the caption they belong to: unnumbered caption pieces on the
    #    page, and a paragraph right after an unfinished caption that carries on in lower case.
    merged = 0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind == "caption" and number_of(b.text):
            j = i + 1
            while j < len(blocks):
                nxt = blocks[j]
                carries_on = (j == i + 1 and nxt.kind == "paragraph" and nxt.text[:1].islower()
                              and not re.search(r"[.!?:]\s*$", b.text))
                if (nxt.kind == "caption" or carries_on) and nxt.page == b.page and not number_of(nxt.text):
                    b.text = b.text.rstrip() + " " + nxt.text.lstrip()
                    b.parts += nxt.parts
                    del blocks[j]
                    merged += 1
                    continue
                if nxt.kind in ("caption",) or nxt.page != b.page:
                    break
                j += 1
        i += 1
    # 3. Attach captions: first by Docling's own link between a float and its caption,
    #    then, for captions without one, to the nearest float of the matching kind on the page.
    floats = [b for b in blocks if b.kind in ("figure", "table")]
    attached = 0
    by_ref = {b.extra.get("ref"): b for b in blocks if b.kind == "caption"}
    for f in floats:
        caps = [by_ref[r] for r in f.extra.get("caption_refs", []) if r in by_ref and not by_ref[r].extra.get("attached")]
        if caps:
            f.extra["caption"] = " ".join(c.text for c in caps)
            info = number_of(caps[0].text)
            if info:
                f.extra["number"] = info[1]
            for c in caps:
                c.extra["attached"] = True
                attached += 1
    for cap in [b for b in blocks if b.kind == "caption"]:
        info = number_of(cap.text)
        want = info[0] if info else None
        candidates = [f for f in floats if f.page == cap.page and "caption" not in f.extra and (want is None or f.kind == want)]
        if not candidates:
            continue
        target = min(candidates, key=lambda f: _distance(f, cap))
        target.extra["caption"] = cap.text
        if info:
            target.extra["number"] = info[1]
        cap.extra["attached"] = True
        attached += 1
    attached_text = {_norm(f.extra["caption"])[:60] for f in floats if f.extra.get("caption")}
    before = len(blocks)
    doc.blocks = [b for b in blocks if not (b.kind == "caption" and b.extra.get("attached"))
                  and not (b.kind in ("paragraph", "caption") and _norm(b.text)[:60] in attached_text)]
    used = sum(1 for b in blocks if b.kind == "caption" and b.extra.get("attached"))  # one caption can serve several panels
    duplicates = before - len(doc.blocks) - used
    _number_rest(doc)
    captioned = sum(1 for f in floats if f.extra.get("caption"))
    if merged:
        doc.notes.append(f"Joined {merged} captions that were split into pieces.")
    if captioned:
        doc.notes.append(f"Attached captions to {captioned} figures and tables.")
    if duplicates:
        doc.notes.append(f"Removed {duplicates} duplicate copies of captions.")


def _distance(f: Block, cap: Block) -> float:
    """Vertical gap between a float and a caption, preferring overlap in columns."""
    gap = max(cap.box.t - f.box.b, f.box.t - cap.box.b, 0)
    shared = f.box.overlap_x(cap.box) / max(min(f.box.width, cap.box.width), 1)
    return gap + (0 if shared > 0.3 else 500)


def _number_rest(doc: Document) -> None:
    """Give every figure and table without a caption number the next free one."""
    for kind in ("figure", "table"):
        used = {b.extra.get("number") for b in doc.blocks if b.kind == kind}
        n = 0
        for b in doc.blocks:
            if b.kind == kind and not b.extra.get("number"):
                n += 1
                while f"u{n}" in used:
                    n += 1
                b.extra["number"] = f"u{n}"  # 'u' marks an unnumbered figure in file names


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"<[^>]+>", "", text.lower()))
