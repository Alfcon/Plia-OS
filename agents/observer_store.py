from __future__ import annotations
import os
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILE_RETENTION_DAYS = 7


class ObserverStore:
    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS screen_obs (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL,
                    window_title TEXT,
                    app_name TEXT,
                    ocr_text TEXT
                );
                CREATE TABLE IF NOT EXISTS focus_events (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL,
                    window_title TEXT,
                    app_name TEXT,
                    duration_seconds REAL
                );
                CREATE TABLE IF NOT EXISTS key_events (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL,
                    window_title TEXT,
                    app_name TEXT,
                    text_chunk TEXT
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL,
                    profile_text TEXT
                );
            """)

    def add_screen_obs(self, ts: str, window_title: str | None,
                       app_name: str | None, ocr_text: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO screen_obs (ts, window_title, app_name, ocr_text) VALUES (?, ?, ?, ?)",
                (ts, window_title, app_name, ocr_text),
            )

    def add_focus_event(self, ts: str, window_title: str | None,
                        app_name: str | None, duration_seconds: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO focus_events (ts, window_title, app_name, duration_seconds) VALUES (?, ?, ?, ?)",
                (ts, window_title, app_name, duration_seconds),
            )

    def add_key_chunk(self, ts: str, window_title: str | None,
                      app_name: str | None, text_chunk: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO key_events (ts, window_title, app_name, text_chunk) VALUES (?, ?, ?, ?)",
                (ts, window_title, app_name, text_chunk),
            )

    def get_recent_obs(self, minutes: int = 10) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        with self._conn() as conn:
            screen = conn.execute(
                "SELECT ts, window_title, app_name, ocr_text "
                "FROM screen_obs WHERE ts >= ? ORDER BY ts",
                (cutoff,),
            ).fetchall()
            focus = conn.execute(
                "SELECT ts, window_title, app_name, duration_seconds "
                "FROM focus_events WHERE ts >= ? ORDER BY ts",
                (cutoff,),
            ).fetchall()
            keys = conn.execute(
                "SELECT ts, window_title, app_name, text_chunk "
                "FROM key_events WHERE ts >= ? ORDER BY ts",
                (cutoff,),
            ).fetchall()
        return {
            "screen": [
                {"ts": r[0], "window_title": r[1], "app_name": r[2], "ocr_text": r[3]}
                for r in screen
            ],
            "focus": [
                {"ts": r[0], "window_title": r[1], "app_name": r[2], "duration_seconds": r[3]}
                for r in focus
            ],
            "keys": [
                {"ts": r[0], "window_title": r[1], "app_name": r[2], "text_chunk": r[3]}
                for r in keys
            ],
        }

    def save_profile(self, ts: str, profile_text: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO profiles (ts, profile_text) VALUES (?, ?)",
                (ts, profile_text),
            )

    def get_latest_profile(self) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT profile_text FROM profiles ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None

    def prune_old(self, retention_hours: int = 24) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).isoformat()
        profile_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_PROFILE_RETENTION_DAYS)
        ).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM screen_obs WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM focus_events WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM key_events WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM profiles WHERE ts < ?", (profile_cutoff,))


_store: ObserverStore | None = None


def get_observer_store() -> ObserverStore:
    global _store
    if _store is None:
        from core.config import get_config
        cfg = get_config()
        db_path = str(Path(cfg.memory_dir) / "observer.db")
        _store = ObserverStore(db_path)
    return _store
