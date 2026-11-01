"""Scan a converted Markdown file for the problems PDF conversion typically leaves.

Used by the tests, by `pdfdown check`, and by the TUI's report panel. Each
finding is a plain sentence with an example, so a reader can judge it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Finding:
    kind: str
    count: int
    example: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.count} (e.g. {self.example!r})"


def _prose(md: str) -> list[str]:
    """Paragraph lines only: no headings, images, tables, code, math or HTML blocks."""
    out, in_code = [], False
    for line in md.splitlines():
        if line.startswith("```") or line.strip() == "$$":
            in_code = not in_code
            continue
        if in_code or not line.strip() or line.startswith(("#", "!", "|", "<table", "<", "*Fig", "*Table")):
            continue
        out.append(line)
    return out


def scan(md_path: str | Path) -> list[Finding]:
    path = Path(md_path)
    md = path.read_text(encoding="utf-8")
    prose = _prose(md)
    text = "\n".join(prose)
    found: list[Finding] = []

    def add(kind: str, matches: list[str]) -> None:
        if matches:
            found.append(Finding(kind, len(matches), matches[0][:80]))

    words = Counter(w.lower() for w in re.findall(r"[A-Za-z]{2,}", text))
    split = [f"{a} {b}" for a, b in re.findall(r"(?<![’'\w])([a-zA-Z]) ([a-z]{2,})\b", text)
             if a.lower() not in ("a", "i") and words[(a + b).lower()] > 0]  # "j ust": "just" is a word in this document
    add("letters split apart", re.findall(r"(?:\b[a-z] ){3,}[a-z]\b", text) + split)
    add("leftover line-end hyphens", re.findall(r"\b[a-z]{2,}- [a-z]{2,}\b", text))
    add("unbalanced superscript tags", [l for l in prose if l.count("<sup>") != l.count("</sup>") or l.count("<sub>") != l.count("</sub>")])
    add("paragraphs ending mid-sentence", [l[-60:] for l in prose
                                           if not l.startswith(("-", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
                                           and len(l) > 80 and not re.search(r"[.!?:;)\]\"'”’>]\s*$|<sup>[^<]*</sup>\s*$", l)])
    counts = Counter(l.strip() for l in md.splitlines() if len(l.strip()) > 40)
    add("duplicated lines", [l for l, n in counts.items() if n > 1])
    caption_heads = Counter(re.sub(r"\W+", " ", m.lower()).strip()
                            for m in re.findall(r"(?m)^\*?((?:Fig(?:ure)?|Table)\s*\.?\s*\d+\s*[:|.][^*\n]{0,40})", md))
    add("captions written twice", [c for c, n in caption_heads.items() if n > 1])
    missing = [m for m in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md) if not (path.parent / m).is_file()]
    add("images that do not exist", missing)
    return found
