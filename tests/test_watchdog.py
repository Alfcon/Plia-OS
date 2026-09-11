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
    from core import watchdog

    async def fake_coro():
        await asyncio.sleep(10)

    watchdog.register("_test_task", fake_coro)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/watchdog/restart/_test_task")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    task = watchdog.get_entry("_test_task").task
    if task:
        task.cancel()


@pytest.mark.asyncio
async def test_restart_cancels_old_task():
    from core import watchdog
    cancelled = []

    async def long_running():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    watchdog.register("_cancel_test", long_running)
    old_task = watchdog.spawn("_cancel_test")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/watchdog/restart/_cancel_test")
    await asyncio.sleep(0.05)
    assert old_task.cancelled() or old_task.done()
    new_task = watchdog.get_entry("_cancel_test").task
    if new_task:
        new_task.cancel()


@pytest.mark.asyncio
async def test_watchdog_named_shows_registered():
    from core import watchdog

    async def dummy():
        await asyncio.sleep(5)

    watchdog.register("_vis_test", dummy)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/watchdog")
    assert "_vis_test" in r.json()["named"]


@pytest.mark.asyncio
async def test_register_watchdog_task_stores_description():
    import dashboard.server as srv
    from core import watchdog

    async def dummy():
        await asyncio.sleep(5)

    srv.register_watchdog_task("_desc_test", dummy, description="does dummy things")
    assert watchdog.get_entry("_desc_test").description == "does dummy things"


@pytest.mark.asyncio
async def test_watchdog_named_includes_description():
    import dashboard.server as srv

    async def dummy():
        await asyncio.sleep(5)

    srv.register_watchdog_task("_desc_api_test", dummy, description="visible in API")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/watchdog")
    named = r.json()["named"]
    assert named["_desc_api_test"]["description"] == "visible in API"


@pytest.mark.asyncio
async def test_spawn_watched_names_and_registers():
    from core import watchdog
    from core.main import _spawn_watched

    async def dummy():
        await asyncio.sleep(5)

    task = _spawn_watched("_spawn_test", dummy, "spawned by test")
    assert task.get_name() == "_spawn_test"
    entry = watchdog.get_entry("_spawn_test")
    assert entry.description == "spawned by test"
    assert entry.task is task
    task.cancel()


@pytest.mark.asyncio
async def test_restart_preserves_description():
    import dashboard.server as srv
    from core import watchdog

    async def dummy():
        await asyncio.sleep(5)

    srv.register_watchdog_task("_desc_restart", dummy, description="keeps description")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/watchdog/restart/_desc_restart")
    assert r.status_code == 200
    entry = watchdog.get_entry("_desc_restart")
    assert entry.description == "keeps description"
    if entry.task:
        entry.task.cancel()


def test_core_loops_have_names_and_descriptions():
    from core.main import _CORE_LOOPS
    names = [name for name, _, _ in _CORE_LOOPS]
    for expected in ("voice_pipeline", "reminder_loop", "cron_loop"):
        assert expected in names
    for name, factory, description in _CORE_LOOPS:
        assert callable(factory)
        assert description.strip(), f"{name} missing description"
