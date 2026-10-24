from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_proc(returncode: int):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    return proc


@pytest.mark.asyncio
async def test_screenshot_503_when_no_tool(tmp_path):
    fake_png = tmp_path / "shot.png"

    async def mock_exec(*args, **kwargs):
        return _mock_proc(1)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/screenshot")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_screenshot_success(tmp_path):
    import base64

    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    call_count = 0

    async def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        fname = args[1]
        import pathlib
        pathlib.Path(fname).write_bytes(png_data)
        return _mock_proc(0)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/screenshot")

    assert r.status_code == 200
    d = r.json()
    assert "image" in d
    assert "size" in d
    assert d["size"] == len(png_data)
    assert base64.b64decode(d["image"]) == png_data


@pytest.mark.asyncio
async def test_screenshot_returns_base64_string(tmp_path):
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

    async def mock_exec(*args, **kwargs):
        fname = args[1]
        import pathlib
        pathlib.Path(fname).write_bytes(png_data)
        return _mock_proc(0)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/screenshot")

    assert r.status_code == 200
    img = r.json()["image"]
    import base64
    decoded = base64.b64decode(img)
    assert decoded == png_data


@pytest.mark.asyncio
async def test_screenshot_falls_back_to_second_tool():
    call_count = 0
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

    async def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_proc(1)
        # filename is always the last positional arg for all three commands
        fname = args[-1]
        import pathlib
        pathlib.Path(fname).write_bytes(png_data)
        return _mock_proc(0)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/screenshot")

    assert r.status_code == 200
    assert call_count >= 2
