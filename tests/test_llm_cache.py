from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset():
    import core.supervisor as sv
    sv._RESPONSE_CACHE.clear()
    sv._CACHE_STATS["hits"] = 0
    sv._CACHE_STATS["misses"] = 0


@pytest.mark.asyncio
async def test_cache_stats_default():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/cache/stats")
    data = r.json()
    assert data["size"] == 0
    assert data["hits"] == 0
    assert data["misses"] == 0
    assert "enabled" in data
    _reset()


@pytest.mark.asyncio
async def test_cache_flush():
    _reset()
    import core.supervisor as sv
    sv._RESPONSE_CACHE["k"] = ("response", [])
    sv._CACHE_STATS["hits"] = 5
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/cache")
    assert r.json()["ok"] is True
    assert len(sv._RESPONSE_CACHE) == 0
    assert sv._CACHE_STATS["hits"] == 0
    _reset()


@pytest.mark.asyncio
async def test_cache_toggle_on():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/cache/toggle", json={"enabled": True})
    assert r.json()["ok"] is True
    assert r.json()["enabled"] is True
    # reset
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/cache/toggle", json={"enabled": False})


@pytest.mark.asyncio
async def test_cache_toggle_off():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/cache/toggle", json={"enabled": True})
        r = await c.post("/api/cache/toggle", json={"enabled": False})
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_cache_stats_reflect_size():
    _reset()
    import core.supervisor as sv
    sv._RESPONSE_CACHE["a"] = ("resp", [])
    sv._RESPONSE_CACHE["b"] = ("resp2", [])
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/cache/stats")
    assert r.json()["size"] == 2
    _reset()


@pytest.mark.asyncio
async def test_cache_hit_rate_calculation():
    _reset()
    import core.supervisor as sv
    sv._CACHE_STATS["hits"] = 3
    sv._CACHE_STATS["misses"] = 1
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/cache/stats")
    assert r.json()["hit_rate"] == 75.0
    _reset()


# ── Supervisor cache unit tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_on_repeat():
    import core.supervisor as sv
    _reset()
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello cache test"}]
    with patch("core.supervisor.get_config") as mock_cfg, \
         patch("core.supervisor._graph") as mock_graph, \
         patch("core.supervisor.get_memory_store") as mock_store, \
         patch("agents.chat_history.add_message", new=AsyncMock()):
        cfg = mock_cfg.return_value
        cfg.llm_cache_enabled = True
        cfg.llm_cache_max = 100
        cfg.web_search_default = "ddg"
        store = mock_store.return_value
        store.recall.return_value = []
        store.add_turn.return_value = None
        mock_graph.ainvoke = AsyncMock(return_value={
            "messages": [{"role": "assistant", "content": "hi there"}]
        })
        await sv.run_turn(list(messages))
        await sv.run_turn(list(messages))
    assert sv._CACHE_STATS["hits"] == 1
    assert sv._CACHE_STATS["misses"] == 1
    _reset()
