from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    pass


@dataclass
class DownloadRow:
    id: str
    name: str
    state: str
    path: str
    bytes_done: int
    total_bytes: int | None
    percent: float
    speed_bps: float
    http_status: str
    error: str


def api_base(host: str, port: int) -> str:
    host = (host or "").strip()
    if not host:
        raise ValueError("host is required")
    if host.startswith("http://"):
        base = host.rstrip("/")
    elif host.startswith("https://"):
        raise ValueError("only http:// API endpoints are supported")
    else:
        base = f"http://{host}:{int(port)}"
    return base


def request_json(base: str, path: str, method: str = "GET", data: bytes | None = None, timeout: float = 5.0):
    request = Request(f"{base}{path}", data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body:
                return None
            return json.loads(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            message = payload.get("error") or body
        except json.JSONDecodeError:
            message = body or str(exc)
        raise ApiError(message) from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise ApiError(str(exc)) from exc


def request_text(base: str, path: str, method: str = "GET", text: str = "", timeout: float = 5.0) -> str:
    data = text.encode("utf-8") if method != "GET" else None
    request = Request(f"{base}{path}", data=data, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(body or str(exc)) from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise ApiError(str(exc)) from exc


def normalize_download(item: dict) -> DownloadRow:
    item_id = str(item.get("id", ""))
    name = item.get("filename") or item.get("original_url") or f"download {item_id}"
    bytes_done = int(item.get("downloaded_bytes", item.get("bytes", 0)) or 0)
    total = item.get("size", item.get("content_length"))
    total_bytes = int(total) if total not in {None, "", 0} else None
    percent = float(item.get("percent", 0.0) or 0.0)
    if not percent and total_bytes:
        percent = min(100.0, bytes_done * 100.0 / total_bytes)
    return DownloadRow(
        id=item_id,
        name=str(name),
        state=str(item.get("state", "")),
        path=str(item.get("path", "")),
        bytes_done=bytes_done,
        total_bytes=total_bytes,
        percent=percent,
        speed_bps=float(item.get("speed_bps", 0.0) or 0.0),
        http_status=str(item.get("http_status") or ""),
        error=str(item.get("error") or ""),
    )


class Ps5Api:
    def __init__(self, host: str = "192.168.1.204", port: int = 2634) -> None:
        self.host = host
        self.port = port

    @property
    def base(self) -> str:
        return api_base(self.host, self.port)

    def status(self) -> dict:
        return request_json(self.base, "/api/status")

    def downloads(self) -> list[DownloadRow]:
        data = request_json(self.base, "/api/downloads")
        return [normalize_download(item) for item in (data or [])]

    def logs(self) -> str:
        data = request_json(self.base, "/api/logs")
        if isinstance(data, list):
            lines = []
            for row in reversed(data):
                lines.append(f"{row.get('level', '')} {row.get('message', '')}".strip())
            return "\n".join(lines)
        return str(data or "")

    def add_links(self, text: str) -> str:
        return request_text(self.base, "/api/links", method="POST", text=text, timeout=30.0)

    def action(self, item_id: str, action: str) -> str:
        if action == "delete":
            return request_text(self.base, f"/api/downloads/{item_id}", method="DELETE")
        return request_text(self.base, f"/api/downloads/{item_id}/{action}", method="POST")

    def settings(self) -> dict:
        return request_json(self.base, "/api/settings")

    def update_settings(self, values: dict) -> dict:
        payload = json.dumps(values).encode("utf-8")
        return request_json(self.base, "/api/settings", method="PUT", data=payload)


def resolve_native_url(helper_host: str, helper_port: int, target_url: str) -> str:
    base = api_base(helper_host, helper_port)
    query = urlencode({"url": target_url})
    return request_text(base, f"/api/resolve-native?{query}", timeout=30.0)
