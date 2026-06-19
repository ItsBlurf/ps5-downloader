# PS5 Standalone Target

The long-term target is a PS5-only workflow: inject `ps5-downloader.elf`, open
`http://PS5_IP:2634`, paste links, and download to `/data/...` without a PC
resolver or relay.

## Current Reality

The current stable native payload is intentionally plain HTTP only. It uses
POSIX sockets because earlier `SceHttp2`/`SceSsl` HTTPS tests failed with
`0x8095f00c`, and one later large-transfer test was followed by the console
becoming unreachable.

The PC helper is therefore a compatibility bridge:

- resolves HTTPS hoster pages;
- follows hoster redirects;
- streams HTTPS-only direct files to the PS5 over plain LAN HTTP;
- keeps the actual saved file on the PS5 under the configured `/data/...` path.

That bridge is useful, but it is not the final standalone design.

## Preferred Standalone Design

Use a user-space TLS library inside the ELF instead of re-enabling `SceHttp2` in
the daemon first.

The native downloader already has most of the HTTP machinery it needs:

- URL parsing;
- socket connect/read/write;
- `HEAD` probing;
- ranged `GET`;
- resume and `.part` files;
- segmented downloads;
- progress logging.

The missing piece is a TLS transport that can replace plain socket `read` and
`write` for `https://` URLs.

## Candidate TLS Libraries

1. BearSSL
   - Small C library.
   - Designed for embedded use.
   - Sans-I/O style fits an existing socket loop.
   - TLS 1.2 only, which is usually enough for file hosters today but not
     guaranteed forever.

2. Mbed TLS
   - Portable C TLS library.
   - Common embedded choice.
   - Supports BIO callbacks over custom sockets.
   - Larger than BearSSL, but more actively maintained.

3. wolfSSL
   - Portable embedded TLS library.
   - TLS 1.3 support.
   - Licensing and build size need review before vendoring.

4. `SceSsl`/`SceHttp2`
   - Available in the PS5 payload SDK.
   - Fastest to wire into a small probe.
   - Highest stability risk based on current project logs.
   - Should only be tested in a tiny one-shot probe ELF before it is used in the
     daemon.

## Implementation Plan

Stage A: portable TLS adapter

- Add a transport abstraction in `src/ps5_payload/main.c`:
  - connect;
  - write request;
  - read headers;
  - stream body;
  - close.
- Keep the existing plain HTTP socket implementation as one transport.
- Add a compile-time `ENABLE_NATIVE_TLS=0/1` switch.
- Do not change queue/storage behavior yet.

Stage B: tiny HTTPS probe ELF

- Build a separate probe, not the main daemon.
- It should fetch only headers and the first 1 KiB from a known legal URL.
- It should write logs to `/data/test/ps5-downloader-tls-probe.log`.
- It must exit after one request.
- Only after this probe survives repeated tests should TLS be enabled in the
  daemon.

Stage C: embedded TLS

- Vendor one reviewed TLS library under `third_party/`.
- Add license text and attribution.
- Cross-compile it with the PS5 payload SDK.
- Use PS5 sockets as the network backend.
- Start with HTTPS `HEAD` and single-connection `GET`.
- Add range and segmented HTTPS only after single-stream HTTPS is stable.

Stage D: native hoster resolvers

- Port only the simple, legal resolver logic into C:
  - direct HTTP/HTTPS;
  - redirects;
  - generic HTML link extraction;
  - MediaFire public links;
  - Buzzheavier public links;
  - VikingFile/direct-file style links.
- Captcha, login, quota, wait-time, and anti-bot browser flows remain
  `manual-action-required`.

## Important Constraint

No downloader can support every hoster fully without a large plugin library and
sometimes a real browser session. The standalone PS5 target can become very
useful for public/direct links and simple public hoster pages, but it should not
claim to bypass captcha, login, Cloudflare browser challenges, quota checks, or
premium restrictions.

## Current Priority

The next technical step is not more hoster-specific code. It is native TLS.
Without native TLS, any HTTPS-only host will keep needing the helper relay.
