# PS5 Payload Build

The PS5 target is a native C `.elf` daemon. It does not embed Python, Node, Electron, or any heavy runtime.

## Native Status

The current native payload is a conservative API-only queue build. The browser
UI was removed from the `.elf`; use the desktop app or REST API as the control
panel.

It intentionally does not use `SceHttp2` or `SceSsl`. Earlier test builds that initialized `SceHttp2` could download a tiny plain HTTP file, but HTTPS failed with `0x8095f00c`, and a later large transfer test was followed by the console becoming unreachable. To reduce kernel-panic risk, the native payload now uses POSIX sockets for plain HTTP only and refuses large or unknown-size files before downloading.

## Runtime Contract

- Default web/API port: `2634`.
- Root path `/` returns a small API-only JSON status message, not a web UI.
- Current test download/log directory: `/data/test`.
- Persistent log: `/data/test/ps5-downloader.log`.
- PID marker: `/data/test/ps5-downloader.pid`.
- Known external log checked by diagnostics: `/data/nanodns/nanodns.log`.
- Local injection logs: `logs/payload-sender/` on this PC.
- Native safety cap: disabled by default, reported as `0`.
- Practical large-file limits are free space, filesystem behavior, server behavior, and network stability.
- Plain `http://` only in the native payload.
- `https://` links are first sent to the configured PC resolver helper. If the helper cannot return a PS5-compatible plain HTTP direct URL, the native queue stores the helper's `manual-action-required` reason.
- Socket send/receive timeout: `20 seconds`.
- Downloads use `HEAD` first; redirects and error responses are refused before a file body is written. Unknown-size responses are allowed but cannot show a reliable percent or ETA until enough metadata is known.
- Completed files are renamed from `.part` only after the received byte count matches `Content-Length`.
- Direct HTTP downloads can resume from a `.part` file when the server advertises `Accept-Ranges: bytes`.
- Fresh known-size HTTP downloads above 8 MiB use up to `4` byte-range segments when the server advertises `Accept-Ranges: bytes`.
- Pause keeps a `.part` file for resume. Cancel removes the known `.part` file so a later retry starts cleanly.
- `GET /api/logs` returns the newest log tail, not the oldest entries.
- `POST /api/links` accepts a pasted block and queues multiple unique URLs.
- Native queue size: `16` in-memory items.
- Active native workers: `1` by default, so the API stays responsive without running several large transfers at once.
- The native UI polls the queue and shows progress bars, bytes, speed, ETA, HTTP status, and errors.
- Direct MediaFire CDN URLs using `https://download*.mediafire.com/...` are converted to `http://download*.mediafire.com/...` before probing/downloading.
- Direct URLs may include `?__ps5_host=original.host`; the payload connects to the URL host/IP while sending `Host: original.host`, then strips that helper parameter from the upstream request.
- Normal MediaFire, Buzzheavier, and other registered page URLs can resolve automatically when `resolver_url` is configured to a portable helper, for example `http://192.168.1.157:2635/api/resolve-native`, as long as the hoster does not require a browser challenge, login, captcha, quota confirmation, or other manual flow.
- If a resolved direct file is HTTPS-only, the helper returns `http://PC_IP:2635/api/relay?...`. The native payload downloads that plain HTTP LAN URL while the helper streams the HTTPS upstream. This keeps the file on the PS5 under `/data/test` but avoids re-enabling native TLS in the payload. Hoster servers that reject `HEAD` are probed through a one-byte ranged `GET` fallback.
- The native UI includes a settings panel for changing the download folder. Paths are validated and must stay under `/data`.
- Settings are persisted to `/data/test/ps5-downloader.conf`.

## Build

```bash
scripts/build-ps5-elf.sh
```

Output:

```text
dist/ps5-downloader.elf
```

SDK path used on this machine:

```text
/home/blurf/PS5/ps5-payload-sdk
```

Direct build:

```bash
PS5_PAYLOAD_SDK=/home/blurf/PS5/ps5-payload-sdk make ps5-elf
```

Temporary test port:

```bash
PS5_PAYLOAD_SDK=/home/blurf/PS5/ps5-payload-sdk make -C src/ps5_payload clean all HTTP_PORT=2635
```

## Safe Deploy

The included sender works with the PS5 payload loader on port `9021` and wraps injection with a safety preflight:

- checks `http://PS5:2634/api/status`
- saves current ps5-downloader, diagnostics, and nanoDNS logs when reachable
- calls `POST /api/shutdown` before sending a replacement
- waits briefly for the old HTTP daemon to stop
- aborts by default if the old daemon still answers, to avoid stacking payloads
- sends the `.elf`
- polls `/api/status`
- saves post-send logs

Use:

```bash
python3 payload_sender.py 192.168.1.204 9021 dist/ps5-downloader.elf
```

The default loader port is also `9021`, so this shorter form is equivalent:

```bash
python3 payload_sender.py 192.168.1.204 dist/ps5-downloader.elf
```

Only use `--force` when you intentionally accept the risk of stacking payloads because the old daemon did not shut down.

Do not stack several test payloads at once. `ps5-payload-dev/websrv` documents that homebrew can crash when another homebrew is already running, and that rest mode can kernel panic while homebrew is running. `ps5-payload-dev/elfldr` documents the safer model of running payloads in individual processes so the loader can keep running if a payload crashes. Keep one ps5-downloader payload active at a time and use `/api/shutdown` before sending a replacement when possible. The sender now does this automatically when the old daemon is still reachable.

References checked:

- https://github.com/ps5-payload-dev/websrv
- https://github.com/ps5-payload-dev/elfldr
- https://github.com/drakmor/nanoDNS

## Native API

- `GET /api/status`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/plugins`
- `GET /api/logs`
- `GET /api/logs/self`
- `GET /api/logs/nanodns`
- `GET /api/diagnostics`
- `GET /api/downloads`
- `POST /api/resolve`
- `POST /api/links`
- `POST /api/shutdown`
- `POST /api/prepare-reload`

## Observed Tests

Tested against PS5 `192.168.1.204`.

- Payload sender successfully sent `.elf` files to `192.168.1.204:9021`.
- A small plain HTTP download worked and wrote to `/data/test`.
- `http://example.com/` downloaded 559 bytes with HTTP 200.
- The supplied legal MediaFire URL resolves on the PC parser to `nnssaw.7z`.
- The resolved MediaFire CDN URL accepts plain HTTP and reports `Content-Length: 96405553`.
- An earlier 92 MB native download attempt with the old `SceHttp2` path was followed by the PS5 becoming unreachable before a response/log could be retrieved.
- The current POSIX-socket range/resume build successfully downloaded the 96,405,553-byte legal MediaFire test file to `/data/test/nnssaw.7z`.
- On the live PS5, native `getaddrinfo` failed for `download2281.mediafire.com` with `rc=4`; the PC helper resolved the CDN IP and submitted `http://IP/...?...__ps5_host=download2281.mediafire.com`, which completed successfully.
- After adding `resolver_url`, pasting the original MediaFire page URL directly into the PS5 API resolved through the helper and detected the completed `/data/test/nnssaw.7z`.
- A public Leaseweb test URL, `http://speedtest.sfo12.us.leaseweb.net/10mb.bin`, resolved through the helper to IP/Host form and completed to `/data/test/10mb.bin`.
- Re-submitting the legal MediaFire test as a direct CDN HTTPS URL converted to HTTP and completed successfully.
- Re-submitting the same direct URL after reinjection detected the existing completed file and returned `completed` without redownloading it.
- The no-cap queue build successfully downloaded a 157,286,400-byte local HTTP test file to `/data/test/large-test-150m.bin`.
- A pasted block with two URLs queued both items; the first 167,772,160-byte local HTTP file showed live byte progress and completed, then the second `http://example.com/` item ran and completed.
- Speed tuning test on the live PS5: 256 KiB native read buffer, larger socket buffers, and throttled byte updates improved a 100 MB Leaseweb single-stream download from roughly 0.8 MiB/s to about 2.5-3.6 MiB/s depending on mirror.
- LAN single-stream test from this PC to PS5 completed a 96 MiB file at about 6.8 MiB/s average and 8.3 MiB/s peak.
- Range-segmented HTTP test against `http://speedtest.belwue.net/100M` completed at about 6.3 MiB/s average and 8.2 MiB/s peak.
- Range-segmented HTTP test against `http://speedtest.tele2.net/100MB.zip` worked but was slower because one or more remote segments lagged; host/server behavior still matters.
- HTTPS through `SceHttp2` failed before status with decimal `-2137657332`, hex `0x8095f00c`.
- `SceHttp2` template version arguments `1`, `2`, and `3` all failed HTTPS with the same error.
- The current safety build removed all `SceHttp2`/`SceSsl` calls and links no PS5 HTTP/TLS libraries.
- 2026-06-18 Rootz regression test: `https://www.rootz.so/d/1zJYQK` resolved through the helper to Rootz `proxy-download`, probed as `Content-Length: 96405553`, downloaded to `/data/test/nnssaw.7z` with 4 ranged segments, and completed in 14.565s at about 6463 KiB/s average.
- 2026-06-18 AkiraBox `.to` sample: `https://akirabox.to/gXeGOobwPGAa/file` now matches the AkiraBox plugin and returns metadata, but the actual download endpoint currently returns a Cloudflare browser challenge to the helper, so the PS5 queue records `manual-action-required` without downloading a broken HTML file.
- 2026-06-18 1fichier sample: `https://1fichier.com/?eb6ooyk6tu3y5pkbhgwb` now matches the 1fichier plugin, parses `nnssaw.7z` and `96.41 MB`, and records manual action because the free page advertises a 60s timed flow and a normal delayed helper POST did not expose a direct public URL.

## Current Blockers

- Native HTTPS/TLS is unresolved.
- Native external DNS resolution is unreliable in payload context; PC-resolved IP plus `__ps5_host` is the current working fallback for public direct HTTP hosts that require a Host header.
- Seamless HTTPS hoster-page handling currently requires a helper process on a PC/LAN device because public file hoster pages are normally HTTPS.
- Native large-file transfer is proven for 96,405,553-byte, 157,286,400-byte, and 167,772,160-byte direct/relayed HTTP files with no fixed code cap. A 1 GB ranged Leaseweb file was partially tested and cancelled cleanly. Multi-GB completion still needs staged testing.
- MediaFire and Rootz page resolution is HTTPS-only on PS5; use the PC resolver/helper until native TLS is implemented.
- Google Drive is HTTPS-only and often needs confirmation/quota/login flows. Those are not bypassed.
- Persistent native queue state is not implemented yet.

See [PS5_STANDALONE.md](PS5_STANDALONE.md) for the standalone PS5-only target
and the safer TLS implementation plan.

## Logs To Check

- `GET /api/logs` or `GET /api/logs/self`: ps5-downloader persistent log from `/data/test/ps5-downloader.log`.
- `GET /api/diagnostics`: known log paths and sizes.
- `GET /api/logs/nanodns`: nanoDNS log from `/data/nanodns/nanodns.log` when nanoDNS is installed and readable.
- Local PC send logs: `logs/payload-sender/`.
- Kernel log: `/dev/klog` is not exposed by ps5-downloader. Use a dedicated klog reader such as `klogsrv` or loader support if we need kernel-level logs later.

## Next Native Work

- Add a transport abstraction so the downloader can use either plain sockets or
  a future TLS transport.
- Build a tiny one-shot HTTPS probe ELF before enabling TLS inside the daemon.
- Add a small dedicated `probe` endpoint for direct HTTP URLs.
- Add persistent queue state under `/data/test` so waiting/completed items survive reinjection.
- Add explicit cancel support.
- Add persistent JSON state under `/data/test`.
- Investigate raw `sceSsl*` usage separately from the daemon, in a tiny one-shot HTTPS probe payload, before putting TLS back into the downloader daemon.
