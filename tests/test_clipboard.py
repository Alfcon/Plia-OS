from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_proc(returncode: int, stdout: bytes = b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


@pytest.mark.asyncio
async def test_get_clipboard_xclip_success():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, b"hello world")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clipboard")
    assert r.status_code == 200
    assert r.json()["text"] == "hello world"


@pytest.mark.asyncio
async def test_get_clipboard_falls_back_to_xsel():
    call_count = 0

    async def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _mock_proc(0 if call_count > 1 else 1, b"xsel content")

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clipboard")
    assert r.status_code == 200
    assert call_count >= 2


@pytest.mark.asyncio
async def test_get_clipboard_503_when_no_tool():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clipboard")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_clipboard_success():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clipboard", json={"text": "write me"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["length"] == len("write me")


@pytest.mark.asyncio
async def test_post_clipboard_503_when_no_tool():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clipboard", json={"text": "test"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_clipboard_empty_text():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clipboard", json={})
    assert r.status_code == 200
    assert r.json()["length"] == 0
