#!/bin/sh
# pdfdown installer for macOS and Linux. Installs whatever is missing, then pdfdown and its models.
#
#   curl -LsSf https://raw.githubusercontent.com/rafsunsheikh/pdfdown/main/install.sh | sh
#
# Skips anything already there: uv (which brings its own Python), pdfdown, then the models (about 1 GB).
# Settings: PDFDOWN_SPEC (what to install instead of "pdfdown"), PDFDOWN_DEPS_ONLY=1 (only uv),
# PDFDOWN_NO_MODELS=1 (skip the models).
set -eu

say() { printf 'pdfdown: %s\n' "$1"; }

find_uv() {
    for candidate in "$(command -v uv 2>/dev/null || true)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then echo "$candidate"; return 0; fi
    done
    return 1
}

if uv=$(find_uv); then
    say "uv: already installed"
else
    say "installing uv (it fetches Python by itself) ..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        wget -qO- https://astral.sh/uv/install.sh | sh
    fi
    uv=$(find_uv) || { say "uv did not install; see https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
fi
[ "${PDFDOWN_DEPS_ONLY:-}" = "1" ] && exit 0

spec=${PDFDOWN_SPEC:-pdfdown}
say "installing $spec (about 1 GB with PyTorch; a few minutes) ..."
"$uv" tool install --python 3.12 --upgrade "$spec"
"$uv" tool update-shell >/dev/null 2>&1 || true  # keep pdfdown on the PATH in new terminals
bin=$("$uv" tool dir --bin)
if [ "${PDFDOWN_NO_MODELS:-}" != "1" ]; then
    "$bin/pdfdown" setup || say "some models will be downloaded on first use instead"
fi
say "done. Open a new terminal and type: pdfdown"
