#!/usr/bin/env python3
"""Safer PS5 ELF sender for ps5-downloader.

The sender keeps the old positional form:

    python3 payload_sender.py <host> <file>
    python3 payload_sender.py <host> <loader-port> <file>

For this project the default loader port is 9021 and the daemon HTTP port is
2634. Before sending a replacement ELF, it tries to collect logs and asks the
currently running ps5-downloader daemon to shut down.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_LOADER_PORT = 9021
DEFAULT_HTTP_PORT = 2634
KNOWN_HTTP_PORTS = (2634, 2644)
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs" / "payload-sender"


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def http_request(host: str, http_port: int, method: str, path: str, body: bytes | None = None, timeout: float = 2.0) -> tuple[int, bytes]:
    url = f"http://{host}:{http_port}{path}"
    request = Request(url, data=body, method=method)
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def daemon_status(host: str, http_port: int) -> dict | None:
    try:
        status, body = http_request(host, http_port, "GET", "/api/status")
    except (OSError, URLError, TimeoutError):
        return None
    if status != 200:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {"raw": body.decode("utf-8", "replace")}


def save_remote_logs(host: str, http_port: int, label: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    for name, path in (
        ("self", "/api/logs"),
        ("diagnostics", "/api/diagnostics"),
        ("nanodns", "/api/logs/nanodns"),
    ):
        try:
            status, body = http_request(host, http_port, "GET", path, timeout=3.0)
        except (OSError, URLError, TimeoutError) as exc:
            body = f"unavailable: {exc}\n".encode()
            status = 0
        out = LOG_DIR / f"{stamp}-{label}-{name}.log"
        out.write_bytes(f"# GET {path} status={status}\n".encode() + body)
        print(f"saved {name} log: {out}")


def wait_for_daemon_down(host: str, http_port: int, timeout_s: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if daemon_status(host, http_port) is None:
            return True
        time.sleep(0.5)
    return False


def wait_for_daemon_up(host: str, http_port: int, timeout_s: float = 12.0) -> dict | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = daemon_status(host, http_port)
        if status is not None:
            return status
        time.sleep(0.5)
    return None


def shutdown_known_ports(host: str, primary_port: int, no_shutdown: bool, force: bool, note) -> None:
    checked: list[int] = []
    for port in (primary_port, *KNOWN_HTTP_PORTS):
        if port in checked:
            continue
        checked.append(port)
        existing = daemon_status(host, port)
        if not existing:
            note(f"no known daemon detected on HTTP port {port}")
            continue
        note(f"known daemon detected on port {port}: {existing}")
        save_remote_logs(host, port, f"before-shutdown-{port}")
        if no_shutdown:
            note(f"shutdown skipped for port {port} by --no-shutdown")
            continue
        try:
            status, body = http_request(host, port, "POST", "/api/shutdown", timeout=3.0)
            note(f"shutdown port {port} response status={status} body={body.decode('utf-8', 'replace').strip()}")
        except (OSError, URLError, TimeoutError) as exc:
            note(f"shutdown request failed for port {port}: {exc}")
        if wait_for_daemon_down(host, port):
            note(f"daemon on port {port} stopped responding")
        else:
            note(f"daemon on port {port} still responds after shutdown wait")
            if not force:
                note("aborting send to avoid stacking payloads; reboot/restart loader or use --force only when intentional")
                raise SystemExit(2)
            note("continuing because --force was provided")


def send_payload(
    file_path: Path,
    host: str,
    loader_port: int = DEFAULT_LOADER_PORT,
    http_port: int = DEFAULT_HTTP_PORT,
    no_shutdown: bool = False,
    force: bool = False,
) -> None:
    data = file_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    local_log = LOG_DIR / f"{now_stamp()}-send.log"

    with local_log.open("a", encoding="utf-8") as log:
        def note(message: str) -> None:
            line = f"{datetime.now(timezone.utc).isoformat()} {message}"
            print(message)
            log.write(line + "\n")
            log.flush()

        note(f"payload={file_path} bytes={len(data)} sha256={digest}")
        note(f"target host={host} loader_port={loader_port} http_port={http_port}")

        shutdown_known_ports(host, http_port, no_shutdown, force, note)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            sock.connect((host, loader_port))
            sock.sendall(data)
        finally:
            sock.close()
        note(f"sent {len(data)} bytes to {host}:{loader_port}")

        status = wait_for_daemon_up(host, http_port)
        if status:
            note(f"new daemon status: {status}")
            save_remote_logs(host, http_port, "after-send")
        else:
            note("new daemon did not answer HTTP status within wait window")

        note(f"local send log: {local_log}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely send ps5-downloader ELF payloads.")
    parser.add_argument("host")
    parser.add_argument("port_or_file")
    parser.add_argument("file", nargs="?")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--no-shutdown", action="store_true", help="do not call /api/shutdown before sending")
    parser.add_argument("--force", action="store_true", help="send even if the existing daemon does not shut down")
    args = parser.parse_args(argv)
    if args.file is None:
        args.loader_port = DEFAULT_LOADER_PORT
        args.file_path = Path(args.port_or_file)
    else:
        args.loader_port = int(args.port_or_file)
        args.file_path = Path(args.file)
    return args


if __name__ == "__main__":
    parsed = parse_args(sys.argv[1:])
    send_payload(parsed.file_path, parsed.host, parsed.loader_port, parsed.http_port, parsed.no_shutdown, parsed.force)
