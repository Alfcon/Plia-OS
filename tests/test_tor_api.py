import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from core.main import create_app


@pytest.mark.asyncio
async def test_get_tor_status_disabled():
    with patch("core.tor_manager.get_status", return_value={
        "enabled": False, "kill_switch_active": False, "exit_ip": None
    }):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.get("/api/tor/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["kill_switch_active"] is False


@pytest.mark.asyncio
async def test_get_tor_status_enabled():
    with patch("core.tor_manager.get_status", return_value={
        "enabled": True, "kill_switch_active": False, "exit_ip": "185.220.1.1"
    }):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.get("/api/tor/status")
    assert resp.status_code == 200
    assert resp.json()["exit_ip"] == "185.220.1.1"


@pytest.mark.asyncio
async def test_post_tor_enable_success():
    with patch("core.tor_manager.enable", return_value="Tor enabled. Exit node: 1.2.3.4"):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.post("/api/tor/enable")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "enabled" in data["message"].lower()


@pytest.mark.asyncio
async def test_post_tor_enable_failure():
    with patch("core.tor_manager.enable", return_value="tor not installed. Run: sudo apt install tor"):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.post("/api/tor/enable")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "not installed" in data["message"]


@pytest.mark.asyncio
async def test_post_tor_disable():
    with patch("core.tor_manager.disable", return_value="Tor disabled. Clearnet restored."):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            resp = await client.post("/api/tor/disable")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
