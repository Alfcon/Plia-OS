from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_obs(running=False, profile="", last_capture=None, last_profile=None):
    obs = MagicMock()
    obs.is_running.return_value = running
    obs.get_profile.return_value = profile
    obs.last_capture_ts.return_value = last_capture
    obs.last_profile_ts.return_value = last_profile
    obs.start = AsyncMock()
    obs.stop = AsyncMock()
    return obs


@pytest.mark.asyncio
async def test_observer_status_endpoint():
    obs = _make_obs(running=True, profile="User coding.", last_capture="2026-01-01T00:00:00",
                    last_profile="2026-01-01T00:05:00")
    with patch("core.observer.get_observer", return_value=obs):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.get("/api/observer/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["profile_preview"] == "User coding."
    assert data["last_capture"] == "2026-01-01T00:00:00"


@pytest.mark.asyncio
async def test_observer_enable_endpoint():
    obs = _make_obs(running=False)
    with patch("core.observer.get_observer", return_value=obs), \
         patch("core.config.update_config") as mock_update:
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.post("/api/observer/enable")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    mock_update.assert_called_with(observer_enabled=True)


@pytest.mark.asyncio
async def test_observer_disable_endpoint():
    obs = _make_obs(running=True)
    with patch("core.observer.get_observer", return_value=obs), \
         patch("core.config.update_config") as mock_update:
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.post("/api/observer/disable")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    mock_update.assert_called_with(observer_enabled=False)


@pytest.mark.asyncio
async def test_observer_status_endpoint_stopped():
    obs = _make_obs(running=False, profile="", last_capture=None, last_profile=None)
    with patch("core.observer.get_observer", return_value=obs):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.get("/api/observer/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["profile_preview"] == ""
