# ps5-downloader

`ps5-downloader` is an early lightweight JDownloader-like download manager designed around a jailbroken PS5 workflow: run a small daemon on the PS5 LAN, open a mobile-friendly web UI, paste or send links from a phone/PC/browser, resolve links through plugins, and download into validated local paths.

This repository contains a functional portable PC development build, a desktop control panel, and an injectable PS5 `.elf` daemon. The native `.elf` is API-only, stores visible test files under `/data/test`, and supports queued direct plain HTTP downloads with `.part` resume plus 4-connection segmented downloads when the server advertises byte ranges. There is no fixed native size cap now; practical limits are PS5 storage, filesystem behavior, network stability, and server behavior. Native HTTPS is still disabled after crash testing.

## Legal Use Only

Use this project only for files you are legally allowed to download and store. The plugin system is intended for public/direct links and user-owned content. Captcha bypass, login bypass, quota bypass, DRM circumvention, exploit development, and account credential handling are intentionally out of scope.

## Current Features

- API-only PS5 daemon on port `2634` by default.
- Linux/Windows desktop control panel for sending the ELF, starting/stopping the helper, adding links, and managing the queue.
- REST API for status, downloads, link submission, settings, logs, and plugins.
- Link catcher: `POST /api/links` accepts raw text, JSON, form data, single URLs, hoster pages, or pasted blocks.
- Bookmarklet on the Settings page for "send current page to PS5".
- Queue states: waiting, resolving, downloading, paused, completed, failed, manual-action-required, cancelled.
- Recursive LinkGrabber pipeline: extract URLs, normalize, dedupe, resolve hoster pages, expand packages, follow safe redirects, then queue direct files or visible manual-action items.
- Plugin registry with Direct HTTP, generic redirects, generic HTML extraction, MediaFire, Buzzheavier, Rootz, AkiraBox, 1fichier metadata/manual-flow handling, and GitHub release asset support.
- PC direct HTTP/HTTPS downloader with resume via Range, `.part` files, atomic rename, retries, content-length validation, path validation, and pause/cancel support.
- PS5 native plain HTTP queue downloader using POSIX sockets, with HEAD probing, byte-range resume, 4-connection segmented ranged downloads for fresh large files, `.part` files, no fixed size cap, and one background worker.
- Native web UI with queue cards, progress bars, transferred bytes, speed, ETA, HTTP status, and visible errors.
- Direct MediaFire CDN URLs pasted as `https://download*.mediafire.com/...` are converted to plain HTTP for the native downloader when possible.
- Native settings panel for choosing a validated PS5 download folder under `/data`.
- Link-grabber style queue: pasted text blocks are extracted, deduplicated, queued, resolved, and shown as completed/failed/manual-action-required instead of hiding errors in logs.
- SQLite state database for downloads, logs, and settings.
- CLI for testing: add, resolve, serve, test-plugin, list.
- Unit tests for parser, dedupe, plugin matching, direct resolution, MediaFire fixture parsing, queue transitions, resume logic, filename sanitization, and path traversal prevention.

## Quick Start: PC Development Mode

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
ps5-downloader serve
```

Open:

```text
http://127.0.0.1:2634
```

Run tests:

```bash
python3 -m unittest discover -s tests
```

Run without installing:

```bash
PYTHONPATH=src python3 -m ps5_downloader serve
```

## Desktop App

There is also a simple Linux/Windows desktop control panel so you do not have
to open `http://PS5_IP:2634` in a browser.

Linux:

```bash
scripts/ps5-downloader-gui.sh
```

Windows:

```bat
scripts\ps5-downloader-gui.bat
```

Installed package entry point:

```bash
ps5-downloader-gui
```

The app can:

- send `dist/ps5-downloader.elf` to the PS5 payload loader on port `9021`
- start/stop the LAN resolver/fetcher helper on port `2635`
- connect to the PS5 daemon on port `2634`
- paste/send links to the PS5 queue
- view queue state, progress, speed, errors, and logs
- pause, resume, cancel, or delete queue items
- update the PS5 download path and resolver helper URL

## CLI

```bash
ps5-downloader add "https://example.com/file.zip"
ps5-downloader resolve "https://example.com/file.zip"
ps5-downloader grab "paste text or a hoster/page URL here"
ps5-downloader send-ps5 "https://www.mediafire.com/file/example/file.7z/file" --ps5 192.168.1.204
ps5-downloader serve --host 0.0.0.0 --port 2634
ps5-downloader serve --host 0.0.0.0 --port 2635
ps5-downloader test-plugin "https://www.mediafire.com/file/example/file.zip/file"
ps5-downloader list
```

## API

- `GET /api/status`
- `GET /api/downloads`
- `POST /api/links`
- `POST /api/downloads/:id/start`
- `POST /api/downloads/:id/pause`
- `POST /api/downloads/:id/resume`
- `POST /api/downloads/:id/cancel`
- `DELETE /api/downloads/:id`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/logs`
- `GET /api/plugins`

`POST /api/links` examples:

```bash
curl -X POST http://127.0.0.1:2634/api/links \
  -H 'content-type: application/json' \
  -d '{"text":"https://example.com/file.zip"}'
```

```bash
curl -X POST http://127.0.0.1:2634/api/links \
  --data-binary @links.txt
```

## Settings

Defaults are stored under the platform data directory:

- Linux/macOS: `~/Downloads/ps5-downloader`
- Windows: `%APPDATA%\ps5-downloader`
- PS5 current test path: `/data/test`

Important settings:

- download directory
- temp directory
- max concurrent downloads
- per-download connections placeholder
- speed limit placeholder
- user agent
- conflict behavior: auto-rename, overwrite, or skip

All download and temp paths are validated before writes.

On the native PS5 payload, the download directory must be under `/data`, for example `/data/test` or `/data/ps5-downloader`.

## Supported Hosts

Implemented:

- Direct public HTTP/HTTPS file URLs.
- Generic redirects.
- Simple public HTML pages containing direct downloadable links. The crawler keeps likely file links such as `.pkg`, `.7z`, `.zip`, `.rar`, multipart RARs, ISO images, media files, installers, disk images, and similar downloadable paths instead of queueing page navigation.
- MediaFire public-file pages when the page exposes a normal public download URL and does not require captcha, login, premium access, or bypass behavior.
- Buzzheavier public-file pages when the page exposes its normal `HX-Redirect` direct download response and does not return a browser challenge.
- Rootz public-file pages through its public metadata/proxy-download flow.
- VikingFile direct public HTTPS links through the helper relay.
- AkiraBox `.com` and `.to` public metadata through its official API; downloads still require the actual public endpoint to avoid browser challenges.
- 1fichier public-page metadata parsing with safe `manual-action-required` handling for timed/account/browser flows.
- GitHub release asset URLs.

Like JDownloader, broad hoster support comes from plugins. Unlike JDownloader, this project does not yet have a huge plugin library, so unknown hosters are handled by the generic redirect/HTML crawler first and then fall back to `manual-action-required` or `unsupported`. Captcha, login, premium-only, quota, abuse-check, and anti-bot flows are not bypassed.

The stable native PS5 payload currently avoids HTTPS/TLS page scraping. The long-term target is PS5-only operation after native TLS is implemented; see [docs/PS5_STANDALONE.md](docs/PS5_STANDALONE.md). For seamless page-link grabbing today, run the portable resolver helper on a PC on the same LAN:

```bash
PYTHONPATH=src python3 -m ps5_downloader.cli.main serve --host 0.0.0.0 --port 2635
```

Then open the PS5 UI settings and set:

```text
resolver_url = http://PC_IP:2635/api/resolve-native
```

With that configured, pasting normal public MediaFire and supported hoster page links into the PS5 UI/API resolves through the helper and downloads on the PS5. The helper also normalizes direct public HTTP links into IP/Host-header URLs when PS5 native DNS fails. If a hoster returns Cloudflare, captcha, login, premium, wait-time, quota, or abuse-check pages, the queue shows `manual-action-required` with the plugin reason instead of pretending it can bypass that flow.

For HTTPS-only direct files, the helper returns a LAN relay URL such as `http://PC_IP:2635/api/relay?...`. The PS5 still writes the final file under the configured `/data/...` download folder, while the helper performs the HTTPS request and streams plain HTTP over the LAN. The relay supports `HEAD` and ranged `GET` so native progress, resume, and segmented downloads can still work when the upstream host supports ranges. If a hoster blocks `HEAD`, the relay falls back to a one-byte ranged `GET` to discover filename/size without downloading the whole file during probing.

You can also push a resolved link from the PC directly:

```bash
PYTHONPATH=src python3 -m ps5_downloader.cli.main send-ps5 \
  "https://www.mediafire.com/file/example/file.7z/file" \
  --ps5 192.168.1.204
```

Both flows resolve the public page on the PC, convert direct CDN URLs into PS5-native plain HTTP/IP URLs with the correct Host header, and submit them to the PS5 API.

## Adding Plugins

Create a plugin in `src/ps5_downloader/plugins/` that subclasses `BasePlugin` and returns a `PluginResult`.

Each plugin declares:

- `name`
- `supported_domains`
- `patterns`
- `priority`
- `supports_metadata`
- `supports_folders`

Register it in `src/ps5_downloader/plugins/registry.py`.

## PS5 Limitations

The PC build is Python because it gives a fast, testable daemon and plugin pipeline. The PS5-native path is a small C daemon using the same REST/static UI shape where practical.

Build the injectable PS5 payload:

```bash
scripts/build-ps5-elf.sh
```

Output:

```text
dist/ps5-downloader.elf
```

Build Linux desktop artifacts:

```bash
scripts/build-desktop-linux.sh
scripts/build-appimage.sh
```

Windows `.exe` builds are produced by the GitHub Actions release workflow on
Windows runners when a release tag such as `v0.1.0` is pushed.

See [docs/PS5_BUILD.md](docs/PS5_BUILD.md) for live PS5 test results, logs, HTTPS status, and native API details.
See [docs/HOSTER_SUPPORT.md](docs/HOSTER_SUPPORT.md) for the current hoster support matrix and priority list.

## Troubleshooting

- Server already in use: run `ps5-downloader serve --port 2635`.
- Downloads fail immediately: check the URL is public and direct, then inspect `GET /api/logs`.
- Resume does not work: the server may not support HTTP Range; the downloader restarts or fails safely instead of corrupting the `.part` file.
- MediaFire/Buzzheavier/AkiraBox/1fichier says manual action required: the public page likely requires captcha/login/browser anti-abuse confirmation, account/API support, quota handling, or a host-enforced wait flow, which this project does not bypass.
- PS5 build fails: install/configure `PS5_PAYLOAD_SDK`; see `docs/PS5_BUILD.md`.

## License

MIT. Research references are documented in [docs/RESEARCH.md](docs/RESEARCH.md). No source code was copied from pyLoad, aria2, Gopeed, yt-dlp, JDownloader, or PS5 homebrew projects.
