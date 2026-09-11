from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_search_empty_query():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/history/search?q=")
    assert r.status_code == 200
    data = r.json()
    assert data["results"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_search_returns_matches():
    messages = [
        {"role": "user", "content": "tell me about dragons", "ts": "2026-01-01"},
        {"role": "assistant", "content": "Dragons are mythical creatures", "ts": "2026-01-01"},
    ]
    with patch("agents.chat_history.search", return_value=messages):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/search?q=dragon")
    data = r.json()
    assert data["total"] == 2
    assert data["query"] == "dragon"


@pytest.mark.asyncio
async def test_search_no_results():
    with patch("agents.chat_history.search", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/search?q=xyznotfound")
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_search_snippet_contains_match():
    messages = [{"role": "user", "content": "a" * 200 + "keyword" + "b" * 200, "ts": ""}]
    with patch("agents.chat_history.search", return_value=messages):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/search?q=keyword")
    snippet = r.json()["results"][0]["snippet"]
    assert "keyword" in snippet
    assert len(snippet) < len(messages[0]["content"])  # truncated


@pytest.mark.asyncio
async def test_search_result_has_role_and_ts():
    messages = [{"role": "assistant", "content": "the answer is yes", "ts": "2026-01-01T00:00:00"}]
    with patch("agents.chat_history.search", return_value=messages):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/history/search?q=answer")
    result = r.json()["results"][0]
    assert result["role"] == "assistant"
    assert result["ts"] == "2026-01-01T00:00:00"


@pytest.mark.asyncio
async def test_search_n_param_passed():
    with patch("agents.chat_history.search") as mock_search:
        mock_search.return_value = []
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.get("/api/history/search?q=test&n=10")
        mock_search.assert_called_once_with("test", 10)
