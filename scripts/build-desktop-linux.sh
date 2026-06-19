#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

mkdir -p release
if command -v pyinstaller >/dev/null 2>&1; then
  PYINSTALLER=(pyinstaller)
elif python3 -m PyInstaller --version >/dev/null 2>&1; then
  PYINSTALLER=(python3 -m PyInstaller)
else
  python3 -m pip install --user pyinstaller
  PYINSTALLER=(python3 -m PyInstaller)
fi
PYTHONPATH=src "${PYINSTALLER[@]}" --clean --noconfirm packaging/ps5-downloader-gui.spec
cp dist/ps5-downloader-gui release/ps5-downloader-gui-linux-x86_64
chmod +x release/ps5-downloader-gui-linux-x86_64
sha256sum release/ps5-downloader-gui-linux-x86_64 > release/ps5-downloader-gui-linux-x86_64.sha256
