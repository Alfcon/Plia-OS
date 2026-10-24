from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset_stats():
    from core.context_compactor import _STATS
    _STATS["compactions"] = 0
    _STATS["messages_summarised"] = 0
    _STATS["messages_kept"] = 0
    _STATS["failures"] = 0


@pytest.mark.asyncio
async def test_stats_returns_all_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/context/stats")
    assert r.status_code == 200
    data = r.json()
    for key in ("compactions", "messages_summarised", "messages_kept", "failures", "threshold", "keep_recent"):
        assert key in data


@pytest.mark.asyncio
async def test_stats_threshold_correct():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/context/stats")
    data = r.json()
    assert data["threshold"] == 30
    assert data["keep_recent"] == 20


@pytest.mark.asyncio
async def test_stats_reset():
    from core.context_compactor import _STATS
    _STATS["compactions"] = 5
    _STATS["messages_summarised"] = 100
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/context/stats/reset")
    assert r.json()["ok"] is True
    data_r = await AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test").get("/api/context/stats")
    data = data_r.json()
    assert data["compactions"] == 0
    assert data["messages_summarised"] == 0
    _reset_stats()


@pytest.mark.asyncio
async def test_stats_counters_increment_on_compaction():
    import asyncio
    from unittest.mock import patch, AsyncMock
    from core.context_compactor import maybe_compact, _STATS
    _reset_stats()

    async def _fake_summarise(msgs):
        return "summary"

    with patch("core.context_compactor._summarise", side_effect=_fake_summarise):
        # Build a message list large enough to trigger compaction (>30 non-system)
        messages = [{"role": "system", "content": "sys"}] + [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(35)
        ]
        await maybe_compact(messages)

    assert _STATS["compactions"] == 1
    assert _STATS["messages_summarised"] > 0
    assert _STATS["messages_kept"] > 0
    _reset_stats()


@pytest.mark.asyncio
async def test_stats_failure_increments_on_error():
    import asyncio
    from unittest.mock import patch
    from core.context_compactor import maybe_compact, _STATS
    _reset_stats()

    with patch("core.context_compactor._summarise", side_effect=Exception("LLM down")):
        messages = [{"role": "system", "content": "sys"}] + [
            {"role": "user", "content": f"msg {i}"} for i in range(35)
        ]
        result = await maybe_compact(messages)

    assert _STATS["failures"] == 1
    assert _STATS["compactions"] == 0
    assert result == messages  # returned unchanged
    _reset_stats()
