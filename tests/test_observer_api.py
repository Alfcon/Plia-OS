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


@pytest.mark.asyncio
async def test_observer_activity_endpoint():
    obs = _make_obs(running=True, profile="User focused on coding.")
    obs._current_app = "code"
    obs._current_window = "main.py — VSCode"
    mock_store = MagicMock()
    mock_store.get_recent_obs.return_value = {
        "focus": [
            {"ts": "2026-06-27T10:00:00+00:00", "app_name": "code", "window_title": "main.py", "duration_seconds": 300.0},
            {"ts": "2026-06-27T10:05:00+00:00", "app_name": "firefox", "window_title": "MDN", "duration_seconds": 120.0},
            {"ts": "2026-06-27T10:07:00+00:00", "app_name": "code", "window_title": "test.py", "duration_seconds": 180.0},
        ],
        "screen": [],
        "keys": [],
    }
    with patch("core.observer.get_observer", return_value=obs), \
         patch("agents.observer_store.get_observer_store", return_value=mock_store):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.get("/api/observer/activity?minutes=60")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_app"] == "code"
    assert data["current_window"] == "main.py — VSCode"
    assert data["profile"] == "User focused on coding."
    # top apps: code=480s, firefox=120s
    top = {x["app"]: x["seconds"] for x in data["top_apps"]}
    assert top["code"] == 480
    assert top["firefox"] == 120
    assert data["top_apps"][0]["app"] == "code"  # sorted descending
    assert len(data["timeline"]) == 3


@pytest.mark.asyncio
async def test_observer_activity_empty():
    obs = _make_obs(running=False, profile="")
    obs._current_app = ""
    obs._current_window = ""
    mock_store = MagicMock()
    mock_store.get_recent_obs.return_value = {"focus": [], "screen": [], "keys": []}
    with patch("core.observer.get_observer", return_value=obs), \
         patch("agents.observer_store.get_observer_store", return_value=mock_store):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.get("/api/observer/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["top_apps"] == []
    assert data["timeline"] == []
    assert data["current_app"] == ""
