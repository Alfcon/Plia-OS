from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_history_export_json():
    with patch("agents.chat_history.get_recent", return_value=[
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_history_export_markdown():
    with patch("agents.chat_history.get_recent", return_value=[
        {"role": "user", "content": "hello"},
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    assert r.status_code == 200
    assert "text/" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_history_export_unknown_format_falls_back_to_json():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/history/export?fmt=xml")
    # Unknown formats default to JSON
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_history_export_json_content():
    msgs = [
        {"role": "user", "content": "ping"},
        {"role": "assistant", "content": "pong"},
    ]
    with patch("agents.chat_history.get_recent", return_value=msgs):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    assert b"ping" in r.content
    assert b"pong" in r.content


@pytest.mark.asyncio
async def test_history_export_markdown_content():
    msgs = [{"role": "user", "content": "test message"}]
    with patch("agents.chat_history.get_recent", return_value=msgs):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    assert b"test message" in r.content


@pytest.mark.asyncio
async def test_chatexport_nav_section_present():
    """Dashboard HTML must include the chatexport panel."""
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "dashboard" / "static" / "index.html").read_text()
    assert "m-section-chatexport" in html
    assert "chatexport-count" in html
