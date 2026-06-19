# nanoDNS Notes

The PS5 used for testing runs nanoDNS by drakmor:

- https://github.com/drakmor/nanoDNS

Relevant behavior from the project README:

- The payload listens on local port `53`.
- Runtime files live under `/data/nanodns`.
- Config is `/data/nanodns/nanodns.ini`.
- It forwards non-overridden DNS queries to configured upstream resolvers.
- It logs DNS requests/responses to the configured log file.
- `bind=127.0.0.1` is the default; `bind=0.0.0.0` listens on all local IPv4 interfaces.

Observed with `ps5-downloader`:

- PS5 networking and DNS are sufficient for plain HTTP downloads from the native payload.
- HTTPS currently fails inside `sceHttp2SendRequest` with `0x8095f00c`; this is not a DNS failure because HTTP works.

Keep PSN/update blocking policy separate from this downloader.
