# Hoster Support Matrix

This project uses the same practical model as JDownloader-style tools: a small
core plus hoster/decrypter plugins. Some hosts work through generic direct-link
logic, while others need a dedicated plugin.

## Status Meanings

- `native-http`: PS5 payload can download directly today.
- `helper-relay`: PC helper resolves or streams HTTPS to the PS5 over LAN HTTP.
- `plugin`: dedicated parser exists.
- `generic`: generic redirect/direct/HTML handling is expected to work for
  simple public links.
- `manual-action`: captcha, login, quota, wait-time, anti-bot, or premium-only
  behavior may require the user to open the page in a browser or provide a
  direct link.
- `planned`: important hoster, but not implemented beyond generic handling yet.

## Priority Hosts

| Hoster | Current Status | Notes |
| --- | --- | --- |
| MediaFire | plugin, helper-relay, sometimes native-http | Public file pages resolve through the helper. Direct CDN URLs may work as plain HTTP. Captcha/login/abuse pages are manual-action. |
| Buzzheavier | plugin, helper-relay | Uses an HTMX `HX-Redirect` flow when not challenged. Intermittent Cloudflare challenges are retried/cached but not bypassed. |
| VikingFile | generic, helper-relay | Direct HTTPS links work through the relay. The relay handles hosts that reject `HEAD` by probing with one-byte `Range`. |
| AkiraBox | plugin, helper-relay when not challenged, manual-action when challenged | Handles `akirabox.com` and `akirabox.to` links through official `/api/files?url=...` metadata. Current live sample reports metadata but the download endpoint returns a Cloudflare browser challenge to the helper, so it is correctly stopped as `manual-action-required`. |
| Rootz | plugin, helper-relay | Public `/d/<id>` pages resolve through Rootz's `download-by-short` metadata and `proxy-download` endpoint. Live PS5 test completed the 96,405,553-byte `nnssaw.7z` sample through the relay at about 6.3 MiB/s. Password-protected, deleted, unavailable, or challenged files remain manual-action. |
| 1fichier | plugin, manual-action for current free flow | Parses filename/size/wait metadata and prevents generic asset false positives. The current free sample advertises a 60s wait but does not expose a direct URL after a normal delayed POST from the helper. Premium/account/API support is planned; captcha/IP/account/CDN restrictions are not bypassed. |

## Common Famous Hosts To Prioritize

These are common file-hosting targets to evaluate next. They are not all equal:
some expose clean direct links, some require accounts, and some are mostly
anti-bot/browser flows.

- Pixeldrain
- Gofile
- KrakenFiles
- MEGA
- Google Drive public files
- Dropbox shared files
- OneDrive shared files
- Box shared files
- 1fichier premium/API flow
- Rapidgator
- Nitroflare
- KatFile
- DDownload
- Turbobit
- MegaUp
- MixDrop
- Filebin
- BowFile
- BestFile
- Clicknupload

## Policy

The downloader should automate legal public/direct downloads and user-owned
content. It should not bypass captcha, login, Cloudflare browser challenges,
quota/abuse confirmations, premium restrictions, DRM, or account protections.

The most important technical dependency for PS5-only operation is native TLS.
Until that exists, HTTPS-only hosts need the helper relay.
