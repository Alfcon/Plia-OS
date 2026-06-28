from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset():
    import dashboard.server as srv
    srv._CONFIG_HISTORY.clear()


@pytest.mark.asyncio
async def test_history_empty_initially():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config/history")
    assert r.status_code == 200
    assert r.json()["history"] == []
    _reset()


@pytest.mark.asyncio
async def test_history_recorded_on_change():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/config", json={"stt_language": "fr"})
        r = await c.get("/api/config/history")
    data = r.json()
    assert len(data["history"]) >= 1
    assert "stt_language" in data["history"][0]["changes"]
    _reset()


@pytest.mark.asyncio
async def test_history_records_old_and_new():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        # Set to known value first
        await c.post("/api/config", json={"stt_language": "en"})
        _reset()
        await c.post("/api/config", json={"stt_language": "de"})
        r = await c.get("/api/config/history")
    changes = r.json()["history"][0]["changes"]
    assert changes["stt_language"]["new"] == "de"
    _reset()


@pytest.mark.asyncio
async def test_history_not_recorded_when_no_change():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        # get current value first
        cfg = (await c.get("/api/config")).json()
        current = cfg.get("stt_language", "en")
        # post same value back
        await c.post("/api/config", json={"stt_language": current})
        r = await c.get("/api/config/history")
    assert r.json()["history"] == []
    _reset()


@pytest.mark.asyncio
async def test_history_has_timestamp():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/config", json={"stt_language": "es"})
        r = await c.get("/api/config/history")
    h = r.json()["history"][0]
    assert "ts" in h
    assert h["ts"] > 0
    _reset()


@pytest.mark.asyncio
async def test_history_clear():
    _reset()
    import dashboard.server as srv
    import time
    srv._CONFIG_HISTORY.appendleft({"ts": time.time(), "changes": {"foo": {"old": 1, "new": 2}}})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/config/history")
    assert r.json()["ok"] is True
    assert len(srv._CONFIG_HISTORY) == 0


@pytest.mark.asyncio
async def test_history_n_param():
    _reset()
    import dashboard.server as srv
    import time
    for i in range(10):
        srv._CONFIG_HISTORY.appendleft({"ts": time.time(), "changes": {"k": {"old": i, "new": i+1}}})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config/history?n=3")
    assert len(r.json()["history"]) == 3
    _reset()
