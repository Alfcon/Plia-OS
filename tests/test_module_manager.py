import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_modules_returns_all(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/modules")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = [m["name"] for m in data]
    assert "utility_tools" in names
    for m in data:
        assert "name" in m
        assert "tools" in m
        assert "enabled" in m


@pytest.mark.asyncio
async def test_disable_module_marks_disabled(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/modules/utility_tools/disable")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_enable_module_marks_enabled(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/modules/utility_tools/disable")
        r = await client.post("/api/modules/utility_tools/enable")
    assert r.status_code == 200
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_disabled_module_excluded_from_tool_schemas(app):
    from core import registry
    from core.config import update_config, get_config
    update_config(disabled_modules=["utility_tools"])
    try:
        schemas = registry.get_tool_schemas()
        tool_names = [s["function"]["name"] for s in schemas]
        assert "get_time" not in tool_names
    finally:
        update_config(disabled_modules=[])


@pytest.mark.asyncio
async def test_enabled_module_included_in_tool_schemas(app):
    from core import registry
    from core.config import update_config
    update_config(disabled_modules=[])
    schemas = registry.get_tool_schemas()
    tool_names = [s["function"]["name"] for s in schemas]
    assert "get_time" in tool_names


@pytest.mark.asyncio
async def test_list_modules_shows_enabled_status(app):
    from core.config import update_config
    update_config(disabled_modules=["utility_tools"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/modules")
        data = {m["name"]: m for m in r.json()}
        assert data["utility_tools"]["enabled"] is False
    finally:
        update_config(disabled_modules=[])
