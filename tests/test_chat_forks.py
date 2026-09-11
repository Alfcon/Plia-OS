from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── list ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_forks_empty():
    with patch("core.fork_store.list_forks", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/forks")
    assert r.status_code == 200
    assert r.json()["forks"] == []


@pytest.mark.asyncio
async def test_list_forks_returns_items():
    forks = [{"name": "a.json", "label": "test", "created_at": 1, "turn_count": 5}]
    with patch("core.fork_store.list_forks", return_value=forks):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/forks")
    assert r.json()["forks"][0]["label"] == "test"


# ── save ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_fork_ok():
    turns = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    with patch("agents.chat_history.get_recent", return_value=turns), \
         patch("core.fork_store.save_fork", return_value="20260628_fork.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/forks", json={"label": "my fork"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["turn_count"] == 2


@pytest.mark.asyncio
async def test_save_fork_empty_history_400():
    with patch("agents.chat_history.get_recent", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/forks", json={"label": "empty"})
    assert r.status_code == 400


# ── get ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_fork_ok():
    fork_data = {"_label": "test", "_created_at": 1, "turns": [{"role": "user", "content": "hi"}]}
    with patch("core.fork_store.get_fork", return_value=fork_data):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/forks/test.json")
    assert r.status_code == 200
    assert r.json()["_label"] == "test"


@pytest.mark.asyncio
async def test_get_fork_not_found_404():
    with patch("core.fork_store.get_fork", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/forks/missing.json")
    assert r.status_code == 404


# ── restore ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restore_fork_ok():
    fork_data = {"_label": "snap", "_created_at": 1, "turns": [
        {"role": "user", "content": "ping"}, {"role": "assistant", "content": "pong"}
    ]}
    with patch("core.fork_store.get_fork", return_value=fork_data), \
         patch("agents.chat_history.get_recent", return_value=[]), \
         patch("core.fork_store.save_fork", return_value="pre.json"), \
         patch("agents.chat_history.clear"), \
         patch("agents.chat_history.add_message"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/forks/snap.json/restore")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["turn_count"] == 2


@pytest.mark.asyncio
async def test_restore_fork_not_found_404():
    with patch("core.fork_store.get_fork", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/forks/missing.json/restore")
    assert r.status_code == 404


# ── delete ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_fork_ok():
    with patch("core.fork_store.delete_fork", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/chat/forks/snap.json")
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_fork_not_found_404():
    with patch("core.fork_store.delete_fork", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/chat/forks/missing.json")
    assert r.status_code == 404
