from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_replay_missing_message_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/pipeline/replay", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_replay_blank_message_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/pipeline/replay", json={"message": "   "})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_replay_returns_response():
    with patch("core.supervisor.run_turn", new=AsyncMock(return_value=("hello!", []))):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/pipeline/replay", json={"message": "ping"})
    assert r.status_code == 200
    data = r.json()
    assert data["response"] == "hello!"
    assert "latency_ms" in data


@pytest.mark.asyncio
async def test_replay_latency_non_negative():
    with patch("core.supervisor.run_turn", new=AsyncMock(return_value=("ok", []))):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/pipeline/replay", json={"message": "test"})
    assert r.json()["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_replay_passes_system_prompt():
    captured = {}

    async def _fake_run_turn(messages):
        captured["messages"] = messages
        return ("resp", [])

    with patch("core.supervisor.run_turn", side_effect=_fake_run_turn):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/pipeline/replay", json={"message": "hi"})

    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1]["role"] == "user"
    assert captured["messages"][-1]["content"] == "hi"


@pytest.mark.asyncio
async def test_replay_fresh_context_two_messages_only():
    captured = {}

    async def _fake_run_turn(messages):
        captured["messages"] = messages
        return ("resp", [])

    with patch("core.supervisor.run_turn", side_effect=_fake_run_turn):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/pipeline/replay", json={"message": "hello"})

    # Only system + user — no history injected
    assert len(captured["messages"]) == 2
