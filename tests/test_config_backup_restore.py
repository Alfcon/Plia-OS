from __future__ import annotations

import json
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── Export (GET /api/config) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_returns_all_config_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config")
    assert r.status_code == 200
    cfg = r.json()
    assert "ollama_url" in cfg
    assert "ollama_model" in cfg
    assert "system_prompt" in cfg
    assert "tts_engine" in cfg
    assert "stt_model_size" in cfg


@pytest.mark.asyncio
async def test_export_does_not_expose_backup_field():
    """system_prompt_backup is internal — export should return it empty/absent in practice."""
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config")
    cfg = r.json()
    # It appears in the raw export but must be empty by default
    assert cfg.get("system_prompt_backup", "") == ""


# ── Import (POST /api/config) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_applies_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/config", json={"ollama_model": "import-test-model"})
        assert r.status_code == 200
        cfg = (await c.get("/api/config")).json()
    assert cfg["ollama_model"] == "import-test-model"


@pytest.mark.asyncio
async def test_import_rejects_invalid_literal():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/config", json={"tts_engine": "invalid_engine"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_import_blocks_system_prompt_backup():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/config", json={"system_prompt_backup": "injected"})
        assert r.status_code == 200
        cfg = (await c.get("/api/config")).json()
    assert cfg.get("system_prompt_backup", "") == ""


@pytest.mark.asyncio
async def test_import_rejects_unknown_keys():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/config", json={"totally_unknown_key": "value"})
    assert r.status_code == 422


# ── Round-trip backup/restore ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_round_trip_restore():
    """Export config, change a field, restore from backup, verify original value."""
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        # Capture original
        backup = (await c.get("/api/config")).json()
        original_model = backup["ollama_model"]

        # Change a field
        await c.post("/api/config", json={"ollama_model": "temp-model"})
        changed = (await c.get("/api/config")).json()
        assert changed["ollama_model"] == "temp-model"

        # Restore from backup (strip internal field as frontend does)
        restore_payload = {k: v for k, v in backup.items() if k != "system_prompt_backup"}
        r = await c.post("/api/config", json=restore_payload)
        assert r.status_code == 200

        restored = (await c.get("/api/config")).json()
    assert restored["ollama_model"] == original_model


@pytest.mark.asyncio
async def test_partial_import_only_touches_specified_fields():
    """Importing a subset of fields leaves unspecified fields unchanged."""
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        original_url = (await c.get("/api/config")).json()["ollama_url"]
        await c.post("/api/config", json={"ollama_model": "partial-test"})
        cfg = (await c.get("/api/config")).json()
    assert cfg["ollama_url"] == original_url
    assert cfg["ollama_model"] == "partial-test"
