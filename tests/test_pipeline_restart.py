from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_restart_returns_starting():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/pipeline/restart")
    assert r.status_code == 200
    assert r.json()["state"] == "starting"


@pytest.mark.asyncio
async def test_restart_cancels_existing_task():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_task.cancel = MagicMock()

    with patch("core.pipeline_registry.get_task", return_value=mock_task), \
         patch("core.pipeline_registry.set_task"), \
         patch("core.pipeline_registry.set_state"), \
         patch("asyncio.create_task"), \
         patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.CancelledError())):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/pipeline/restart")
    mock_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_restart_creates_new_task():
    with patch("core.pipeline_registry.get_task", return_value=None), \
         patch("core.pipeline_registry.set_state") as mock_state, \
         patch("asyncio.create_task", return_value=MagicMock()) as mock_ct:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/pipeline/restart")
    mock_ct.assert_called_once()
    mock_state.assert_called_with("starting")


@pytest.mark.asyncio
async def test_pipeline_start_endpoint_still_works():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/pipeline/start")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_pipeline_stop_endpoint_still_works():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/pipeline/stop")
    assert r.status_code == 200
    assert r.json()["state"] == "stopped"


@pytest.mark.asyncio
async def test_restart_sets_task_in_registry():
    captured_task = {}

    def _capture_task(t):
        captured_task["task"] = t

    with patch("core.pipeline_registry.get_task", return_value=None), \
         patch("core.pipeline_registry.set_task", side_effect=_capture_task), \
         patch("core.pipeline_registry.set_state"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/pipeline/restart")
    assert "task" in captured_task
