from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .client import ApiError, Ps5Api, api_base, request_text
from .payload import send_payload_file


HELPER_DEFAULT_HOST = "127.0.0.1"
HELPER_BIND_HOST = "0.0.0.0"
HELPER_PORT = 2635


def fmt_bytes(value: int | float | None) -> str:
    if not value:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    index = 0
    while amount >= 1024 and index < len(units) - 1:
        amount /= 1024
        index += 1
    return f"{amount:.1f} {units[index]}" if index else f"{int(amount)} B"


class FetcherProcess:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_owned_running():
            return
        if getattr(sys, "frozen", False):
            from ps5_downloader.cli.main import make_app
            from ps5_downloader.server.api import serve

            self.thread = threading.Thread(
                target=lambda: serve(make_app(), HELPER_BIND_HOST, HELPER_PORT),
                daemon=True,
            )
            self.thread.start()
            return
        cmd = [
            sys.executable,
            "-m",
            "ps5_downloader.cli.main",
            "serve",
            "--host",
            HELPER_BIND_HOST,
            "--port",
            str(HELPER_PORT),
        ]
        env = os.environ.copy()
        src_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        env["PYTHONPATH"] = os.pathsep.join([src_root, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)

    def stop(self) -> None:
        if self.thread is not None:
            try:
                request_text(api_base(HELPER_DEFAULT_HOST, HELPER_PORT), "/api/shutdown", method="POST", timeout=2.0)
            except ApiError:
                pass
            self.thread.join(timeout=5)
            self.thread = None
        if self.is_owned_running() and self.process:
            if os.name == "nt":
                self.process.terminate()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def is_owned_running(self) -> bool:
        thread_running = self.thread is not None and self.thread.is_alive()
        process_running = self.process is not None and self.process.poll() is None
        return thread_running or process_running


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PS5 Downloader")
        self.geometry("1080x720")
        self.minsize(860, 560)
        self.fetcher = FetcherProcess()
        self.ps5_host = tk.StringVar(value="192.168.1.204")
        self.ps5_port = tk.IntVar(value=2634)
        self.helper_status = tk.StringVar(value="Fetcher stopped")
        self.ps5_status = tk.StringVar(value="PS5 not checked")
        self.download_dir = tk.StringVar(value="/data/test")
        self.resolver_url = tk.StringVar(value="http://192.168.1.157:2635/api/resolve-native")
        self.loader_port = tk.IntVar(value=9021)
        self.elf_path = tk.StringVar(value=str(Path("dist/ps5-downloader.elf").resolve()))
        self.auto_refresh = tk.BooleanVar(value=True)
        self.rows_by_iid: dict[str, str] = {}
        self._refresh_after_id: str | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(400, self.refresh_all)

    @property
    def api(self) -> Ps5Api:
        return Ps5Api(self.ps5_host.get().strip(), int(self.ps5_port.get()))

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(4, weight=1)

        ttk.Label(top, text="PS5").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.ps5_host, width=18).grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(top, text="Port").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.ps5_port, width=7).grid(row=0, column=3, sticky="w", padx=(6, 12))
        ttk.Button(top, text="Connect", command=self.refresh_all).grid(row=0, column=4, sticky="w")
        ttk.Button(top, text="Start Fetcher", command=self.start_fetcher).grid(row=0, column=5, padx=4)
        ttk.Button(top, text="Stop Fetcher", command=self.stop_fetcher).grid(row=0, column=6, padx=4)
        ttk.Checkbutton(top, text="Auto refresh", variable=self.auto_refresh).grid(row=0, column=7, padx=(12, 0))

        status = ttk.Frame(self, padding=(10, 0, 10, 8))
        status.grid(row=1, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.ps5_status).pack(side="left")
        ttk.Label(status, text="   ").pack(side="left")
        ttk.Label(status, textvariable=self.helper_status).pack(side="left")

        panes = ttk.PanedWindow(self, orient=tk.VERTICAL)
        panes.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        upper = ttk.Frame(panes)
        upper.columnconfigure(0, weight=1)
        upper.rowconfigure(2, weight=1)
        panes.add(upper, weight=3)

        link_frame = ttk.LabelFrame(upper, text="Add links", padding=8)
        link_frame.grid(row=0, column=0, sticky="ew")
        link_frame.columnconfigure(0, weight=1)
        self.links_text = tk.Text(link_frame, height=4, wrap="word")
        self.links_text.grid(row=0, column=0, columnspan=7, sticky="ew")
        ttk.Button(link_frame, text="Send to PS5", command=self.add_links).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(link_frame, text="Set /data/test", command=lambda: self.set_download_dir("/data/test")).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Button(link_frame, text="Save Settings", command=self.save_settings).grid(row=1, column=2, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(link_frame, text="Download path").grid(row=1, column=3, sticky="e", padx=(18, 4), pady=(8, 0))
        ttk.Entry(link_frame, textvariable=self.download_dir, width=26).grid(row=1, column=4, sticky="ew", pady=(8, 0))
        ttk.Label(link_frame, text="Resolver").grid(row=1, column=5, sticky="e", padx=(12, 4), pady=(8, 0))
        ttk.Entry(link_frame, textvariable=self.resolver_url, width=40).grid(row=1, column=6, sticky="ew", pady=(8, 0))
        link_frame.columnconfigure(6, weight=1)

        payload_frame = ttk.LabelFrame(upper, text="Payload", padding=8)
        payload_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        payload_frame.columnconfigure(1, weight=1)
        ttk.Label(payload_frame, text="ELF").grid(row=0, column=0, sticky="w")
        ttk.Entry(payload_frame, textvariable=self.elf_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(payload_frame, text="Browse", command=self.browse_elf).grid(row=0, column=2, padx=4)
        ttk.Label(payload_frame, text="Loader port").grid(row=0, column=3, padx=(16, 4))
        ttk.Entry(payload_frame, textvariable=self.loader_port, width=8).grid(row=0, column=4)
        ttk.Button(payload_frame, text="Send ELF to PS5", command=self.send_elf).grid(row=0, column=5, padx=(12, 0))

        queue_frame = ttk.LabelFrame(upper, text="PS5 queue", padding=8)
        queue_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        queue_frame.rowconfigure(0, weight=1)
        queue_frame.columnconfigure(0, weight=1)
        columns = ("id", "state", "name", "progress", "speed", "status", "path")
        self.tree = ttk.Treeview(queue_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": "ID",
            "state": "State",
            "name": "Name",
            "progress": "Progress",
            "speed": "Speed",
            "status": "HTTP",
            "path": "Path",
        }
        widths = {"id": 60, "state": 150, "name": 260, "progress": 170, "speed": 100, "status": 70, "path": 300}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(queue_frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for label, action in (
            ("Start/Resume", "resume"),
            ("Pause", "pause"),
            ("Cancel", "cancel"),
            ("Delete File + Item", "delete"),
        ):
            ttk.Button(actions, text=label, command=lambda a=action: self.item_action(a)).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Refresh", command=self.refresh_all).pack(side="left", padx=(12, 0))

        lower = ttk.Frame(panes)
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(0, weight=1)
        panes.add(lower, weight=1)
        logs = ttk.LabelFrame(lower, text="Logs", padding=8)
        logs.grid(row=0, column=0, sticky="nsew")
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log_text = tk.Text(logs, height=8, wrap="none")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(logs, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def start_fetcher(self) -> None:
        try:
            self.fetcher.start()
            time.sleep(0.4)
            self.check_helper()
        except Exception as exc:
            messagebox.showerror("Fetcher", str(exc))

    def browse_elf(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PS5 downloader ELF",
            filetypes=(("ELF payload", "*.elf"), ("All files", "*.*")),
            initialdir=str(Path(self.elf_path.get()).parent if self.elf_path.get() else Path.cwd()),
        )
        if path:
            self.elf_path.set(path)

    def send_elf(self) -> None:
        path = self.elf_path.get().strip()
        if not path:
            messagebox.showerror("Send ELF", "Choose an ELF file first.")
            return
        if not Path(path).is_file():
            messagebox.showerror("Send ELF", f"ELF not found: {path}")
            return
        if not messagebox.askyesno("Send ELF", "Send this ELF to the PS5 payload loader now?"):
            return
        self.run_bg(
            lambda: send_payload_file(
                path,
                self.ps5_host.get().strip(),
                int(self.loader_port.get()),
                int(self.ps5_port.get()),
            ),
            self.after_send_elf,
        )

    def after_send_elf(self, result) -> None:
        if isinstance(result, Exception):
            messagebox.showerror("Send ELF", str(result))
            return
        lines = [
            f"payload sent: {result.bytes_sent} bytes",
            f"sha256: {result.sha256}",
            *result.notes,
        ]
        self.append_log("\n".join(lines))
        self.refresh_all()

    def stop_fetcher(self) -> None:
        try:
            try:
                request_text(api_base(HELPER_DEFAULT_HOST, HELPER_PORT), "/api/shutdown", method="POST", timeout=2.0)
            except ApiError:
                pass
            self.fetcher.stop()
            self.check_helper()
        except Exception as exc:
            messagebox.showerror("Fetcher", str(exc))

    def check_helper(self) -> None:
        try:
            request_text(api_base(HELPER_DEFAULT_HOST, HELPER_PORT), "/api/status", timeout=2.0)
            owner = "owned" if self.fetcher.is_owned_running() else "external"
            self.helper_status.set(f"Fetcher running on {HELPER_PORT} ({owner})")
        except Exception:
            self.helper_status.set("Fetcher stopped")

    def add_links(self) -> None:
        text = self.links_text.get("1.0", "end").strip()
        if not text:
            return
        self.run_bg(lambda: self.api.add_links(text), self.after_add_links)

    def after_add_links(self, result: str | Exception) -> None:
        if isinstance(result, Exception):
            messagebox.showerror("Add links", str(result))
            return
        self.links_text.delete("1.0", "end")
        self.append_log(result.strip())
        self.refresh_all()

    def item_action(self, action: str) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item_id = str(self.tree.item(selection[0], "values")[0])
        if action == "delete" and not messagebox.askyesno("Delete", "Delete this queue item and its file from the PS5?"):
            return
        self.run_bg(lambda: self.api.action(item_id, action), lambda result: self.after_action(action, result))

    def after_action(self, action: str, result: str | Exception) -> None:
        if isinstance(result, Exception):
            messagebox.showerror(action, str(result))
            return
        self.append_log(str(result).strip())
        self.refresh_all()

    def set_download_dir(self, value: str) -> None:
        self.download_dir.set(value)
        self.save_settings()

    def save_settings(self) -> None:
        values = {
            "download_dir": self.download_dir.get().strip(),
            "resolver_url": self.resolver_url.get().strip(),
        }
        self.run_bg(lambda: self.api.update_settings(values), self.after_save_settings)

    def after_save_settings(self, result: dict | Exception) -> None:
        if isinstance(result, Exception):
            messagebox.showerror("Settings", str(result))
            return
        self.append_log(f"settings saved: {result}")
        self.refresh_all()

    def refresh_all(self) -> None:
        if self._refresh_after_id is not None:
            self.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        self.check_helper()
        self.run_bg(self._load_snapshot, self._apply_snapshot)
        if self.auto_refresh.get():
            self._refresh_after_id = self.after(1500, self.refresh_all)

    def _load_snapshot(self) -> dict:
        api = self.api
        return {
            "status": api.status(),
            "settings": api.settings(),
            "downloads": api.downloads(),
            "logs": api.logs(),
        }

    def _apply_snapshot(self, result: dict | Exception) -> None:
        if isinstance(result, Exception):
            self.ps5_status.set(f"PS5 offline: {result}")
            return
        status = result["status"]
        self.ps5_status.set(
            f"PS5 online port {status.get('port', self.ps5_port.get())} | "
            f"path {status.get('download_dir', '')} | worker {status.get('worker_started', '')}"
        )
        settings = result.get("settings") or {}
        self.download_dir.set(settings.get("download_dir", self.download_dir.get()))
        self.resolver_url.set(settings.get("resolver_url", self.resolver_url.get()))
        self.update_downloads(result["downloads"])
        self.set_logs(result.get("logs", ""))

    def update_downloads(self, rows) -> None:
        seen = set()
        for row in rows:
            seen.add(row.id)
            total = row.total_bytes
            progress = f"{fmt_bytes(row.bytes_done)}"
            if total:
                progress += f" / {fmt_bytes(total)} ({row.percent:.1f}%)"
            else:
                progress += " / unknown"
            values = (
                row.id,
                row.state,
                row.name,
                progress,
                f"{fmt_bytes(row.speed_bps)}/s" if row.speed_bps else "",
                row.http_status,
                row.error or row.path,
            )
            if row.id in self.rows_by_iid:
                self.tree.item(self.rows_by_iid[row.id], values=values)
            else:
                iid = self.tree.insert("", "end", values=values)
                self.rows_by_iid[row.id] = iid
        for row_id, iid in list(self.rows_by_iid.items()):
            if row_id not in seen:
                self.tree.delete(iid)
                del self.rows_by_iid[row_id]

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def set_logs(self, text: str) -> None:
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def run_bg(self, func, callback) -> None:
        def worker() -> None:
            try:
                result = func()
            except Exception as exc:
                result = exc
            self.after(0, lambda: callback(result))

        threading.Thread(target=worker, daemon=True).start()

    def on_close(self) -> None:
        if self._refresh_after_id is not None:
            self.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        self.fetcher.stop()
        self.destroy()


def main() -> int:
    app = DesktopApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
