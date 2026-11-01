"""The progress panel's numbers, without the app."""

from pdfdown.tui.progress import JobProgress


def test_bar_follows_expected_time(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFDOWN_CACHE", str(tmp_path))
    p = JobProgress(latex=True, per_page=1.0, per_equation=3.0, reader_loaded=True)
    p.on_step("layout", 0, 27)
    p.on_step("cleanup", 0, 33)  # 27 pages took ~27 s; 33 equations will take ~99 s
    p.on_step("write", 0, 0)
    p.on_step("equations", 16, 33)
    assert 0.45 < p.fraction() < 0.65  # half the equations read is about half the work, not 87%
    p.on_step("done", 0, 0)
    assert p.fraction() == 1.0


def test_lines_and_learning(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFDOWN_CACHE", str(tmp_path))
    p = JobProgress(latex=False)
    p.on_step("layout-cached", 0, 2)
    assert "already analysed (cached)" in p.lines()[0] and len(p.lines()) == 3  # no equation step without LaTeX
    p.on_step("cleanup", 0, 0)
    assert p.lines()[0].startswith("[green]✓")


def test_loading_the_equation_reader_is_its_own_step(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFDOWN_CACHE", str(tmp_path))
    p = JobProgress(latex=True, per_page=1.0, per_equation=3.0, to_load=20.0)
    for step, done, total in [("layout", 0, 10), ("cleanup", 0, 5), ("write", 0, 0), ("equations", 0, 5)]:
        p.on_step(step, done, total)
    p.on_step("model", 0, 5)
    assert any("Load the equation reader" in line and "⟳" in line for line in p.lines())
    before = p.fraction()
    p.on_step("equations", 1, 5)
    assert p.fraction() > before
    assert not any("Load the equation reader" in line for line in JobProgress(latex=True, reader_loaded=True).lines())
