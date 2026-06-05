import pytest
from httpx import AsyncClient, ASGITransport
from core.main import create_app


async def test_app_starts_and_dashboard_loads():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "Plia-OS" in resp.text


async def test_api_tools_returns_example_module_tools():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert "get_time" in tools
    assert "set_reminder" in tools
