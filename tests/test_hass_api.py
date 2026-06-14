import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_entities_returns_empty_when_not_configured(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/hass/entities")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_entities_returns_list_when_configured(app):
    fake_entities = [
        {"entity_id": "light.living_room", "friendly_name": "Living Room", "state": "on", "domain": "light"},
        {"entity_id": "switch.fan", "friendly_name": "Fan", "state": "off", "domain": "switch"},
    ]
    with patch("core.config._config") as mock_cfg, \
         patch("agents.home_assistant.list_entities", new=AsyncMock(return_value=fake_entities)):
        mock_cfg.hass_url = "http://homeassistant.local:8123"
        mock_cfg.hass_token = "abc123"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/hass/entities")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["entity_id"] == "light.living_room"
    assert data[0]["state"] == "on"


@pytest.mark.asyncio
async def test_toggle_returns_503_when_not_configured(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/hass/toggle/light.living_room")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_toggle_calls_correct_service(app):
    with patch("core.config._config") as mock_cfg, \
         patch("agents.home_assistant.call_service", new=AsyncMock(return_value="Called light.toggle on light.living_room")):
        mock_cfg.hass_url = "http://homeassistant.local:8123"
        mock_cfg.hass_token = "abc123"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/hass/toggle/light.living_room")
    assert r.status_code == 200
    assert "result" in r.json()
