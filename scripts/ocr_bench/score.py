"""Score OCR engines on the benchmark from build.py (development helper).

For every document and variant (text layer, clean scan, poor scan) and every engine, convert with pdfdown and
compare the words with the known answer:
  word error rate (WER): wrong, missing and extra words, as a share of the answer's words;
  character error rate (CER): the same for characters (fairer for Bangla, where one vowel sign spoils a word).

    .venv/bin/python scripts/ocr_bench/score.py                 # every engine
    .venv/bin/python scripts/ocr_bench/score.py en easyocr      # one language, one engine
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "out/ocr-bench"
ENGINES = {"en": ["rapidocr", "mac", "easyocr"], "bn": ["tesseract", "easyocr", "rapidocr", "mac"]}


def plain(markdown: str) -> str:
    """The words a reader sees: no Markdown marks, image links, tags or LaTeX."""
    text = re.sub(r"\$\$.*?\$\$", " ", markdown, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\wঀ-৿]+", " ", text)  # keep letters, digits and Bengali signs
    return re.sub(r"\s+", " ", text).strip()


def rates(truth: str, got: str) -> tuple[float, float]:
    words_t, words_g = truth.split(), got.split()
    wer = Levenshtein.distance(words_t, words_g) / max(len(words_t), 1)
    cer = Levenshtein.distance(truth, got) / max(len(truth), 1)
    return wer, cer


def convert(pdf: Path, engine: str | None, lang: str) -> tuple[str, float]:
    from pdfdown.engine import EngineOptions
    from pdfdown.pipeline import run

    languages = ("bn", "en") if lang == "bn" else ()
    if engine == "tesseract":
        languages = ("bn",) if lang == "bn" else ("en",)
    options = EngineOptions(ocr="auto", ocr_engine=engine or "auto", ocr_lang=languages if engine in ("easyocr", "mac", "tesseract") else ())
    start = time.time()
    result = run(pdf, BENCH / "runs" / (engine or "text"), latex=False, options=options)
    return result.markdown.read_text(encoding="utf-8"), time.time() - start


def main() -> None:
    os.environ.setdefault("PDFDOWN_CACHE", str(BENCH / "cache"))
    only_lang = sys.argv[1] if len(sys.argv) > 1 else None
    only_engine = sys.argv[2] if len(sys.argv) > 2 else None
    manifest = json.loads((BENCH / "manifest.json").read_text())
    results = []
    for item in manifest:
        if only_lang and item["lang"] != only_lang:
            continue
        if item["truth"] == "text-layer":
            truth = plain(convert(BENCH / item["text_pdf"], None, item["lang"])[0])
        else:
            truth = plain((BENCH / item["truth"]).read_text(encoding="utf-8"))
        if item["lang"] == "bn":  # how well the real text layer itself reads, before any OCR
            got, seconds = convert(BENCH / item["text_pdf"], None, "bn")
            results.append({"doc": item["id"], "variant": "text layer", "engine": "-", "seconds": seconds,
                            **dict(zip(("wer", "cer"), rates(truth, plain(got))))})
        for engine in ENGINES[item["lang"]]:
            if only_engine and engine != only_engine:
                continue
            for variant in ("clean", "poor"):
                try:
                    got, seconds = convert(BENCH / f"{item['id']}-{variant}.pdf", engine, item["lang"])
                    wer, cer = rates(truth, plain(got))
                except Exception as error:  # an engine that cannot run here
                    wer = cer = float("nan")
                    seconds = 0.0
                    print(f"  {item['id']} {variant} {engine}: failed: {error}", file=sys.stderr)
                results.append({"doc": item["id"], "variant": variant, "engine": engine, "seconds": seconds,
                                "wer": wer, "cer": cer})
                print(f"{item['id']:12} {variant:10} {engine:9} WER {wer:6.1%}  CER {cer:6.1%}  {seconds:5.0f} s", flush=True)
    out = BENCH / f"results-{only_lang or 'all'}-{only_engine or 'all'}.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
