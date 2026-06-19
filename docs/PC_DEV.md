# PC Development Build

The PC build is the reference implementation for the queue, parser, plugins, API, and web UI.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
ps5-downloader serve --host 0.0.0.0 --port 2634
```

Run tests:

```bash
python3 -m unittest discover -s tests
```

State defaults to `~/Downloads/ps5-downloader` on Linux/macOS.

For isolated state during testing:

```bash
PS5_DOWNLOADER_HOME=/tmp/ps5-downloader-dev PYTHONPATH=src python3 -m ps5_downloader serve
```
