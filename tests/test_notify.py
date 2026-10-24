from __future__ import annotations

import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset():
    import dashboard.server as srv
    srv._NOTIFY_HISTORY.clear()


def _mock_proc(returncode: int = 0, stderr: bytes = b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    return proc


@pytest.mark.asyncio
async def test_notify_no_message_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/notify", json={"title": "Hi"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_notify_calls_notify_send():
    proc = _mock_proc(0)
    with patch("asyncio.create_subprocess_exec", return_value=proc) as m:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/notify", json={"title": "Test", "message": "hello"})
    assert r.status_code == 200
    call_args = m.call_args[0]
    assert "notify-send" in call_args


@pytest.mark.asyncio
async def test_notify_ok_true_on_success():
    proc = _mock_proc(0)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/notify", json={"title": "T", "message": "m"})
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_notify_ok_false_on_failure():
    proc = _mock_proc(1, b"no daemon")
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/notify", json={"title": "T", "message": "fail"})
    d = r.json()
    assert d["ok"] is False
    assert "error" in d


@pytest.mark.asyncio
async def test_notify_history_empty():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/notify/history")
    assert r.status_code == 200
    assert r.json()["history"] == []
    _reset()


@pytest.mark.asyncio
async def test_notify_history_records_entry():
    _reset()
    proc = _mock_proc(0)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/notify", json={"title": "T", "message": "hello world"})
            r = await c.get("/api/notify/history")
    h = r.json()["history"]
    assert len(h) == 1
    assert h[0]["message"] == "hello world"
    _reset()


@pytest.mark.asyncio
async def test_notify_invalid_urgency_defaults_to_normal():
    proc = _mock_proc(0)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/notify", json={"title": "T", "message": "m", "urgency": "extreme"})
    assert r.json()["urgency"] == "normal"
