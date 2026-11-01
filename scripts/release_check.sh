#!/bin/bash
# Install the built wheel into a fresh venv per Python version and convert a sample (development helper).
set -u
cd "$(dirname "$0")/.."
wheel=$(ls dist/pdfdown-*.whl | tail -1)
for py in 3.11 3.12 3.13; do
  dir=out/release/py$py
  rm -rf "$dir"; mkdir -p "$dir"
  start=$(date +%s)
  if ! uv venv -q -p "$py" "$dir/venv" || ! uv pip install -q --python "$dir/venv/bin/python" "$wheel" > "$dir/install.log" 2>&1; then
    echo "py$py: INSTALL FAILED"; tail -5 "$dir/install.log"; continue
  fi
  version=$("$dir/venv/bin/pdfdown" --version 2>&1)
  PDFDOWN_CACHE="$dir/cache" "$dir/venv/bin/pdfdown" --batch corpus/office-report.pdf -o "$dir/out" > "$dir/run.log" 2>&1
  code=$?
  md="$dir/out/office-report/office-report.md"
  echo "py$py: $version, exit $code, $(wc -l < "$md" 2>/dev/null || echo 'no') lines, $(ls "$dir/out/office-report/figures" 2>/dev/null | wc -l | tr -d ' ') figures, $(( $(date +%s) - start )) s"
  grep -E "failed|Error|Traceback" "$dir/run.log" | head -3
done
