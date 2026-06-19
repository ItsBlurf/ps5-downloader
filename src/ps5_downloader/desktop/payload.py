from __future__ import annotations

import hashlib
import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_LOADER_PORT = 9021
DEFAULT_HTTP_PORT = 2634
KNOWN_HTTP_PORTS = (2634, 2644)


@dataclass
class SendResult:
    bytes_sent: int
    sha256: str
    status: dict | None
    notes: list[str]


def http_request(host: str, http_port: int, method: str, path: str, timeout: float = 2.0) -> tuple[int, bytes]:
    request = Request(f"http://{host}:{http_port}{path}", method=method)
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


def send_payload_file(
    elf_path: str | Path,
    host: str,
    loader_port: int = DEFAULT_LOADER_PORT,
    http_port: int = DEFAULT_HTTP_PORT,
    force: bool = False,
) -> SendResult:
    path = Path(elf_path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    notes: list[str] = []

    checked: list[int] = []
    for port in (http_port, *KNOWN_HTTP_PORTS):
        if port in checked:
            continue
        checked.append(port)
        existing = daemon_status(host, port)
        if not existing:
            notes.append(f"no daemon detected on HTTP port {port}")
            continue
        notes.append(f"daemon detected on port {port}: {existing}")
        try:
            status, body = http_request(host, port, "POST", "/api/shutdown", timeout=3.0)
            notes.append(f"shutdown port {port}: status={status} body={body.decode('utf-8', 'replace').strip()}")
        except (OSError, URLError, TimeoutError) as exc:
            notes.append(f"shutdown request failed on port {port}: {exc}")
        if wait_for_daemon_down(host, port):
            notes.append(f"daemon on port {port} stopped")
        elif not force:
            raise RuntimeError("old daemon still responds after shutdown; not sending payload")
        else:
            notes.append(f"daemon on port {port} still responds; continuing because force=True")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((host, loader_port))
        sock.sendall(data)
    finally:
        sock.close()
    notes.append(f"sent {len(data)} bytes to {host}:{loader_port}")
    status = wait_for_daemon_up(host, http_port)
    if status:
        notes.append(f"new daemon status: {status}")
    else:
        notes.append("new daemon did not answer HTTP status within wait window")
    return SendResult(bytes_sent=len(data), sha256=digest, status=status, notes=notes)
