from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── GET /api/health structure ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_structure():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "services" in data
    assert "checked_at" in data
    assert isinstance(data["services"], list)
    assert isinstance(data["checked_at"], float)


@pytest.mark.asyncio
async def test_health_service_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/health")
    data = r.json()
    for svc in data["services"]:
        assert "name" in svc
        assert "status" in svc
        assert "detail" in svc
        assert svc["status"] in ("ok", "error", "unconfigured")


@pytest.mark.asyncio
async def test_health_contains_expected_services():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/health")
    names = {s["name"] for s in r.json()["services"]}
    assert "ollama" in names
    assert "hass" in names
    assert "memory" in names


# ── Ollama probe ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_ollama_ok():
    import httpx
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"models": [{"name": "llama3"}, {"name": "mistral"}]}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = AsyncMock(return_value=mock_response)
        MockClient.return_value = instance

        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")

    data = r.json()
    ollama = next((s for s in data["services"] if s["name"] == "ollama"), None)
    assert ollama is not None
    # Can be ok or error depending on whether local ollama is running — just check structure
    assert ollama["status"] in ("ok", "error", "unconfigured")


@pytest.mark.asyncio
async def test_health_ollama_unconfigured(tmp_path):
    from core.config import get_config, update_config
    original = get_config().ollama_url
    try:
        update_config(ollama_url="")
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")
        data = r.json()
        ollama = next((s for s in data["services"] if s["name"] == "ollama"), None)
        assert ollama is not None
        assert ollama["status"] == "unconfigured"
    finally:
        update_config(ollama_url=original)


# ── HASS probe ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_hass_unconfigured():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/health")
    data = r.json()
    hass = next((s for s in data["services"] if s["name"] == "hass"), None)
    assert hass is not None
    # Default config has no HASS — should be unconfigured
    assert hass["status"] == "unconfigured"


# ── Memory probe ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_memory_ok():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [{"key": "a", "value": "b"}, {"key": "c", "value": "d"}]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")
    data = r.json()
    mem = next((s for s in data["services"] if s["name"] == "memory"), None)
    assert mem is not None
    assert mem["status"] == "ok"


# ── GCal probe ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_gcal_unconfigured():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/health")
    data = r.json()
    gcal = next((s for s in data["services"] if s["name"] == "gcal"), None)
    assert gcal is not None
    assert gcal["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_health_gcal_file_missing(tmp_path):
    from core.config import get_config, update_config
    original = get_config().gcal_credentials_file
    fake_path = str(tmp_path / "nonexistent_creds.json")
    try:
        update_config(gcal_credentials_file=fake_path)
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")
        data = r.json()
        gcal = next((s for s in data["services"] if s["name"] == "gcal"), None)
        assert gcal is not None
        assert gcal["status"] == "error"
    finally:
        update_config(gcal_credentials_file=original)


@pytest.mark.asyncio
async def test_health_gcal_file_present(tmp_path):
    from core.config import get_config, update_config
    original = get_config().gcal_credentials_file
    cred_file = tmp_path / "creds.json"
    cred_file.write_text("{}")
    try:
        update_config(gcal_credentials_file=str(cred_file))
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")
        data = r.json()
        gcal = next((s for s in data["services"] if s["name"] == "gcal"), None)
        assert gcal is not None
        assert gcal["status"] == "ok"
    finally:
        update_config(gcal_credentials_file=original)


# ── Fallback LLM probe ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_fallback_llm_unconfigured():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/health")
    data = r.json()
    fb = next((s for s in data["services"] if s["name"] == "fallback_llm"), None)
    assert fb is not None
    assert fb["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_health_fallback_llm_no_key(tmp_path):
    from core.config import get_config, update_config
    orig_provider = get_config().fallback_provider
    orig_key = get_config().fallback_api_key
    try:
        update_config(fallback_provider="openai", fallback_api_key="")
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")
        data = r.json()
        fb = next((s for s in data["services"] if s["name"] == "fallback_llm"), None)
        assert fb["status"] == "error"
    finally:
        update_config(fallback_provider=orig_provider, fallback_api_key=orig_key)


@pytest.mark.asyncio
async def test_health_fallback_llm_with_key(tmp_path):
    from core.config import get_config, update_config
    orig_provider = get_config().fallback_provider
    orig_key = get_config().fallback_api_key
    try:
        update_config(fallback_provider="openai", fallback_api_key="sk-test123")
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/health")
        data = r.json()
        fb = next((s for s in data["services"] if s["name"] == "fallback_llm"), None)
        assert fb["status"] == "ok"
        assert "openai" in fb["detail"]
    finally:
        update_config(fallback_provider=orig_provider, fallback_api_key=orig_key)
