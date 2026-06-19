from __future__ import annotations

import json
import mimetypes
import socket
import re
import shutil
import time
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlparse, urlsplit
from urllib.request import Request, urlopen

from ps5_downloader.core.downloader import QueueManager
from ps5_downloader.core.models import PluginResultType
from ps5_downloader.core.resolver import LinkResolver
from ps5_downloader.core.settings import SettingsStore
from ps5_downloader.core.storage import Storage
from ps5_downloader.core.utils import ps5_native_http_url


class App:
    def __init__(self, storage: Storage, settings_store: SettingsStore) -> None:
        self.storage = storage
        self.settings_store = settings_store
        self.settings = settings_store.load()
        self.resolver = LinkResolver()
        self.queue = QueueManager(storage, self.settings)
        self.native_direct_cache: dict[str, tuple[float, list[str]]] = {}


def make_handler(app: App):
    static_root = Path(__file__).with_name("static")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ps5-downloader/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/status":
                self.send_json({"ok": True, "downloads": len(app.storage.list_downloads())})
            elif path == "/api/resolve-native":
                self.handle_resolve_native(parsed.query)
            elif path == "/api/relay":
                self.handle_relay(parsed.query, head_only=False)
            elif path == "/api/downloads":
                self.send_json([item.to_dict() for item in app.storage.list_downloads()])
            elif path == "/api/settings":
                self.send_json(app.settings.to_dict())
            elif path == "/api/logs":
                self.send_json(app.storage.logs())
            elif path == "/api/plugins":
                self.send_json(app.resolver.registry.list_plugins())
            else:
                self.serve_static(path, static_root)

        def do_HEAD(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/relay":
                self.handle_relay(parsed.query, head_only=True)
                return
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/shutdown":
                self.send_json({"ok": True, "shutdown": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "/api/links":
                self.handle_links()
                return
            match = re.fullmatch(r"/api/downloads/([^/]+)/(start|pause|resume|cancel)", path)
            if match:
                self.handle_action(match.group(1), match.group(2))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "not found")

        def do_PUT(self) -> None:
            if urlparse(self.path).path != "/api/settings":
                self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
                return
            try:
                data = self.read_json()
                app.settings = app.settings_store.update(data)
                app.queue.settings = app.settings
                app.queue.engine.settings = app.settings
                self.send_json(app.settings.to_dict())
            except Exception as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

        def do_DELETE(self) -> None:
            match = re.fullmatch(r"/api/downloads/([^/]+)", urlparse(self.path).path)
            if not match:
                self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
                return
            self.send_json({"deleted": app.queue.delete(match.group(1))})

        def handle_links(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8", errors="replace")
            ctype = self.headers.get("Content-Type", "")
            if "application/json" in ctype:
                payload = json.loads(raw or "{}")
                text = payload.get("text") or payload.get("url") or ""
            elif "application/x-www-form-urlencoded" in ctype:
                form = parse_qs(raw)
                text = "\n".join(form.get("text", []) + form.get("url", []))
            else:
                text = raw
            results = app.resolver.resolve_text(text)
            items = []
            for result in results:
                items.extend(app.queue.add_result(result))
            self.send_json({"results": [result.to_dict() for result in results], "downloads": [item.to_dict() for item in items]})

        def handle_resolve_native(self, query: str) -> None:
            params = parse_qs(query)
            text = "\n".join(params.get("url", []) + params.get("text", []))
            if not text:
                self.send_text("no url provided\n", HTTPStatus.BAD_REQUEST)
                return
            results = []
            direct_urls = []
            for attempt in range(3):
                results = app.resolver.resolve_text(text)
                direct_urls = [
                    result.resolved_url
                    for result in results
                    if result.type == PluginResultType.DIRECT_FILE and result.resolved_url
                ]
                retryable = any(
                    result.type == PluginResultType.MANUAL_ACTION_REQUIRED and result.plugin == "buzzheavier-public"
                    for result in results
                )
                if direct_urls or not retryable or attempt == 2:
                    break
                app.storage.log("warning", f"native resolver retrying intermittent hoster challenge for {text[:120]}")
                time.sleep(0.75)
            urls = []
            reasons = []
            if direct_urls:
                app.native_direct_cache[text] = (time.time(), direct_urls)
            elif text in app.native_direct_cache:
                cached_at, cached_urls = app.native_direct_cache[text]
                if time.time() - cached_at < 15 * 60:
                    direct_urls = cached_urls
                    app.storage.log("warning", f"native resolver using cached direct URL(s) for {text[:120]}")
            for direct_url in direct_urls:
                if direct_url.startswith("https://"):
                    relay_ok, relay_reason = self.preflight_relayable_url(direct_url)
                    if not relay_ok:
                        reasons.append(relay_reason)
                        continue
                    native_url = self.relay_url(direct_url)
                else:
                    native_url = ps5_native_http_url(direct_url)
                if native_url.startswith("http://"):
                    urls.append(native_url)
                else:
                    reasons.append("cached direct URL is not PS5-native HTTP compatible")
            for result in results:
                if result.type == PluginResultType.DIRECT_FILE and result.resolved_url:
                    continue
                if result.type != PluginResultType.DIRECT_FILE or not result.resolved_url:
                    if result.type == PluginResultType.MANUAL_ACTION_REQUIRED:
                        reason = result.message or "manual action required"
                        if result.plugin:
                            reason = f"{result.plugin}: {reason}"
                    else:
                        reason = f"{result.type}"
                        if result.plugin:
                            reason += f" from {result.plugin}"
                        if result.message:
                            reason += f": {result.message}"
                    reasons.append(reason)
                    continue
            if not urls:
                detail = " | ".join(reasons[:5]) or "no direct URL found"
                app.storage.log("warning", f"native resolver found no direct URLs for {text[:120]}: {detail[:600]}")
                self.send_text(f"manual-action-required: {detail[:1200]}\n", HTTPStatus.OK)
                return
            app.storage.log("info", f"native resolver returned {len(urls)} URL(s)")
            self.send_text("\n".join(urls) + "\n")

        def preflight_relayable_url(self, direct_url: str) -> tuple[bool, str]:
            if not self.is_allowed_relay_url(direct_url):
                return False, "relay URL must be public http/https"
            headers = {"User-Agent": app.settings.user_agent}
            req = Request(direct_url, headers=headers, method="HEAD")
            try:
                with urlopen(req, timeout=app.settings.request_timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" in content_type.lower():
                        return False, "direct URL returned HTML instead of a file"
                    return True, ""
            except HTTPError as exc:
                if exc.code not in {403, 405}:
                    return False, f"direct URL preflight status={exc.code}"
            except Exception as exc:
                return False, f"direct URL preflight failed: {exc}"

            range_headers = dict(headers)
            range_headers["Range"] = "bytes=0-0"
            try:
                req = Request(direct_url, headers=range_headers, method="GET")
                with urlopen(req, timeout=app.settings.request_timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" in content_type.lower():
                        body = response.read(4096).decode("utf-8", errors="replace")
                        if "Just a moment" in body or "cf-mitigated" in body.lower():
                            return False, "direct URL returned a Cloudflare browser challenge"
                        return False, "direct URL returned HTML instead of a file"
                    if response.status in {200, 206}:
                        return True, ""
                    return False, f"direct URL range preflight status={response.status}"
            except HTTPError as exc:
                body = exc.read(4096).decode("utf-8", errors="replace")
                if "Just a moment" in body or "cf-mitigated" in body.lower():
                    return False, "direct URL returned a Cloudflare browser challenge"
                return False, f"direct URL range preflight status={exc.code}"
            except Exception as exc:
                return False, f"direct URL range preflight failed: {exc}"

        def relay_url(self, direct_url: str) -> str:
            host = self.headers.get("Host") or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
            return f"http://{host}/api/relay?url={quote(direct_url, safe='')}"

        def handle_relay(self, query: str, head_only: bool) -> None:
            params = parse_qs(query)
            direct_url = params.get("url", [""])[0]
            if not self.is_allowed_relay_url(direct_url):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "relay URL must be public http/https")
                return
            headers = {"User-Agent": app.settings.user_agent}
            incoming_range = self.headers.get("Range")
            if incoming_range:
                headers["Range"] = incoming_range
            req = Request(direct_url, headers=headers, method="HEAD" if head_only else "GET")
            try:
                upstream = urlopen(req, timeout=app.settings.request_timeout)
            except HTTPError as exc:
                if head_only and exc.code in {403, 405}:
                    upstream = self.relay_head_via_range(direct_url, headers)
                    if upstream is None:
                        upstream = exc
                else:
                    upstream = exc
            except Exception as exc:
                app.storage.log("warning", f"relay request failed for {direct_url[:160]}: {exc}")
                self.send_error_json(HTTPStatus.BAD_GATEWAY, f"relay request failed: {exc}")
                return
            with upstream:
                status = getattr(upstream, "status", upstream.getcode())
                self.send_response(HTTPStatus.OK if head_only and status == 206 else status)
                head_total = self.content_range_total(upstream.headers.get("Content-Range", ""))
                for header in (
                    "Content-Length",
                    "Content-Type",
                    "Content-Disposition",
                    "Accept-Ranges",
                    "Content-Range",
                    "ETag",
                    "Last-Modified",
                ):
                    value = upstream.headers.get(header)
                    if head_only and header == "Content-Length" and head_total:
                        value = str(head_total)
                    if head_only and header == "Content-Range":
                        continue
                    if value:
                        self.send_header(header, value)
                if head_only and head_total and not upstream.headers.get("Accept-Ranges"):
                    self.send_header("Accept-Ranges", "bytes")
                self.send_header("X-PS5-Downloader-Relay", "1")
                self.end_headers()
                if not head_only:
                    try:
                        shutil.copyfileobj(upstream, self.wfile, length=256 * 1024)
                    except (BrokenPipeError, ConnectionResetError, socket.timeout) as exc:
                        app.storage.log("warning", f"relay client disconnected for {direct_url[:160]}: {exc}")
                        return
            app.storage.log("info", f"relay completed status={status} url={direct_url[:160]}")

        def relay_head_via_range(self, direct_url: str, headers: dict[str, str]):
            range_headers = dict(headers)
            range_headers["Range"] = "bytes=0-0"
            req = Request(direct_url, headers=range_headers, method="GET")
            try:
                return urlopen(req, timeout=app.settings.request_timeout)
            except Exception as exc:
                app.storage.log("warning", f"relay HEAD fallback failed for {direct_url[:160]}: {exc}")
                return None

        @staticmethod
        def content_range_total(content_range: str) -> int | None:
            match = re.search(r"/(\d+)\s*$", content_range or "")
            if not match:
                return None
            return int(match.group(1))

        @staticmethod
        def is_allowed_relay_url(direct_url: str) -> bool:
            parts = urlsplit(direct_url)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                return False
            host = parts.hostname.lower()
            if host in {"localhost", "localhost.localdomain"}:
                return False
            try:
                ip = ip_address(host)
            except ValueError:
                return True
            return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)

        def handle_action(self, item_id: str, action: str) -> None:
            try:
                item = getattr(app.queue, action)(item_id)
                self.send_json(item.to_dict())
            except KeyError:
                self.send_error_json(HTTPStatus.NOT_FOUND, "download not found")
            except Exception as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

        def read_json(self) -> dict:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
            return json.loads(raw or "{}")

        def serve_static(self, path: str, root: Path) -> None:
            if path in {"", "/"}:
                path = "/index.html"
            target = (root / path.lstrip("/")).resolve()
            if root.resolve() not in target.parents and target != root.resolve():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_error_json(self, status: HTTPStatus, message: str) -> None:
            self.send_json({"error": message}, status)

        def log_message(self, fmt: str, *args) -> None:
            app.storage.log("info", fmt % args)

    return Handler


def serve(app: App, host: str = "0.0.0.0", port: int = 2634) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    app.storage.log("info", f"server listening on http://{host}:{port}")
    httpd.serve_forever()
