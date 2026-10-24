import pytest
import httpx
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from core.main import create_app


def _ollama_down(router):
    router.get("http://localhost:11434/api/tags").mock(
        side_effect=httpx.ConnectError("down")
    )


async def _get(path):
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        return await ac.get(path)


@pytest.mark.asyncio
async def test_recommend_endpoint_returns_tiers(respx_mock):
    _ollama_down(respx_mock)
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)):
        r = await _get("/api/models/recommend")
    assert r.status_code == 200
    data = r.json()
    assert data["hardware"]["vram_gb"] == 24.0
    assert data["hardware"]["ram_gb"] == 64.0
    assert "current" in data
    assert isinstance(data["models"], list) and data["models"]
    assert {"name", "tier", "params_b", "installed"} <= data["models"][0].keys()


@pytest.mark.asyncio
async def test_recommend_endpoint_want_filter(respx_mock):
    _ollama_down(respx_mock)
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)):
        r = await _get("/api/models/recommend?want=coding")
    assert r.status_code == 200
    names = [m["name"] for m in r.json()["models"]]
    assert names
    assert all("coder" in n for n in names)


@pytest.mark.asyncio
async def test_recommend_endpoint_merges_installed(respx_mock):
    respx_mock.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [
            {"name": "qwen2.5:7b", "size": 4_700_000_000},
            {"name": "mystery:latest", "size": 5_000_000_000},
        ]})
    )
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)):
        r = await _get("/api/models/recommend")
    assert r.status_code == 200
    by_name = {m["name"]: m for m in r.json()["models"]}
    assert by_name["qwen2.5:7b"]["installed"] is True
    assert by_name["qwen2.5:7b"]["vram_gb"] == 6.0        # curated figures kept
    assert by_name["mystery:latest"]["installed"] is True
    assert by_name["mystery:latest"]["tags"] == ["installed"]
    assert sum(1 for m in r.json()["models"] if m["name"] == "qwen2.5:7b") == 1  # no duplicate


@pytest.mark.asyncio
async def test_recommend_endpoint_ollama_down_catalog_only(respx_mock):
    _ollama_down(respx_mock)
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)):
        r = await _get("/api/models/recommend")
    assert r.status_code == 200
    models = r.json()["models"]
    assert models
    assert all(m["installed"] is False for m in models)


@pytest.mark.asyncio
async def test_recommend_endpoint_installed_filter(respx_mock):
    respx_mock.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [
            {"name": "mystery:latest", "size": 5_000_000_000},
        ]})
    )
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)):
        r = await _get("/api/models/recommend?want=installed")
    names = [m["name"] for m in r.json()["models"]]
    assert names == ["mystery:latest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"models": None},
    {"models": ["qwen2.5:7b"]},
    {"models": {"a": 1}},
])
async def test_recommend_malformed_payload(respx_mock, payload):
    respx_mock.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)):
        r = await _get("/api/models/recommend")
    assert r.status_code == 200
    assert "models" in r.json()
    assert isinstance(r.json()["models"], list)
    assert len(r.json()["models"]) > 0
