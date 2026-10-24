from __future__ import annotations

import json
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_SAMPLE = [
    {"role": "user", "content": "Hello there", "ts": "2026-06-28T10:00:00+00:00"},
    {"role": "assistant", "content": "Hi! How can I help?", "ts": "2026-06-28T10:00:01+00:00"},
    {"role": "user", "content": "What time is it?", "ts": "2026-06-28T10:01:00+00:00"},
]


@pytest.mark.asyncio
async def test_export_json_status():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_export_json_content_type():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    assert "application/json" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_export_json_structure():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    data = json.loads(r.content)
    assert "messages" in data
    assert len(data["messages"]) == 3
    assert data["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_export_json_attachment_header():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ".json" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_markdown_status():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_export_markdown_content_type():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    assert "text/markdown" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_export_markdown_contains_messages():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    body = r.text
    assert "Hello there" in body
    assert "Hi! How can I help?" in body
    assert "What time is it?" in body


@pytest.mark.asyncio
async def test_export_markdown_has_roles():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    body = r.text
    assert "**You**" in body or "user" in body.lower()
    assert "**Plia**" in body or "assistant" in body.lower()


@pytest.mark.asyncio
async def test_export_markdown_attachment_header():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=markdown")
    assert ".md" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_default_is_json():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export")
    assert "application/json" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_export_empty_history():
    with patch("agents.chat_history.get_recent", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/export?fmt=json")
    assert r.status_code == 200
    assert json.loads(r.content)["messages"] == []


@pytest.mark.asyncio
async def test_export_n_param():
    with patch("agents.chat_history.get_recent", return_value=_SAMPLE[:1]) as mock_get:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.get("/api/history/export?n=50")
    mock_get.assert_called_once_with(50)
