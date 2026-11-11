#!/usr/bin/env bash
# Install the app-grid launcher for this checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
APP_DIR="${DATA_HOME}/applications"
ICON_DIR="${DATA_HOME}/icons/hicolor/scalable/apps"

mkdir -p "$APP_DIR" "$ICON_DIR"
cp "${ROOT}/share/icons/hicolor/scalable/apps/wayback-machine-downloader.svg" \
  "${ICON_DIR}/wayback-machine-downloader.svg"
chmod +x "${ROOT}/bin/wayback-downloader-gui"

python3 - << 'PY'
import os
from pathlib import Path

root = Path(os.environ["ROOT"])
data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
template = (root / "share/applications/wayback-machine-downloader.desktop.in").read_text()
exec_path = str(root / "bin" / "wayback-downloader-gui").replace("\\", "\\\\").replace('"', '\\"')
desktop = template.replace("@EXEC@", f'"{exec_path}"')
desktop = desktop.replace(
    "@ICON@",
    str(root / "share/icons/hicolor/scalable/apps/wayback-machine-downloader.svg"),
)
destination = data_home / "applications" / "wayback-machine-downloader.desktop"
destination.write_text(desktop)
print(f"Installed {destination}")
PY

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" || true
fi
if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
  gtk4-update-icon-cache -f -t "${DATA_HOME}/icons/hicolor" || true
fi
