"""Tail of the in-mission event file (events.jsonl) with a durable cursor.

Handles: partial last line (not consumed until its newline arrives), file truncation or
replacement when a mission restarts, malformed lines, duplicate events (by event id), and
application restarts (cursor + event ids persisted in SQLite).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..db import Store

log = logging.getLogger("sortie.watcher")
LOG_LINE = re.compile(r"SORTIE_EVT (\{.*\})\s*$")


class EventTail:
    def __init__(self, path: Path, store: Optional[Store] = None, cursor_name: str = "events") -> None:
        self.path, self.store, self.cursor_name = Path(path), store, cursor_name
        self.offset = 0
        self.file_id = ""
        self.seen: set[str] = set()
        self.malformed = 0
        self.resets = 0
        cur = store.get_cursor(cursor_name) if store else None
        if cur:
            self.offset, self.file_id = int(cur["offset"]), cur["file_id"]

    def _identity(self) -> str:
        """The first line (mission_start, with a per-run id) identifies the file's content."""
        try:
            with open(self.path, "rb") as f:
                head = f.readline(2048)
        except OSError:
            return ""
        return hashlib.sha1(head).hexdigest()[:16] if head.endswith(b"\n") else ""

    def poll(self) -> List[Dict[str, Any]]:
        """Return events appended since the last poll (never the same event twice)."""
        if not self.path.is_file():
            return []
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        ident = self._identity()
        if not ident:
            return []                                   # first line not complete yet
        if ident != self.file_id or size < self.offset:
            if self.file_id:
                self.resets += 1
                log.info("event file restarted; reading from the top")
            self.file_id, self.offset = ident, 0
        if size == self.offset:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError as exc:                          # DCS may hold the file briefly; retry next poll
            log.debug("event file busy: %s", exc)
            return []
        end = chunk.rfind(b"\n")
        if end < 0:
            return []                                   # only a partial line so far
        out: List[Dict[str, Any]] = []
        for raw in chunk[: end + 1].splitlines():
            ev = parse_line(raw.decode("utf-8", "replace"))
            if ev is None:
                if raw.strip():
                    self.malformed += 1
                continue
            eid = str(ev.get("id", ""))
            if not eid or eid in self.seen:
                continue
            self.seen.add(eid)
            out.append(ev)
        self.offset += end + 1
        if self.store:
            self.store.set_cursor(self.cursor_name, self.file_id, self.offset)
        return out

    def reset(self) -> None:
        self.offset, self.file_id, self.seen = 0, "", set()
        if self.store:
            self.store.set_cursor(self.cursor_name, "", 0)


def parse_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) and "ev" in ev else None


def read_all(path: Path) -> List[Dict[str, Any]]:
    """Whole file, complete lines only, de-duplicated."""
    tail = EventTail(path)
    return tail.poll()


def parse_dcs_log(path: Path) -> List[Dict[str, Any]]:
    """Fallback when MissionScripting.lua is sanitised: events are in dcs.log as SORTIE_EVT lines."""
    out, seen = [], set()
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        m = LOG_LINE.search(line)
        ev = parse_line(m.group(1)) if m else None
        if ev and ev.get("id") not in seen:
            seen.add(ev.get("id"))
            out.append(ev)
    return out


def latest_run(events: List[Dict[str, Any]], sortie_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Events of the last mission run (from the last mission_start), optionally for one sortie id."""
    start = 0
    for i, e in enumerate(events):
        if e.get("ev") == "mission_start" and (sortie_id is None or e.get("sortie") == sortie_id):
            start = i
    run = events[start:]
    if sortie_id is not None and (not run or run[0].get("sortie") != sortie_id):
        return []
    return run
