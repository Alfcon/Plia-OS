"""Endpoint tests for GET /api/hf/quants (respx-mocked Hugging Face API)."""

from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from core.main import create_app

HF = "https://huggingface.co/api/models"
GGUF_TREE = [
    {"path": "m.Q4_K_M.gguf", "size": 2_500_000_000},
    {"path": "m.Q8_0.gguf", "size": 4_300_000_000},
]
NO_GGUF_TREE = [
    {"path": "config.json", "size": 700},
    {"path": "model-00001-of-00002.safetensors", "size": 4_000_000_000},
]


def _client():
    return AsyncClient(transport=ASGITransport(app=create_app()),
                       base_url="http://test")


def _hw(vram=24.0, ram=64.0):
    return patch("core.model_catalog.current_hardware",
                 return_value=(vram, ram))


@pytest.mark.asyncio
async def test_direct_gguf_repo(respx_mock):
    respx_mock.get(f"{HF}/u/repo-GGUF/tree/main").mock(
        return_value=httpx.Response(200, json=GGUF_TREE))
    with _hw():
        async with _client() as c:
            r = await c.get("/api/hf/quants",
                            params={"repo": "https://huggingface.co/u/repo-GGUF"})
    assert r.status_code == 200
    body = r.json()
    assert body["repo"] == "u/repo-GGUF"
    assert body["source_repo"] == "u/repo-GGUF"
    assert body["alternatives"] == []
    assert [q["quant"] for q in body["quants"]] == ["Q4_K_M", "Q8_0"]
    assert body["quants"][0]["fit"] == "gpu"


@pytest.mark.asyncio
async def test_fallback_to_quantized_conversion(respx_mock):
    respx_mock.get(f"{HF}/Qwen/Base/tree/main").mock(
        return_value=httpx.Response(200, json=NO_GGUF_TREE))
    respx_mock.get(
        HF,
        params__contains={"filter": "base_model:quantized:Qwen/Base,gguf",
                          "sort": "downloads"},
    ).mock(return_value=httpx.Response(200, json=[
        {"id": "Qwen/Base-GGUF", "downloads": 900},
        {"id": "unsloth/Base-GGUF", "downloads": 500},
    ]))
    respx_mock.get(f"{HF}/Qwen/Base-GGUF/tree/main").mock(
        return_value=httpx.Response(200, json=GGUF_TREE))
    with _hw():
        async with _client() as c:
            r = await c.get("/api/hf/quants", params={"repo": "Qwen/Base"})
    assert r.status_code == 200
    body = r.json()
    assert body["repo"] == "Qwen/Base"
    assert body["source_repo"] == "Qwen/Base-GGUF"
    assert body["alternatives"] == ["unsloth/Base-GGUF"]
    assert len(body["quants"]) == 2


@pytest.mark.asyncio
async def test_no_gguf_anywhere(respx_mock):
    respx_mock.get(f"{HF}/Qwen/Base/tree/main").mock(
        return_value=httpx.Response(200, json=NO_GGUF_TREE))
    respx_mock.get(HF).mock(return_value=httpx.Response(200, json=[]))
    with _hw():
        async with _client() as c:
            r = await c.get("/api/hf/quants", params={"repo": "Qwen/Base"})
    assert r.status_code == 200
    body = r.json()
    assert body["quants"] == [] and body["alternatives"] == []
    assert body["source_repo"] == "Qwen/Base"


@pytest.mark.asyncio
@pytest.mark.parametrize("hf_status,expected", [(401, 403), (403, 403), (404, 404)])
async def test_gated_and_missing_repos(respx_mock, hf_status, expected):
    respx_mock.get(f"{HF}/u/r/tree/main").mock(
        return_value=httpx.Response(hf_status, json={"error": "x"}))
    async with _client() as c:
        r = await c.get("/api/hf/quants", params={"repo": "u/r"})
    assert r.status_code == expected


@pytest.mark.asyncio
async def test_hf_unreachable(respx_mock):
    respx_mock.get(f"{HF}/u/r/tree/main").mock(
        side_effect=httpx.ConnectError("boom"))
    async with _client() as c:
        r = await c.get("/api/hf/quants", params={"repo": "u/r"})
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_hf_rate_limited(respx_mock):
    respx_mock.get(f"{HF}/u/r/tree/main").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"}))
    async with _client() as c:
        r = await c.get("/api/hf/quants", params={"repo": "u/r"})
    assert r.status_code == 502
    assert "rate limited" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bad_repo_param():
    async with _client() as c:
        r = await c.get("/api/hf/quants", params={"repo": "llama3.2:3b"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_malformed_tree_payload_falls_back(respx_mock):
    # dict instead of list → treated as "no GGUFs" → fallback search runs
    respx_mock.get(f"{HF}/u/r/tree/main").mock(
        return_value=httpx.Response(200, json={"unexpected": True}))
    respx_mock.get(HF).mock(return_value=httpx.Response(200, json=[]))
    with _hw():
        async with _client() as c:
            r = await c.get("/api/hf/quants", params={"repo": "u/r"})
    assert r.status_code == 200
    assert r.json()["quants"] == []
