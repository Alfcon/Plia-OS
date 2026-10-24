from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _future_iso(hours=1):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _mock_store():
    store = MagicMock()
    store._conn = MagicMock()
    return store


# ── PATCH /api/reminders/{id} ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edit_reminder_message():
    fire_at = _future_iso(2)

    def _fake_conn():
        import sqlite3
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, message TEXT, fire_at TEXT, done INTEGER, is_timer INTEGER)")
        conn.execute("INSERT INTO reminders VALUES (1, 'old msg', ?, 0, 0)", (fire_at,))
        conn.commit()
        return conn

    class _FakeStore:
        def _conn(self): return _fake_conn()

    with patch("agents.memory_store.get_memory_store", return_value=_FakeStore()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.patch("/api/reminders/1", json={"message": "new msg"})

    assert r.status_code == 200
    assert r.json()["message"] == "new msg"
    assert r.json()["id"] == 1


@pytest.mark.asyncio
async def test_edit_reminder_fire_at():
    original = _future_iso(1)
    new_time = _future_iso(3)

    def _fake_conn():
        import sqlite3, tempfile
        db = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, message TEXT, fire_at TEXT, done INTEGER, is_timer INTEGER)")
        conn.execute("INSERT INTO reminders VALUES (2, 'msg', ?, 0, 0)", (original,))
        conn.commit()
        return conn

    class _FakeStore:
        def _conn(self): return _fake_conn()

    with patch("agents.memory_store.get_memory_store", return_value=_FakeStore()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.patch("/api/reminders/2", json={"fire_at": new_time})

    assert r.status_code == 200
    assert r.json()["fire_at"] == new_time


@pytest.mark.asyncio
async def test_edit_reminder_both_fields():
    def _fake_conn():
        import sqlite3, tempfile
        db = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, message TEXT, fire_at TEXT, done INTEGER, is_timer INTEGER)")
        conn.execute("INSERT INTO reminders VALUES (3, 'old', ?, 0, 0)", (_future_iso(1),))
        conn.commit()
        return conn

    class _FakeStore:
        def _conn(self): return _fake_conn()

    new_time = _future_iso(5)
    with patch("agents.memory_store.get_memory_store", return_value=_FakeStore()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.patch("/api/reminders/3", json={"message": "updated", "fire_at": new_time})

    assert r.status_code == 200
    assert r.json()["message"] == "updated"
    assert r.json()["fire_at"] == new_time


@pytest.mark.asyncio
async def test_edit_reminder_no_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.patch("/api/reminders/1", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_reminder_invalid_fire_at():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.patch("/api/reminders/1", json={"fire_at": "not-a-date"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_reminder_naive_datetime_rejected():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.patch("/api/reminders/1", json={"fire_at": "2026-07-01T09:00:00"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_reminder_not_found():
    def _fake_conn():
        import sqlite3, tempfile
        db = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, message TEXT, fire_at TEXT, done INTEGER, is_timer INTEGER)")
        conn.commit()
        return conn

    class _FakeStore:
        def _conn(self): return _fake_conn()

    with patch("agents.memory_store.get_memory_store", return_value=_FakeStore()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.patch("/api/reminders/999", json={"message": "x"})

    assert r.status_code == 404


# ── Existing endpoints unaffected ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_reminders_ok():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/reminders")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_create_and_delete_reminder():
    fire_at = _future_iso(1)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/reminders", json={"message": "test", "fire_at": fire_at})
        assert r.status_code == 200
        rid = r.json()["id"]
        r2 = await c.delete(f"/api/reminders/{rid}")
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_create_reminder_naive_datetime_rejected():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/reminders", json={"message": "test", "fire_at": "2026-07-01T09:00:00"})
    assert r.status_code == 422
