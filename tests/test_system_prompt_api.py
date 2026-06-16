import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_undo_system_prompt_returns_restored(app):
    with patch("dashboard.server.restore_system_prompt", return_value="old prompt"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/system-prompt/undo")
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "old prompt"


@pytest.mark.asyncio
async def test_undo_system_prompt_no_backup_returns_422(app):
    with patch("dashboard.server.restore_system_prompt", return_value=""):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/system-prompt/undo")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_reset_system_prompt_returns_default(app):
    with patch("dashboard.server.reset_system_prompt_to_default", return_value="You are Plia."):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/system-prompt/reset")
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "You are Plia."


@pytest.mark.asyncio
async def test_reset_system_prompt_always_succeeds(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/system-prompt/reset")
    assert r.status_code == 200
    assert "system_prompt" in r.json()
