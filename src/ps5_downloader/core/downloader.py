from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .models import DownloadItem, DownloadState, PluginResult, PluginResultType, Settings
from .storage import Storage
from .utils import ensure_directory, ensure_safe_child, filename_from_url


def range_header_for_existing_size(size: int) -> dict[str, str]:
    return {"Range": f"bytes={size}-"} if size > 0 else {}


def has_disk_space(directory: str | Path, needed_bytes: int | None) -> bool:
    if not needed_bytes:
        return True
    usage = shutil.disk_usage(directory)
    return usage.free > needed_bytes


class DownloadEngine:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage

    def download(self, item: DownloadItem, stop_event: threading.Event, pause_event: threading.Event) -> DownloadItem:
        if not item.resolved_url:
            raise ValueError("download item has no resolved URL")
        download_dir = ensure_directory(self.settings.download_dir)
        temp_dir = ensure_directory(self.settings.temp_dir)
        filename = item.filename or filename_from_url(item.resolved_url)
        final_path = self._target_path(download_dir, filename)
        part_path = temp_dir / f"{final_path.name}.part"
        existing = part_path.stat().st_size if part_path.exists() else 0
        headers = {"User-Agent": self.settings.user_agent, **range_header_for_existing_size(existing)}
        req = Request(item.resolved_url, headers=headers)

        try:
            response = urlopen(req, timeout=self.settings.request_timeout)
        except HTTPError as exc:
            if exc.code == 416 and part_path.exists():
                part_path.replace(final_path)
                item.state = DownloadState.COMPLETED
                item.downloaded_bytes = final_path.stat().st_size
                self.storage.update_download(item)
                return item
            raise

        with response:
            status = getattr(response, "status", 200)
            if existing and status != 206:
                existing = 0
                part_path.unlink(missing_ok=True)
            length_header = response.headers.get("Content-Length")
            incoming = int(length_header) if length_header and length_header.isdigit() else None
            total = existing + incoming if incoming is not None else item.size
            item.size = total
            if not has_disk_space(download_dir, total):
                raise OSError("insufficient disk space")
            mode = "ab" if existing else "wb"
            item.downloaded_bytes = existing
            item.state = DownloadState.DOWNLOADING
            self.storage.update_download(item)
            started = time.monotonic()
            last_update = started
            with part_path.open(mode + "") as fh:
                while True:
                    if stop_event.is_set():
                        item.state = DownloadState.CANCELLED
                        self.storage.update_download(item)
                        return item
                    if pause_event.is_set():
                        item.state = DownloadState.PAUSED
                        self.storage.update_download(item)
                        return item
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    item.downloaded_bytes += len(chunk)
                    now = time.monotonic()
                    elapsed = max(0.001, now - started)
                    item.speed_bps = item.downloaded_bytes / elapsed
                    remaining = (item.size - item.downloaded_bytes) if item.size else None
                    item.eta_seconds = remaining / item.speed_bps if remaining and item.speed_bps else None
                    if now - last_update > 0.5:
                        self.storage.update_download(item)
                        last_update = now

        if item.size is not None and item.downloaded_bytes < item.size:
            raise IOError("download ended before Content-Length was satisfied")
        part_path.replace(final_path)
        item.filename = final_path.name
        item.state = DownloadState.COMPLETED
        item.error = None
        self.storage.update_download(item)
        return item

    def _target_path(self, download_dir: Path, filename: str) -> Path:
        candidate = ensure_safe_child(download_dir, filename)
        if self.settings.conflict_behavior == "overwrite":
            return candidate
        if self.settings.conflict_behavior == "skip" and candidate.exists():
            raise FileExistsError(f"target already exists: {candidate.name}")
        if self.settings.conflict_behavior == "auto-rename":
            stem = candidate.stem
            suffix = candidate.suffix
            counter = 1
            while candidate.exists():
                candidate = ensure_safe_child(download_dir, f"{stem} ({counter}){suffix}")
                counter += 1
        return candidate


class QueueManager:
    def __init__(self, storage: Storage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings
        self.engine = DownloadEngine(settings, storage)
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._pauses: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def add_result(self, result: PluginResult) -> list[DownloadItem]:
        if result.type == PluginResultType.PACKAGE:
            items: list[DownloadItem] = []
            for child in result.children:
                if child.resolved_url:
                    items.extend(self.add_result(child))
            return items
        item = DownloadItem(
            id=str(uuid.uuid4()),
            original_url=result.original_url,
            resolved_url=result.resolved_url,
            host=result.host,
            filename=result.filename,
            size=result.size,
            checksum=result.checksum,
            plugin=result.plugin,
            state=DownloadState.WAITING
            if result.type in {PluginResultType.DIRECT_FILE, PluginResultType.REDIRECT}
            else DownloadState.MANUAL_ACTION_REQUIRED,
            error=result.message,
        )
        self.storage.add_download(item)
        return [item]

    def start(self, item_id: str) -> DownloadItem:
        item = self._require(item_id)
        if item.state == DownloadState.DOWNLOADING:
            return item
        item.state = DownloadState.WAITING
        item.error = None
        self.storage.update_download(item)
        with self._lock:
            running = sum(1 for i in self.storage.list_downloads() if i.state == DownloadState.DOWNLOADING)
            if running >= self.settings.max_concurrent_downloads:
                return item
            stop = threading.Event()
            pause = threading.Event()
            self._stops[item_id] = stop
            self._pauses[item_id] = pause
            thread = threading.Thread(target=self._run, args=(item_id, stop, pause), daemon=True)
            self._threads[item_id] = thread
            thread.start()
        return item

    def pause(self, item_id: str) -> DownloadItem:
        item = self._require(item_id)
        if item_id in self._pauses:
            self._pauses[item_id].set()
        else:
            item.state = DownloadState.PAUSED
            self.storage.update_download(item)
        return self._require(item_id)

    def resume(self, item_id: str) -> DownloadItem:
        return self.start(item_id)

    def cancel(self, item_id: str) -> DownloadItem:
        item = self._require(item_id)
        if item.state == DownloadState.COMPLETED:
            item.error = "already completed; use delete to remove the file"
            self.storage.update_download(item)
            return item
        if item_id in self._stops:
            self._stops[item_id].set()
        item.state = DownloadState.CANCELLED
        self.storage.update_download(item)
        return item

    def delete(self, item_id: str) -> bool:
        item = self.storage.get_download(item_id)
        if not item:
            return False
        if item_id in self._stops:
            self._stops[item_id].set()
        self._delete_files_for_item(item)
        return self.storage.delete_download(item_id)

    def _delete_files_for_item(self, item: DownloadItem) -> None:
        if not item.filename:
            return
        download_dir = ensure_directory(self.settings.download_dir)
        temp_dir = ensure_directory(self.settings.temp_dir)
        final_path = ensure_safe_child(download_dir, item.filename)
        part_path = ensure_safe_child(temp_dir, f"{final_path.name}.part")
        final_path.unlink(missing_ok=True)
        part_path.unlink(missing_ok=True)

    def _run(self, item_id: str, stop: threading.Event, pause: threading.Event) -> None:
        item = self._require(item_id)
        retries = 3
        for attempt in range(retries):
            try:
                self.engine.download(item, stop, pause)
                return
            except Exception as exc:
                item = self._require(item_id)
                if item.state in {DownloadState.PAUSED, DownloadState.CANCELLED}:
                    return
                item.error = str(exc)
                item.state = DownloadState.FAILED
                self.storage.update_download(item)
                self.storage.log("error", f"download failed: {exc}", item_id)
                time.sleep(min(8, 2**attempt))
        self._cleanup(item_id)

    def _cleanup(self, item_id: str) -> None:
        self._threads.pop(item_id, None)
        self._stops.pop(item_id, None)
        self._pauses.pop(item_id, None)

    def _require(self, item_id: str) -> DownloadItem:
        item = self.storage.get_download(item_id)
        if not item:
            raise KeyError(item_id)
        return item
