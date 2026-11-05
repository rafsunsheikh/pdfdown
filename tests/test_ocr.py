"""OCR: scanned pages are found and read by themselves, Bangla reads right with and without OCR."""

import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from pdfdown.engine import EngineOptions, scanned_pages
from pdfdown.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
sys.path.insert(0, str(ROOT / "scripts/ocr_bench"))
from score import plain, rates  # noqa: E402


@pytest.fixture
def scanned_report(tmp_path):
    """The office report as an image-only PDF, like a scan."""
    pdf = pdfium.PdfDocument(str(CORPUS / "office-report.pdf"))
    pages = [page.render(scale=200 / 72).to_pil().convert("RGB") for page in pdf]
    pdf.close()
    path = tmp_path / "scanned-report.pdf"
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=200)
    return path


def test_scanned_pages_are_found():
    with_text = pdfium.PdfDocument(str(CORPUS / "office-report.pdf"))
    assert scanned_pages(with_text) == []
    with_text.close()


def test_scans_are_read_without_asking(scanned_report, tmp_path):
    result = run(scanned_report, tmp_path / "out", latex=False)  # default: ocr="auto"
    text = result.markdown.read_text(encoding="utf-8")
    assert result.doc.ocr_pages == [1, 2]
    assert "Annual Operations Review 2025" in text and "Revenue rose 18%" in text
    assert any("read with OCR" in note for note in result.doc.notes)
    nothing = run(scanned_report, tmp_path / "off", latex=False, options=EngineOptions(ocr="off"))
    assert "Revenue" not in nothing.markdown.read_text(encoding="utf-8")  # what you got before: images only


def test_bangla_text_layer_reads_right(tmp_path):
    truth = plain((CORPUS / "bangla-sample.txt").read_text(encoding="utf-8"))
    got = plain(run(CORPUS / "bangla-sample.pdf", tmp_path, latex=False).markdown.read_text(encoding="utf-8"))
    wer, cer = rates(truth, got)
    assert cer < 0.03, f"characters wrong: {cer:.1%}"  # was 15% when pdfdown rebuilt Bangla character by character


def test_bangla_scan_is_read_with_ocr(tmp_path):
    from pdfdown.cli import engine_options

    truth = plain((CORPUS / "bangla-sample.txt").read_text(encoding="utf-8"))
    result = run(CORPUS / "bangla-sample-scan.pdf", tmp_path, latex=False, options=engine_options(lang="bn"))
    wer, cer = rates(truth, plain(result.markdown.read_text(encoding="utf-8")))
    assert result.doc.ocr_pages == [1]
    assert cer < 0.12, f"characters wrong: {cer:.1%}"  # was 72-79% with Docling's default confidence filter
