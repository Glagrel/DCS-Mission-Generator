"""SQLite document store for campaign state."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Ordered migrations. Never edit an applied entry: append a new one. PRAGMA user_version
# holds the number of migrations applied.
MIGRATIONS: List[str] = [
    # 1: base schema
    """
    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS entities (
      campaign_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
      PRIMARY KEY (campaign_id, kind, id));
    CREATE TABLE IF NOT EXISTS history (
      rowid INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, turn INTEGER NOT NULL,
      kind TEXT NOT NULL, data TEXT NOT NULL, ts REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS history_idx ON history (campaign_id, kind, turn);
    """,
    # 2: runtime event records (deduplicated by event id) and watcher cursors
    """
    CREATE TABLE IF NOT EXISTS events (
      campaign_id TEXT NOT NULL, turn INTEGER NOT NULL, event_id TEXT NOT NULL, t REAL NOT NULL,
      ev TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (campaign_id, turn, event_id));
    CREATE TABLE IF NOT EXISTS cursors (
      name TEXT PRIMARY KEY, file_id TEXT NOT NULL, offset INTEGER NOT NULL, updated REAL NOT NULL);
    """,
]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the schema version afterwards."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i in range(version, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[i])
        conn.execute(f"PRAGMA user_version = {i + 1}")
        conn.commit()
    return len(MIGRATIONS)


class Store:
    """Thin wrapper; one connection, explicit commits via `with store.tx():`."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.schema_version = migrate(self.conn)

    def close(self) -> None:
        self.conn.close()

    def tx(self) -> sqlite3.Connection:
        return self.conn  # usable as context manager: commits or rolls back

    # -- campaigns ---------------------------------------------------------
    def create_campaign(self, cid: str, name: str) -> None:
        now = time.time()
        with self.conn:
            self.conn.execute("INSERT INTO campaigns VALUES (?,?,?,?)", (cid, name, now, now))

    def list_campaigns(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT id, name, created, updated FROM campaigns ORDER BY updated DESC")
        return [dict(zip(("id", "name", "created", "updated"), r)) for r in rows]

    def delete_campaign(self, cid: str) -> None:
        with self.conn:
            for table in ("entities", "history", "events"):
                self.conn.execute(f"DELETE FROM {table} WHERE campaign_id=?", (cid,))
            self.conn.execute("DELETE FROM campaigns WHERE id=?", (cid,))

    def touch(self, cid: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE campaigns SET updated=? WHERE id=?", (time.time(), cid))

    # -- entities ----------------------------------------------------------
    def put(self, cid: str, kind: str, obj: BaseModel, commit: bool = True) -> None:
        self.conn.execute("INSERT OR REPLACE INTO entities VALUES (?,?,?,?)",
                          (cid, kind, getattr(obj, "id"), obj.model_dump_json()))
        if commit:
            self.conn.commit()

    def put_many(self, cid: str, kind: str, objs: Iterable[BaseModel]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO entities VALUES (?,?,?,?)",
                [(cid, kind, getattr(o, "id"), o.model_dump_json()) for o in objs])

    def get(self, cid: str, kind: str, eid: str, model: Type[T]) -> Optional[T]:
        row = self.conn.execute("SELECT data FROM entities WHERE campaign_id=? AND kind=? AND id=?",
                                (cid, kind, eid)).fetchone()
        return model.model_validate_json(row[0]) if row else None

    def all(self, cid: str, kind: str, model: Type[T]) -> List[T]:
        rows = self.conn.execute("SELECT data FROM entities WHERE campaign_id=? AND kind=? ORDER BY id",
                                 (cid, kind))
        return [model.model_validate_json(r[0]) for r in rows]

    def delete(self, cid: str, kind: str, eid: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM entities WHERE campaign_id=? AND kind=? AND id=?", (cid, kind, eid))

    # -- history -----------------------------------------------------------
    def log(self, cid: str, turn: int, kind: str, data: Dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO history (campaign_id, turn, kind, data, ts) VALUES (?,?,?,?,?)",
                              (cid, turn, kind, json.dumps(data), time.time()))

    def history(self, cid: str, kind: Optional[str] = None, turn: Optional[int] = None,
                limit: int = 500) -> List[Dict[str, Any]]:
        q, args = "SELECT turn, kind, data FROM history WHERE campaign_id=?", [cid]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if turn is not None:
            q += " AND turn=?"
            args.append(turn)
        q += " ORDER BY rowid DESC LIMIT ?"
        args.append(limit)
        return [{"turn": t, "kind": k, **json.loads(d)} for t, k, d in self.conn.execute(q, args)]

    # -- runtime events ------------------------------------------------------
    def add_events(self, cid: str, turn: int, events: Iterable[Dict[str, Any]]) -> int:
        """Insert events, ignoring ids already stored. Returns the number of new rows."""
        before = self.conn.total_changes
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                [(cid, turn, str(e["id"]), float(e.get("t", 0)), str(e.get("ev", "")), json.dumps(e))
                 for e in events])
        return self.conn.total_changes - before

    def events(self, cid: str, turn: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT data FROM events WHERE campaign_id=? AND turn=? ORDER BY t, rowid", (cid, turn))
        return [json.loads(r[0]) for r in rows]

    def clear_events(self, cid: str, turn: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM events WHERE campaign_id=? AND turn=?", (cid, turn))

    # -- watcher cursors -----------------------------------------------------
    def get_cursor(self, name: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT file_id, offset FROM cursors WHERE name=?", (name,)).fetchone()
        return {"file_id": row[0], "offset": row[1]} if row else None

    def set_cursor(self, name: str, file_id: str, offset: int) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO cursors VALUES (?,?,?,?)",
                              (name, file_id, offset, time.time()))
