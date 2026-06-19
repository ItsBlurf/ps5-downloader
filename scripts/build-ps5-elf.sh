#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_DIR="${PS5_PAYLOAD_SDK:-/home/blurf/PS5/ps5-payload-sdk}"

if [[ ! -d "${SDK_DIR}" ]]; then
  echo "PS5 payload SDK not found: ${SDK_DIR}" >&2
  echo "Download it from https://github.com/ps5-payload-dev/sdk/releases/latest/download/ps5-payload-sdk.zip" >&2
  exit 1
fi

export PS5_PAYLOAD_SDK="${SDK_DIR}"
make -C "${ROOT_DIR}/src/ps5_payload" clean all HTTP_PORT="${HTTP_PORT:-2634}"
mkdir -p "${ROOT_DIR}/dist"
cp "${ROOT_DIR}/src/ps5_payload/ps5-downloader.elf" "${ROOT_DIR}/dist/ps5-downloader.elf"
sha256sum "${ROOT_DIR}/dist/ps5-downloader.elf"
