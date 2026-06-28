from __future__ import annotations

import time
import pytest
from unittest.mock import patch
from pathlib import Path
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _patch_db(tmp_path):
    return patch("core.event_log._db_path", return_value=tmp_path / "events.db")


# ── Unit: event_log module ────────────────────────────────────────────────────

def test_log_and_get(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_events, _init
        _init()
        log_event({"type": "status", "state": "armed"})
        events = get_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "status"
    assert events[0]["data"]["state"] == "armed"


def test_get_events_newest_first(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_events, _init
        _init()
        log_event({"type": "status", "n": 1})
        log_event({"type": "status", "n": 2})
        log_event({"type": "status", "n": 3})
        events = get_events()
    assert events[0]["data"]["n"] == 3
    assert events[-1]["data"]["n"] == 1


def test_get_events_type_filter(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_events, _init
        _init()
        log_event({"type": "status", "x": 1})
        log_event({"type": "agent_routing", "agent": "memory"})
        log_event({"type": "status", "x": 2})
        events = get_events(event_type="status")
    assert all(e["event_type"] == "status" for e in events)
    assert len(events) == 2


def test_get_events_limit(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_events, _init
        _init()
        for i in range(20):
            log_event({"type": "status", "i": i})
        events = get_events(n=5)
    assert len(events) == 5


def test_clear_events(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_events, clear_events, _init
        _init()
        log_event({"type": "status"})
        log_event({"type": "reminder_fired", "message": "test"})
        deleted = clear_events()
        events = get_events()
    assert deleted == 2
    assert events == []


def test_get_event_types(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_event_types, _init
        _init()
        log_event({"type": "status"})
        log_event({"type": "agent_routing", "agent": "web"})
        log_event({"type": "status"})
        types = get_event_types()
    assert "status" in types
    assert "agent_routing" in types
    assert len(types) == 2


def test_log_event_has_timestamp(tmp_path):
    t0 = time.time()
    with _patch_db(tmp_path):
        from core.event_log import log_event, get_events, _init
        _init()
        log_event({"type": "status"})
        events = get_events()
    assert events[0]["ts"] >= t0


def test_rolling_cap(tmp_path):
    with _patch_db(tmp_path), patch("core.event_log._CAP", 10):
        from core.event_log import log_event, get_events, _init
        import core.event_log as el
        el._CAP = 10
        _init()
        for i in range(15):
            log_event({"type": "status", "i": i})
        events = get_events(n=100)
    assert len(events) <= 10


# ── API tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_get_events(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, _init
        _init()
        log_event({"type": "status", "state": "armed"})
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/events")
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert "types" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_api_get_events_type_filter(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, _init
        _init()
        log_event({"type": "status"})
        log_event({"type": "agent_routing", "agent": "web"})
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/events?type=status")
    assert r.status_code == 200
    events = r.json()["events"]
    assert all(e["event_type"] == "status" for e in events)


@pytest.mark.asyncio
async def test_api_get_events_n_param(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, _init
        _init()
        for i in range(10):
            log_event({"type": "status", "i": i})
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/events?n=3")
    assert r.json()["count"] == 3


@pytest.mark.asyncio
async def test_api_clear_events(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, _init
        _init()
        log_event({"type": "status"})
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/events")
            assert r.json()["ok"] is True
            r2 = await c.get("/api/events")
    assert r2.json()["count"] == 0


@pytest.mark.asyncio
async def test_api_events_types_list(tmp_path):
    with _patch_db(tmp_path):
        from core.event_log import log_event, _init
        _init()
        log_event({"type": "reminder_fired", "message": "x"})
        log_event({"type": "transcript", "text": "hello"})
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/events")
    types = r.json()["types"]
    assert "reminder_fired" in types
    assert "transcript" in types
