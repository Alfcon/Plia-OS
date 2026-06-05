import pytest
import asyncio
import json
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from core.registry import tool
from core import events
from core.config import reset_config as _reset_config
from dashboard.server import router


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture(autouse=True)
def reset_cfg():
    yield
    _reset_config()


async def test_get_tools(app):
    @tool(description="test tool")
    def my_tool() -> str:
        return "ok"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "my_tool" in data
    assert data["my_tool"] == "test tool"


async def test_get_config(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["ollama_model"] == "llama3.2"


async def test_post_config_updates_value(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"ollama_model": "mistral"})
    assert resp.status_code == 200
    assert resp.json()["ollama_model"] == "mistral"


async def test_post_config_unknown_key_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"nonexistent_key": "value"})
    assert resp.status_code == 422
