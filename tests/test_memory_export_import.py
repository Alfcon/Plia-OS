from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _make_store(tmp_path):
    from agents.memory_store import MemoryStore
    return MemoryStore(
        str(tmp_path / "memory.db"),
        str(tmp_path / "chroma"),
    )


@pytest.mark.asyncio
async def test_export_returns_json(tmp_path):
    store = _make_store(tmp_path)
    store.remember("lang", "python")
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/memory/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_export_includes_facts(tmp_path):
    store = _make_store(tmp_path)
    store.remember("color", "blue")
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/memory/export")
    data = r.json()
    assert any(f["key"] == "color" and f["value"] == "blue" for f in data["facts"])


@pytest.mark.asyncio
async def test_export_includes_reminders(tmp_path):
    store = _make_store(tmp_path)
    store.add_reminder("feed cat", "2030-01-01T00:00:00+00:00")
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/memory/export")
    data = r.json()
    assert any("feed cat" in rem["message"] for rem in data["reminders"])


@pytest.mark.asyncio
async def test_export_content_disposition(tmp_path):
    store = _make_store(tmp_path)
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/memory/export")
    assert "attachment" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_import_restores_facts(tmp_path):
    store = _make_store(tmp_path)
    payload = {"facts": [{"key": "animal", "value": "cat"}], "history": [], "reminders": []}
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/memory/import", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert store.get_fact("animal") == "cat"


@pytest.mark.asyncio
async def test_import_reports_counts(tmp_path):
    store = _make_store(tmp_path)
    payload = {
        "facts": [{"key": "x", "value": "1"}, {"key": "y", "value": "2"}],
        "history": [],
        "reminders": [{"message": "meeting", "fire_at": "2030-01-01T12:00:00+00:00", "done": False}],
    }
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/memory/import", json=payload)
    d = r.json()
    assert d["facts"] == 2
    assert d["reminders"] == 1


@pytest.mark.asyncio
async def test_import_skips_done_reminders(tmp_path):
    store = _make_store(tmp_path)
    payload = {
        "facts": [],
        "history": [],
        "reminders": [{"message": "done rem", "fire_at": "2020-01-01T00:00:00+00:00", "done": True}],
    }
    with patch("dashboard.server.get_memory_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/memory/import", json=payload)
    assert r.json()["reminders"] == 0
