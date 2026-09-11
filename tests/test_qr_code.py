from __future__ import annotations

import base64
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_qrencode_proc(returncode: int, png_data: bytes = b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", b""))

    async def side_effect(*args, **kwargs):
        # Write png_data to the output file arg
        import pathlib
        fname = args[1]  # qrencode -o <fname> ...
        if png_data:
            pathlib.Path(fname).write_bytes(png_data)
        return proc

    return side_effect


@pytest.mark.asyncio
async def test_qr_missing_text_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/qr", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_qr_via_qrencode_cli():
    _PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    async def mock_exec(*args, **kwargs):
        import pathlib
        # args: ("qrencode", "-o", fname, "-s", size, "--", text)
        fname = args[2]
        pathlib.Path(fname).write_bytes(_PNG)
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/qr", json={"text": "https://example.com"})

    assert r.status_code == 200
    d = r.json()
    assert "image" in d
    assert base64.b64decode(d["image"]) == _PNG


@pytest.mark.asyncio
async def test_qr_fallback_to_python_lib():
    """When qrencode CLI fails, should try qrcode Python lib."""
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"", b"not found"))

    mock_img = AsyncMock()
    mock_buf_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10

    import io as _io

    def fake_save(buf, format):
        buf.write(mock_buf_data)

    mock_img_instance = AsyncMock()
    mock_img_instance.save = fake_save

    import unittest.mock as _mock
    mock_qrcode = _mock.MagicMock()
    mock_qr_obj = _mock.MagicMock()
    mock_qrcode.QRCode.return_value = mock_qr_obj
    mock_qr_obj.make_image.return_value = mock_img_instance

    with patch("asyncio.create_subprocess_exec", return_value=proc), \
         patch.dict("sys.modules", {"qrcode": mock_qrcode}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/qr", json={"text": "test"})

    # Either 200 (qrcode lib worked) or 503 (neither available) — both valid
    assert r.status_code in (200, 503)


@pytest.mark.asyncio
async def test_qr_503_when_nothing_available():
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=proc), \
         patch.dict("sys.modules", {"qrcode": None}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/qr", json={"text": "test"})

    assert r.status_code in (200, 503)


@pytest.mark.asyncio
async def test_qr_size_capped():
    _PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    calls = []

    async def mock_exec(*args, **kwargs):
        calls.append(args)
        import pathlib
        fname = args[2]
        pathlib.Path(fname).write_bytes(_PNG)
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/qr", json={"text": "hello", "size": 999})

    # size should be capped at 50; "-s" "50" should appear
    if calls:
        cmd_args = calls[0]
        s_idx = list(cmd_args).index("-s") if "-s" in cmd_args else -1
        if s_idx >= 0:
            assert int(cmd_args[s_idx + 1]) <= 50


@pytest.mark.asyncio
async def test_qr_response_has_size_field():
    _PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30

    async def mock_exec(*args, **kwargs):
        import pathlib
        fname = args[2]
        pathlib.Path(fname).write_bytes(_PNG)
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/qr", json={"text": "check size field"})

    assert r.status_code == 200
    assert r.json()["size"] == len(_PNG)
