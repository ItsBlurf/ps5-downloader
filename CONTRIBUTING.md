# Contributing

Keep this project lightweight and explicit.

- Use public, legal download workflows only.
- Do not add captcha/login/quota bypass behavior.
- Do not add large dependencies without documenting why they are needed.
- Keep plugins isolated from the core queue/downloader.
- Add tests for parser, queue, storage, path handling, plugin parsing, and download behavior.
- Keep PS5-specific assumptions in `src/ps5_downloader/platform/ps5` or `docs/PS5_BUILD.md`.
- Never hardcode user-specific absolute paths.

Run before submitting changes:

```bash
python3 -m unittest discover -s tests
```
