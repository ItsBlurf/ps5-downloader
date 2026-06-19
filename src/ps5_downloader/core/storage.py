from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import time

from .models import DownloadItem, DownloadState


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists downloads (
              id text primary key,
              data text not null,
              state text not null,
              created_at real not null,
              updated_at real not null
            );
            create table if not exists logs (
              id integer primary key autoincrement,
              ts real not null,
              level text not null,
              message text not null,
              download_id text
            );
            """
        )
        self.conn.commit()

    def add_download(self, item: DownloadItem) -> DownloadItem:
        self.conn.execute(
            "insert or replace into downloads(id, data, state, created_at, updated_at) values (?, ?, ?, ?, ?)",
            (item.id, json.dumps(item.to_dict()), str(item.state), item.created_at, item.updated_at),
        )
        self.conn.commit()
        return item

    def update_download(self, item: DownloadItem) -> DownloadItem:
        item.updated_at = time()
        self.add_download(item)
        return item

    def get_download(self, item_id: str) -> DownloadItem | None:
        row = self.conn.execute("select data from downloads where id = ?", (item_id,)).fetchone()
        if not row:
            return None
        return self._item_from_data(json.loads(row["data"]))

    def list_downloads(self) -> list[DownloadItem]:
        rows = self.conn.execute("select data from downloads order by created_at asc").fetchall()
        return [self._item_from_data(json.loads(row["data"])) for row in rows]

    def delete_download(self, item_id: str) -> bool:
        cur = self.conn.execute("delete from downloads where id = ?", (item_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def log(self, level: str, message: str, download_id: str | None = None) -> None:
        self.conn.execute(
            "insert into logs(ts, level, message, download_id) values (?, ?, ?, ?)",
            (time(), level, message, download_id),
        )
        self.conn.commit()

    def logs(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            "select ts, level, message, download_id from logs order by id desc limit ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _item_from_data(data: dict) -> DownloadItem:
        data.pop("percent", None)
        data["state"] = DownloadState(data["state"])
        return DownloadItem(**data)
