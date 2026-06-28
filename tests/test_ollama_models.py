from __future__ import annotations

import pytest
import respx
import httpx
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from unittest.mock import patch


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_list_models_ok():
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "llama3"}, {"name": "mistral"}]})
        )
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/ollama/models")
    assert r.status_code == 200
    data = r.json()
    assert "llama3" in data["models"]
    assert "mistral" in data["models"]
    assert "current" in data


@pytest.mark.asyncio
async def test_list_models_unreachable_503():
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/ollama/models")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_list_models_includes_current():
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "phi3"}]})
        )
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/ollama/models")
    assert r.json()["current"] is not None


@pytest.mark.asyncio
async def test_set_model_ok():
    with patch("core.config.update_config") as mock_update:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/ollama/model", json={"model": "mistral"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["model"] == "mistral"


@pytest.mark.asyncio
async def test_set_model_empty_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ollama/model", json={"model": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_set_model_missing_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ollama/model", json={})
    assert r.status_code == 400
