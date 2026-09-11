from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_snooze_ok():
    mock_store = MagicMock()
    mock_store.snooze_reminder.return_value = True
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/reminders/1/snooze", json={"minutes": 10})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["snoozed_minutes"] == 10


@pytest.mark.asyncio
async def test_snooze_not_found_404():
    mock_store = MagicMock()
    mock_store.snooze_reminder.return_value = False
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/reminders/999/snooze", json={"minutes": 5})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_snooze_invalid_minutes_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/reminders/1/snooze", json={"minutes": 0})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_snooze_too_large_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/reminders/1/snooze", json={"minutes": 9999})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_snooze_default_minutes():
    mock_store = MagicMock()
    mock_store.snooze_reminder.return_value = True
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/reminders/1/snooze", json={})
    assert r.json()["snoozed_minutes"] == 10


# ── Memory store unit tests ───────────────────────────────────────────────────

def test_snooze_reminder_updates_fire_at(tmp_path):
    from agents.memory_store import MemoryStore
    db_path = str(tmp_path / "memory.db")
    chroma_path = str(tmp_path / "chroma")
    store = MemoryStore(db_path, chroma_path)
    rid = store.add_reminder("test", "2000-01-01T00:00:00+00:00")
    result = store.snooze_reminder(rid, 30)
    assert result is True
    pending = store.get_pending()
    assert all(r["id"] != rid for r in pending)  # fire_at moved to future


def test_snooze_reminder_not_found(tmp_path):
    from agents.memory_store import MemoryStore
    db_path = str(tmp_path / "memory.db")
    chroma_path = str(tmp_path / "chroma")
    store = MemoryStore(db_path, chroma_path)
    result = store.snooze_reminder(9999, 10)
    assert result is False
