from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_get_watchdog_returns_tasks():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/watchdog")
    assert r.status_code == 200
    d = r.json()
    assert "tasks" in d
    assert "total" in d
    assert "named" in d
    assert isinstance(d["tasks"], list)
    assert d["total"] >= 0


@pytest.mark.asyncio
async def test_get_watchdog_task_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/watchdog")
    d = r.json()
    if d["tasks"]:
        task = d["tasks"][0]
        assert "name" in task
        assert "done" in task


@pytest.mark.asyncio
async def test_restart_unknown_task_404():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/watchdog/restart/nonexistent_xyz_task")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restart_registered_task_ok():
    import dashboard.server as srv
    original = dict(srv._WATCHDOG_REGISTRY)
    ran = []

    async def fake_coro():
        ran.append(True)
        await asyncio.sleep(10)

    srv._WATCHDOG_REGISTRY["_test_task"] = {"factory": fake_coro, "task": None}
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/watchdog/restart/_test_task")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        task = srv._WATCHDOG_REGISTRY["_test_task"].get("task")
        if task:
            task.cancel()
    finally:
        srv._WATCHDOG_REGISTRY.clear()
        srv._WATCHDOG_REGISTRY.update(original)


@pytest.mark.asyncio
async def test_restart_cancels_old_task():
    import dashboard.server as srv
    original = dict(srv._WATCHDOG_REGISTRY)
    cancelled = []

    async def long_running():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    old_task = asyncio.create_task(long_running())
    srv._WATCHDOG_REGISTRY["_cancel_test"] = {"factory": long_running, "task": old_task}
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/watchdog/restart/_cancel_test")
        await asyncio.sleep(0.05)
        assert old_task.cancelled() or old_task.done()
    finally:
        new_task = srv._WATCHDOG_REGISTRY.get("_cancel_test", {}).get("task")
        if new_task:
            new_task.cancel()
        srv._WATCHDOG_REGISTRY.clear()
        srv._WATCHDOG_REGISTRY.update(original)


@pytest.mark.asyncio
async def test_watchdog_named_shows_registered():
    import dashboard.server as srv
    original = dict(srv._WATCHDOG_REGISTRY)
    ran = []

    async def dummy():
        await asyncio.sleep(5)

    srv._WATCHDOG_REGISTRY["_vis_test"] = {"factory": dummy, "task": None}
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/watchdog")
        assert "_vis_test" in r.json()["named"]
    finally:
        srv._WATCHDOG_REGISTRY.clear()
        srv._WATCHDOG_REGISTRY.update(original)
