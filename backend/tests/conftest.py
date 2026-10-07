"""Jalur import untuk suite uji — arahkan ke root paket `app`."""
import os
import sys
from pathlib import Path

# Shell host dapat mengekspor DEBUG=release (non-boolean) — pydantic_settings
# memprioritaskan env var atas .env dan akan menolak nilai itu. Normalisasi
# sebelum app.config diimpor.
if os.environ.get("DEBUG", "").lower() not in {
    "true", "false", "1", "0", "yes", "no", "on", "off",
}:
    os.environ["DEBUG"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
