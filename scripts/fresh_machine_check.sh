#!/bin/bash
# Simulate a machine that has never run pdfdown: empty model and result caches (development helper).
set -u
cd "$(dirname "$0")/.."
wheel=$(ls dist/pdfdown-*.whl | tail -1)
py=${1:-3.12}
dir=out/release/fresh$py
rm -rf "$dir"; mkdir -p "$dir"
uv venv -q -p "$py" "$dir/venv" && uv pip install -q --python "$dir/venv/bin/python" "$wheel" > "$dir/install.log" 2>&1 || { echo "py$py install failed"; tail -20 "$dir/install.log"; exit 1; }
export HF_HOME="$dir/hf" PDFDOWN_CACHE="$dir/cache" TORCH_HOME="$dir/torch" XDG_CACHE_HOME="$dir/xdg" EASYOCR_MODULE_PATH="$dir/easyocr"
s=$(date +%s); "$dir/venv/bin/pdfdown" --batch corpus/office-report.pdf -o "$dir/out" > "$dir/run.log" 2>&1; echo "py$py text PDF: exit $? in $(( $(date +%s)-s )) s, $(grep -c '\$\$' "$dir/out/office-report/office-report.md") LaTeX blocks, models now $(du -sh "$dir/hf" | cut -f1)"
s=$(date +%s); "$dir/venv/bin/pdfdown" --batch --ocr out/release/scanned-report.pdf -o "$dir/out" > "$dir/ocr.log" 2>&1; echo "py$py scanned PDF with --ocr: exit $? in $(( $(date +%s)-s )) s"
head -c 600 "$dir/out/scanned-report/scanned-report.md"; echo
grep -E "Error|Traceback|failed" "$dir/run.log" "$dir/ocr.log" | head -5
