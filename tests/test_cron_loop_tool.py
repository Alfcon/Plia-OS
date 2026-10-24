"""Tests for cron loop tool: prefix support."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_cron_tool_prefix_calls_tool(monkeypatch):
    """When cron message is 'tool:morning_briefing', the tool is called and result emitted."""
    from core import events

    emitted = []
    async def fake_emit(type_, data):
        emitted.append((type_, data))
    monkeypatch.setattr(events, "emit", fake_emit)

    async def fake_call_tool(name, args):
        return "Good morning. Weather: sunny."

    with patch("core.registry.call_tool_async", new=AsyncMock(side_effect=fake_call_tool)):
        from core.cron_loop import _fire_cron_job
        await _fire_cron_job({"id": 1, "name": "morning_briefing", "message": "tool:morning_briefing"})

    assert len(emitted) == 1
    assert emitted[0][0] == "reminder_fired"
    assert "Good morning. Weather: sunny." in emitted[0][1]["message"]


@pytest.mark.asyncio
async def test_cron_static_message_unchanged(monkeypatch):
    """Non-tool: messages pass through unchanged."""
    from core import events

    emitted = []
    async def fake_emit(type_, data):
        emitted.append((type_, data))
    monkeypatch.setattr(events, "emit", fake_emit)

    from core.cron_loop import _fire_cron_job
    await _fire_cron_job({"id": 2, "name": "meds", "message": "Take your medication"})

    assert "Take your medication" in emitted[0][1]["message"]


@pytest.mark.asyncio
async def test_cron_tool_failure_emits_error_message(monkeypatch):
    """Tool error emits fallback message rather than crashing the loop."""
    from core import events

    emitted = []
    async def fake_emit(type_, data):
        emitted.append((type_, data))
    monkeypatch.setattr(events, "emit", fake_emit)

    async def boom(name, args):
        raise RuntimeError("weather API down")

    with patch("core.registry.call_tool_async", new=AsyncMock(side_effect=boom)):
        from core.cron_loop import _fire_cron_job
        await _fire_cron_job({"id": 3, "name": "morning_briefing", "message": "tool:morning_briefing"})

    assert len(emitted) == 1
    msg = emitted[0][1]["message"]
    assert "Failed" in msg or "morning_briefing" in msg


@pytest.mark.asyncio
async def test_briefing_cron_config_creates_job(isolate_config_file):
    """Enabling briefing cron via POST /api/config creates the cron job."""
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from core.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        resp = await client.post("/api/config", json={
            "briefing_cron_enabled": True,
            "briefing_cron_time": "08:30",
        })
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["briefing_cron_enabled"] is True
        assert cfg["briefing_cron_time"] == "08:30"

        from agents.cron_store import get_cron_store
        jobs = get_cron_store().list_all()
        job = next((j for j in jobs if j["name"] == "morning_briefing"), None)
        assert job is not None
        assert job["message"] == "tool:morning_briefing"
        assert job["expr"] == "30 8 * * *"


@pytest.mark.asyncio
async def test_briefing_cron_config_removes_job(isolate_config_file):
    """Disabling briefing cron removes the cron job."""
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from core.main import create_app
    from agents.cron_store import get_cron_store

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        await client.post("/api/config", json={"briefing_cron_enabled": True, "briefing_cron_time": "07:00"})
        await client.post("/api/config", json={"briefing_cron_enabled": False})

        jobs = get_cron_store().list_all()
        assert not any(j["name"] == "morning_briefing" for j in jobs)
