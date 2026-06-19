# Build Output

Run:

```bash
scripts/build-ps5-elf.sh
```

The injectable payload is copied here as:

```text
dist/ps5-downloader.elf
```

For this repository the current release ELF is committed so the desktop app and
GitHub release workflow have a known default payload to send/upload. Rebuild it
with `scripts/build-ps5-elf.sh` after native payload changes.
