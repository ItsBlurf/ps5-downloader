# ps5-downloader 0.1.0

Initial public release.

## Highlights

- API-only PS5 `.elf` daemon on port `2634`.
- Desktop control panel for Linux/Windows.
- Desktop panel can send the ELF to the PS5 payload loader on port `9021`.
- Desktop panel can start/stop the LAN resolver helper on port `2635`.
- Queue management from desktop: add links, view progress, pause/resume/cancel/delete.
- Direct HTTP downloads on PS5 with `.part` files and 4 ranged segments when supported.
- Helper relay for HTTPS hoster files.
- Public hoster plugins for MediaFire, Buzzheavier, Rootz, AkiraBox metadata, 1fichier metadata/manual flow, GitHub releases, generic redirects, and generic HTML file links.
- Native API hardening: client socket timeouts, detached request handling, and full CORS method headers so one stalled request does not freeze the control API.

## Assets

- `ps5-downloader-0.1.0.elf`: PS5 payload daemon.
- `ps5-downloader-gui-linux-x86_64`: Linux desktop binary.
- `PS5_Downloader-0.1.0-x86_64.AppImage`: Linux AppImage.
- `ps5-downloader-gui-windows-x86_64.exe`: built by GitHub Actions on the release tag.

## Limitations

- Native PS5 HTTPS is disabled for stability; use the desktop helper/fetcher for HTTPS hoster links.
- Captcha, login, Cloudflare browser challenges, premium restrictions, and quota/abuse confirmations are not bypassed.
- Windows EXE is built on GitHub Actions, not locally from Linux.
