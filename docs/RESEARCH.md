# Research Notes

This repository uses the listed projects for architecture inspiration only. No source code was copied.

## pyLoad / pyload-ng

Useful ideas:

- Lightweight headless download manager with browser management.
- Plugin-driven hoster/decrypter/addon split.
- Separate storage, temp, and user-data directories.
- REST/OpenAPI surface for clients.

License note: pyLoad is AGPL-3.0. This project does not copy pyLoad code.

Sources:

- https://pypi.org/project/pyload-ng/
- https://pyload.net/

## aria2

Useful ideas:

- Resume and partial-download behavior.
- RPC-style daemon control.
- Explicit concurrency, retry, and connection controls.
- Treat options as API-controlled task state.

This project implements a small HTTP API rather than JSON-RPC, but keeps the daemon/control split.

Source:

- https://aria2.github.io/manual/en/html/aria2c.html

## Gopeed

Useful ideas:

- Daemon/API plus UI split.
- Modern extension-oriented download manager shape.
- Remote management from another device on the same network.

Sources:

- https://gopeed.com/
- https://github.com/GopeedLab/gopeed

## yt-dlp

Useful ideas:

- Extractor registry pattern.
- URL matching before extraction.
- Generic fallback extractor for plain pages.

This project keeps plugins much smaller: hoster/decrypter/direct/generic HTML.

Source:

- https://github.com/yt-dlp/yt-dlp

## JDownloader

Useful ideas:

- LinkGrabber concept: pasted text is resolved before download.
- Separate hoster and decrypter plugins.
- Packages/folders and mirror/archive ideas for later stages.

License/source note: JDownloader has GPL components and mixed availability. This project does not copy JDownloader source or plugin code.

Source:

- https://support.jdownloader.org/en/knowledgebase/article/list-of-supported-websites-plugins

## PS5 Homebrew References

Useful ideas:

- PS5 webserver payloads serve a web UI over LAN.
- `/data/homebrew` and `/data` paths are common writable/homebrew locations.
- PS5 payload SDK expects `PS5_PAYLOAD_SDK` and emits `.elf` payloads.

Sources:

- https://github.com/ps5-payload-dev/websrv
- https://github.com/ps5-payload-dev/sdk
- https://github.com/john-tornblom/ps5-payload-sdk

## Chosen Architecture

Stage 1 is a portable Python stdlib daemon for Linux/macOS/Windows:

- Static web UI and REST API on port `2634`.
- SQLite queue/state.
- Plugin registry and link resolver.
- Direct HTTP downloader with resume and `.part` files.
- Unit tests for the core behavior.

Stage 2 is a PS5-native C/C++ payload:

- Keep the same API and static UI contract.
- Store config/state under `/data/ps5-downloader` by default.
- Use validated download/temp roots.
- Implement only the stable subset first: direct HTTP, queue, static web UI, JSON state or SQLite if available.
- Document SDK/toolchain blockers instead of faking a working PS5 `.elf`.
