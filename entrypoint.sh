#!/usr/bin/env bash
# ── Runtime entrypoint ──────────────────────────────────────────────────────
# Fetches Camoufox (Firefox binary) if not already present in the persistent
# volume, then hands off to the main CMD ("python main.py api").
#
# This decouples the ~300 MB browser download from the image build layer:
# adding / removing source files or Python deps no longer re-downloads the
# browser, AND the download survives "docker compose down" because it lives on
# a named volume.
#
# The volume is expected at $XDG_CACHE_HOME/camoufox (the default Camoufox
# install prefix).  When the volume is absent (first run), we fetch; on
# subsequent starts the download is already there.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CAMOUFOX_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/camoufox"

if [ -d "$CAMOUFOX_DIR" ] && [ -x "$CAMOUFOX_DIR/camoufox" ]; then
    echo "[entrypoint] Camoufox found at $CAMOUFOX_DIR — skipping fetch"
else
    echo "[entrypoint] Camoufox not found at $CAMOUFOX_DIR — fetching…"
    uv run camoufox fetch
    echo "[entrypoint] Camoufox fetch complete"
fi

exec "$@"
