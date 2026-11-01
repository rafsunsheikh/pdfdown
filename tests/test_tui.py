"""The TUI, driven by Textual's test pilot on the office report, with a stand-in equation model."""

import asyncio
import json
from pathlib import Path

import pytest

from pdfdown.tui.app import ElementItem, PdfdownApp

REPORT = Path(__file__).resolve().parents[1] / "corpus" / "office-report.pdf"


class FakeModel:
    """Reads every equation as the same LaTeX, which matches the office report's equation."""

    name = "fake"

    def __call__(self, image):
        return r"s_{t}=\alpha x_{t}+(1-\alpha)s_{t-1}"


async def wait_for(pilot, condition, seconds=120):
    for _ in range(int(seconds / 0.2)):
        if condition():
            return
        await pilot.pause(0.2)
    raise AssertionError("timed out")


@pytest.mark.asyncio
async def test_convert_toggle_and_hide(tmp_path):
    app = PdfdownApp([REPORT], tmp_path)
    app._model = FakeModel()
    async with app.run_test(size=(140, 45)) as pilot:
        await wait_for(pilot, lambda: app.jobs[0].status == "done")
        job = app.jobs[0]
        markdown = job.markdown.read_text()
        assert "$$\ns_{t}=\\alpha x_{t}+(1-\\alpha)s_{t-1}\n$$" in markdown  # the stand-in LaTeX passed the check
        items = list(app.query(ElementItem))
        assert [i.block.kind for i in items].count("equation") == 1
        view = app.query_one("#elements")
        view.focus()
        view.index = next(n for n, i in enumerate(items) if i.block.kind == "equation")
        await pilot.press("t")
        await wait_for(pilot, lambda: "equations/eq-1.png" in job.markdown.read_text())
        view.index = next(n for n, i in enumerate(app.query(ElementItem)) if i.block.kind == "figure")
        await pilot.pause(0.3)
        await pilot.press("x")
        await wait_for(pilot, lambda: "figures/figure-1.png" not in job.markdown.read_text())
        edits = json.loads((job.markdown.parent / "pdfdown-edits.json").read_text())
        assert sorted(edits.values(), key=str) == [{"hidden": True}, {"use": "image"}]


def test_edits_survive_a_rerun(tmp_path):
    from pdfdown.pipeline import run

    first = run(REPORT, tmp_path, equation_model=FakeModel())
    figure = first.doc.of_kind("figure")[0]
    (first.markdown.parent / "pdfdown-edits.json").write_text(json.dumps({figure.extra["ref"]: {"hidden": True}}))
    again = run(REPORT, tmp_path, equation_model=FakeModel())
    assert "figures/figure-1.png" not in again.markdown.read_text()


@pytest.mark.asyncio
async def test_first_conversion_in_the_app(tmp_path, monkeypatch):
    # A PDF never seen before goes through model loading inside the app. That used to fail with
    # "bad value(s) in fds_to_keep" (tqdm starting a helper process with Textual's stand-in stderr).
    monkeypatch.setenv("PDFDOWN_CACHE", str(tmp_path / "empty-cache"))
    app = PdfdownApp([REPORT], tmp_path / "out", latex=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await wait_for(pilot, lambda: app.jobs[0].status in ("done", "failed"), seconds=300)
        assert app.jobs[0].status == "done", app.jobs[0].message
