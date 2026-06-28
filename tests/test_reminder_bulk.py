from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _make_store(tmp_path):
    from agents.memory_store import MemoryStore
    return MemoryStore(str(tmp_path / "memory.db"), str(tmp_path / "chroma"))


@pytest.mark.asyncio
async def test_delete_done_200():
    mock = MagicMock()
    mock.delete_done_reminders.return_value = 0
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/reminders/done")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_done_returns_count(tmp_path):
    store = _make_store(tmp_path)
    store.add_reminder("old one", "2020-01-01T00:00:00+00:00")
    store.mark_reminder_done(1)
    with patch("agents.memory_store.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/reminders/done")
    assert r.json()["deleted"] == 1


@pytest.mark.asyncio
async def test_delete_done_not_captured_by_parameterized_route():
    mock = MagicMock()
    mock.delete_done_reminders.return_value = 0
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/reminders/done")
    # Should call delete_done_reminders, not mark_reminder_done with id="done"
    assert mock.delete_done_reminders.called
    assert not mock.mark_reminder_done.called


@pytest.mark.asyncio
async def test_bulk_snooze_200():
    mock = MagicMock()
    mock.bulk_snooze_reminders.return_value = 2
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/reminders/bulk-snooze", json={"ids": [1, 2], "minutes": 15})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["snoozed"] == 2


@pytest.mark.asyncio
async def test_bulk_snooze_no_ids_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/reminders/bulk-snooze", json={"ids": [], "minutes": 10})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_snooze_invalid_minutes_400():
    mock = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/reminders/bulk-snooze", json={"ids": [1], "minutes": 9999})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_snooze_calls_store(tmp_path):
    store = _make_store(tmp_path)
    store.add_reminder("meeting", "2030-01-01T12:00:00+00:00")
    with patch("agents.memory_store.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/reminders/bulk-snooze", json={"ids": [1], "minutes": 30})
    assert r.status_code == 200
    assert r.json()["minutes"] == 30
