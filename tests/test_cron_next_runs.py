from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_FAKE_JOBS = [
    {"id": 1, "name": "hourly", "expr": "0 * * * *", "message": "ping", "enabled": True},
    {"id": 2, "name": "daily", "expr": "0 9 * * *", "message": "morning", "enabled": True},
]


@pytest.mark.asyncio
async def test_next_runs_200():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/hourly/next?n=3")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_next_runs_returns_list():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/hourly/next?n=3")
    d = r.json()
    assert len(d["next_runs"]) == 3


@pytest.mark.asyncio
async def test_next_runs_default_n5():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/hourly/next")
    assert len(r.json()["next_runs"]) == 5


@pytest.mark.asyncio
async def test_next_runs_not_found_404():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/nonexistent/next?n=1")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_next_runs_includes_name_and_expr():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/daily/next?n=2")
    d = r.json()
    assert d["name"] == "daily"
    assert d["expr"] == "0 9 * * *"


@pytest.mark.asyncio
async def test_next_runs_iso_format():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/hourly/next?n=1")
    run = r.json()["next_runs"][0]
    from datetime import datetime
    dt = datetime.fromisoformat(run)
    assert dt is not None


@pytest.mark.asyncio
async def test_next_runs_clamps_n_to_20():
    with patch("agents.cron_store.get_cron_store") as m:
        m.return_value.list_all.return_value = _FAKE_JOBS
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cron/hourly/next?n=100")
    assert len(r.json()["next_runs"]) == 20
