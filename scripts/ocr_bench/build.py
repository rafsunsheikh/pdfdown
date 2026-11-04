"""Build the OCR benchmark: scans whose correct text is known (development helper; output in out/ocr-bench).

English: pages of the CC BY example papers. The answer is pdfdown's normal conversion of the same pages,
which reads the PDF's real text layer.
Bangla: Bangla Wikipedia article text (CC BY-SA, kept local), set as a PDF by Chrome. The answer is the
article text itself, not anything extracted from a PDF.

Each document becomes a "clean" scan (200 dpi) and a "poor" one (150 dpi, tilted, speckled, blurred and
JPEG-compressed, like a photocopy), saved as image-only PDFs.

    .venv/bin/python scripts/ocr_bench/build.py
"""
from __future__ import annotations

import html
import io
import json
import random
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out/ocr-bench"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ENGLISH = [("dpo", ROOT / "examples/dpo/dpo.pdf", [1, 4]),
           ("physics", ROOT / "examples/imaginary-magnetic-fields/imaginary-magnetic-fields.pdf", [1, 3]),
           ("llama", ROOT / "examples/llama/llama.pdf", [1, 2])]
BANGLA = ["রবীন্দ্রনাথ ঠাকুর", "ঢাকা", "পদ্মা নদী"]
BANGLA_CHARS = 2500


def subset(src: Path, pages: list[int], dst: Path) -> None:
    pdf, new = pdfium.PdfDocument(str(src)), pdfium.PdfDocument.new()
    new.import_pages(pdf, [p - 1 for p in pages])
    new.save(str(dst))
    new.close()
    pdf.close()


def scan(src: Path, dst: Path, quality: str, seed: int = 7) -> None:
    rng = random.Random(seed)
    pdf = pdfium.PdfDocument(str(src))
    images = []
    for page in pdf:
        dpi = 200 if quality == "clean" else 150
        im = page.render(scale=dpi / 72).to_pil().convert("L")
        if quality == "poor":
            im = im.rotate(rng.uniform(0.4, 0.9) * rng.choice([-1, 1]), expand=True, fillcolor=255)
            im = im.filter(ImageFilter.GaussianBlur(0.6))
            px = im.load()
            for _ in range(im.width * im.height // 60):  # speckle
                x, y = rng.randrange(im.width), rng.randrange(im.height)
                px[x, y] = rng.choice([0, 255, 128])
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=35)
            im = Image.open(io.BytesIO(buf.getvalue())).convert("L")
        images.append(im.convert("RGB"))
    pdf.close()
    images[0].save(dst, save_all=True, append_images=images[1:], resolution=200 if quality == "clean" else 150)


def wiki_text(title: str) -> str:
    query = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
                                    "format": "json", "formatversion": 2})
    request = urllib.request.Request(f"https://bn.wikipedia.org/w/api.php?{query}",
                                     headers={"User-Agent": "pdfdown-ocr-benchmark/0.1 (local testing)"})
    data = json.load(urllib.request.urlopen(request, timeout=60))
    text = data["query"]["pages"][0]["extract"]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and not p.startswith("=")]
    out, size = [], 0
    for p in paragraphs:
        if size > BANGLA_CHARS:
            break
        out.append(p)
        size += len(p)
    return "\n\n".join(out)


def bangla_pdf(title: str, text: str, dst: Path) -> None:
    body = "".join(f"<p>{html.escape(p)}</p>" for p in text.split("\n\n"))
    page = f"""<!doctype html><meta charset="utf-8"><style>
    @page {{ size: A4; margin: 22mm 20mm; }} body {{ font: 12pt/1.6 "Kohinoor Bangla", "Bangla Sangam MN", sans-serif; }}
    h1 {{ font-size: 20pt; }} p {{ text-align: justify; margin: 0 0 8pt; }}</style>
    <h1>{html.escape(title)}</h1>{body}"""
    work = dst.with_suffix(".html")
    work.write_text(page, encoding="utf-8")
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={dst}",
                    work.as_uri()], check=True, capture_output=True)
    work.unlink()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, src, pages in ENGLISH:
        text_pdf = OUT / f"en-{name}-text.pdf"
        subset(src, pages, text_pdf)
        manifest.append({"id": f"en-{name}", "lang": "en", "text_pdf": text_pdf.name, "truth": "text-layer"})
    for i, title in enumerate(BANGLA, start=1):
        text = wiki_text(title)
        (OUT / f"bn-{i}.truth.txt").write_text(f"{title}\n\n{text}", encoding="utf-8")
        bangla_pdf(title, text, OUT / f"bn-{i}-text.pdf")
        manifest.append({"id": f"bn-{i}", "lang": "bn", "text_pdf": f"bn-{i}-text.pdf", "truth": f"bn-{i}.truth.txt",
                         "title": title})
    for item in manifest:
        for quality in ("clean", "poor"):
            scan(OUT / item["text_pdf"], OUT / f"{item['id']}-{quality}.pdf", quality)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(manifest)} documents, {len(manifest) * 2} scans in {OUT}")


if __name__ == "__main__":
    main()
