"""How far a conversion has got, for the progress panel and the file list.

The pipeline reports its steps (see pipeline.run). Steps with a count, like equations, are exact. The layout
analysis gives no progress while it runs, so its share of the bar is estimated from the number of pages and
the speed this computer showed on earlier PDFs, which is saved in the cache folder and improves with use.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from pdfdown.engine import cache_dir

STEPS = [
    ("layout", "Analyse the page layout"),
    ("cleanup", "Clean up the text"),
    ("write", "Write the Markdown and crop figures, tables and equations"),
    ("model", "Load the equation reader (once per session)"),
    ("equations", "Read equations as LaTeX and check them against the PDF"),
]
DEFAULTS = {"seconds_per_page": 3.0, "seconds_per_equation": 3.0, "seconds_to_load_reader": 20.0,
            "seconds_per_ocr_page": 8.0}
SPEED_FILE = "speed.json"


def _speeds() -> dict:
    try:
        return {**DEFAULTS, **json.loads((cache_dir() / SPEED_FILE).read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def seconds_per_page() -> float:
    return float(_speeds()["seconds_per_page"])


def seconds_per_equation() -> float:
    return float(_speeds()["seconds_per_equation"])


def remember_speed(key: str, measured: float) -> None:
    """Keep a running average of this computer's speed, so the next estimate is closer."""
    if not 0.05 < measured < 120:
        return
    speeds = _speeds()
    speeds[key] = round(0.5 * float(speeds[key]) + 0.5 * measured, 2)
    try:
        (cache_dir() / SPEED_FILE).write_text(json.dumps(speeds), encoding="utf-8")
    except OSError:
        pass


@dataclass
class JobProgress:
    latex: bool
    pages: int = 0
    cached: bool = False
    step: str = ""
    done: int = 0
    total: int = 0
    started: float = field(default_factory=time.time)
    step_started: float = field(default_factory=time.time)
    took: dict[str, float] = field(default_factory=dict)  # finished step -> seconds
    per_page: float = field(default_factory=seconds_per_page)
    per_equation: float = field(default_factory=seconds_per_equation)
    equations: int | None = None  # known once the layout is analysed
    ocr_pages: int = 0  # pages read with OCR (slower)
    per_ocr_page: float = field(default_factory=lambda: float(_speeds()["seconds_per_ocr_page"]))
    reader_loaded: bool = False  # the equation reader is already in memory (from an earlier PDF this session)
    to_load: float = field(default_factory=lambda: float(_speeds()["seconds_to_load_reader"]))
    equation_started: float = field(default_factory=time.time)

    def on_step(self, name: str, done: int, total: int) -> None:
        now = time.time()
        if name in ("layout", "layout-cached"):
            self.pages, self.cached, self.ocr_pages, name = total, name == "layout-cached", done, "layout"
        if name == "cleanup":
            self.equations = total
        if name != self.step:
            if self.step:
                self.took[self.step] = now - self.step_started
                if self.step == "layout" and not self.cached and self.pages:
                    text_pages = self.pages - self.ocr_pages
                    if self.ocr_pages:  # learn the OCR speed from what is left after the text pages
                        rest = self.took["layout"] - text_pages * self.per_page
                        remember_speed("seconds_per_ocr_page", max(rest, 0.5) / self.ocr_pages)
                    else:
                        remember_speed("seconds_per_page", self.took["layout"] / self.pages)
                if self.step == "equations" and name == "done" and self.total:
                    remember_speed("seconds_per_equation", self.took["equations"] / self.total)
                if self.step == "model":
                    remember_speed("seconds_to_load_reader", self.took["model"])
            self.step, self.step_started = name, now
        if name != "equations" or done != self.done:
            self.equation_started = now
        self.done, self.total = done, total

    def _weights(self) -> dict[str, float]:
        """Each step's share of the bar: the seconds it is expected to take on this computer."""
        pages = max(self.pages, 1)
        equations = self.equations if self.equations is not None else pages  # about one a page, until counted
        return {"layout": 1.0 if self.cached else self.layout_estimate(),
                "cleanup": 0.5 + 0.05 * pages,
                "write": 0.5 + 0.1 * pages,
                "model": self.to_load if self.latex and not self.reader_loaded else 0.0,
                "equations": equations * self.per_equation if self.latex else 0.0}

    def _within(self, now: float) -> float:
        """How far through the current step, from 0 to 1."""
        if self.step == "layout":
            return 0.5 if self.cached else min(0.95, (now - self.step_started) / self.layout_estimate())
        if self.step == "model":
            return min(0.95, (now - self.step_started) / max(self.to_load, 1.0))
        if self.step == "equations":
            if not self.total:
                return 0.0
            within = min(0.9, (now - self.equation_started) / max(self.per_equation, 0.5))  # keep moving between equations
            return (self.done + within) / self.total
        return 0.5

    def layout_estimate(self) -> float:
        text_pages = max(self.pages - self.ocr_pages, 0)
        return max(text_pages * self.per_page + self.ocr_pages * self.per_ocr_page, 1.0)

    def fraction(self, now: float | None = None) -> float:
        now = now or time.time()
        if self.step == "done":
            return 1.0
        weights = self._weights()
        reached = 0.0
        for name, _ in STEPS:
            if name == self.step:
                reached += weights[name] * self._within(now)
                break
            reached += weights[name]
        return min(reached / sum(weights.values()), 0.99)

    def lines(self, now: float | None = None) -> list[str]:
        """The checklist under the bar, one line per step."""
        now = now or time.time()
        order = [name for name, _ in STEPS]
        current = order.index(self.step) if self.step in order else (len(order) if self.step == "done" else -1)
        out = []
        for i, (name, text) in enumerate(STEPS):
            if name in ("equations", "model") and not self.latex:
                continue
            if name == "model" and (self.reader_loaded or (i < current and name not in self.took)) and self.step != "model":
                continue  # already loaded, or not needed because every equation was read before
            if name == "layout" and self.cached:
                text = "Page layout already analysed (cached)"
            elif name == "layout" and self.ocr_pages:
                scans = "every page" if self.ocr_pages == self.pages else f"{self.ocr_pages} scanned page{'s' * (self.ocr_pages != 1)}"
                text = f"Analyse the page layout and read {scans} with OCR"
            if i < current:
                seconds = self.took.get(name)
                out.append(f"[green]✓[/] {text}" + (f"  [dim]{seconds:.0f} s[/]" if seconds and seconds >= 1 else ""))
            elif i == current:
                out.append(f"[b]⟳ {text}[/]  {self.detail(now)}")
            else:
                out.append(f"[dim]·  {text}[/]")
        return out

    def detail(self, now: float) -> str:
        if self.step == "layout" and not self.cached:
            left = max(self.layout_estimate() - (now - self.step_started), 0)
            pages = f"{self.pages} page{'s' * (self.pages != 1)}"
            return f"[dim]{pages}, about {left:.0f} s left (estimated)[/]" if left >= 1 else f"[dim]{pages}, almost done[/]"
        if self.step == "equations":
            return f"{self.done} of {self.total}" if self.total else ""
        if self.step == "model":
            return f"[dim]{now - self.step_started:.0f} s[/]"
        return ""

    def elapsed(self, now: float | None = None) -> float:
        return (now or time.time()) - self.started
