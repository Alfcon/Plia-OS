from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_pdf_export_no_wkhtmltopdf_503():
    with patch("shutil.which", return_value=None):
        with patch("agents.chat_history.get_recent", return_value=[]):
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                r = await c.get("/api/history/export/pdf")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_pdf_export_returns_pdf_bytes():
    fake_pdf = b"%PDF-1.4 fake"

    async def _fake_subprocess(*args, **kwargs):
        import types
        proc = types.SimpleNamespace()
        proc.returncode = 0
        async def communicate(): return b"", b""
        proc.communicate = communicate
        return proc

    def _fake_read_bytes(self):
        return fake_pdf

    with patch("shutil.which", return_value="/usr/bin/wkhtmltopdf"), \
         patch("agents.chat_history.get_recent", return_value=[
             {"role": "user", "content": "hello", "ts": "2026-01-01"},
             {"role": "assistant", "content": "hi", "ts": "2026-01-01"},
         ]), \
         patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_bytes", _fake_read_bytes), \
         patch("pathlib.Path.unlink"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_pdf_export_content_disposition():
    fake_pdf = b"%PDF-1.4 fake"

    async def _fake_subprocess(*args, **kwargs):
        import types
        proc = types.SimpleNamespace()
        proc.returncode = 0
        async def communicate(): return b"", b""
        proc.communicate = communicate
        return proc

    with patch("shutil.which", return_value="/usr/bin/wkhtmltopdf"), \
         patch("agents.chat_history.get_recent", return_value=[]), \
         patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_bytes", return_value=fake_pdf), \
         patch("pathlib.Path.unlink"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export/pdf")
    assert "chat_export.pdf" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_pdf_export_process_failure_500():
    async def _fake_subprocess(*args, **kwargs):
        import types
        proc = types.SimpleNamespace()
        proc.returncode = 1
        async def communicate(): return b"", b"error"
        proc.communicate = communicate
        return proc

    with patch("shutil.which", return_value="/usr/bin/wkhtmltopdf"), \
         patch("agents.chat_history.get_recent", return_value=[]), \
         patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.unlink"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export/pdf")
    assert r.status_code == 500
