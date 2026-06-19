from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResultType
from ps5_downloader.core.resolver import LinkResolver
from ps5_downloader.core.settings import SettingsStore, default_home
from ps5_downloader.core.storage import Storage
from ps5_downloader.core.utils import ps5_native_http_url
from ps5_downloader.server.api import App, serve


def make_app() -> App:
    home = default_home()
    settings_store = SettingsStore(home)
    storage = Storage(home / "state.sqlite3")
    return App(storage, settings_store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ps5-downloader")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add")
    p_add.add_argument("url")
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("url")
    p_grab = sub.add_parser("grab")
    p_grab.add_argument("text")
    p_send = sub.add_parser("send-ps5")
    p_send.add_argument("text")
    p_send.add_argument("--ps5", default="192.168.1.204")
    p_send.add_argument("--port", type=int, default=2634)
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=2634)
    p_test = sub.add_parser("test-plugin")
    p_test.add_argument("url")
    sub.add_parser("list")
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        serve(make_app(), args.host, args.port)
        return 0
    if args.cmd in {"resolve", "test-plugin"}:
        print(json.dumps(LinkResolver().resolve_url(args.url).to_dict(), indent=2))
        return 0
    if args.cmd == "grab":
        print(json.dumps([result.to_dict() for result in LinkResolver().resolve_text(args.text)], indent=2))
        return 0
    if args.cmd == "send-ps5":
        results = LinkResolver().resolve_text(args.text)
        urls = [
            ps5_native_http_url(result.resolved_url)
            for result in results
            if result.type == PluginResultType.DIRECT_FILE and result.resolved_url
        ]
        if not urls:
            print(json.dumps({"error": "no direct downloadable URLs resolved", "results": [r.to_dict() for r in results]}, indent=2))
            return 2
        body = "\n".join(urls).encode()
        req = Request(f"http://{args.ps5}:{args.port}/api/links", data=body, method="POST")
        with urlopen(req, timeout=20) as response:
            print(response.read().decode("utf-8", "replace"))
        return 0
    app = make_app()
    if args.cmd == "add":
        results = app.resolver.resolve_text(args.url)
        items = []
        for result in results:
            items.extend(app.queue.add_result(result))
        print(json.dumps([item.to_dict() for item in items], indent=2))
        return 0
    if args.cmd == "list":
        print(json.dumps([item.to_dict() for item in app.storage.list_downloads()], indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
