from __future__ import annotations

import json
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _preset_store(tmp_path):
    import core.preset_store as ps
    ps._PRESETS_FILE = tmp_path / "presets.json"
    return ps


@pytest.mark.asyncio
async def test_list_presets_empty(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/config/presets")
        assert r.status_code == 200
        assert r.json()["presets"] == []
    finally:
        ps._PRESETS_FILE = original


@pytest.mark.asyncio
async def test_save_preset(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/config/presets/mypreset")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["name"] == "mypreset"
    finally:
        ps._PRESETS_FILE = original


@pytest.mark.asyncio
async def test_save_and_list_preset(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/config/presets/alpha")
            await c.post("/api/config/presets/beta")
            r = await c.get("/api/config/presets")
        names = r.json()["presets"]
        assert "alpha" in names
        assert "beta" in names
    finally:
        ps._PRESETS_FILE = original


@pytest.mark.asyncio
async def test_delete_preset(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/config/presets/todelete")
            r = await c.delete("/api/config/presets/todelete")
        assert r.status_code == 200
        assert r.json()["ok"] is True
    finally:
        ps._PRESETS_FILE = original


@pytest.mark.asyncio
async def test_delete_missing_preset_404(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/config/presets/nonexistent")
        assert r.status_code == 404
    finally:
        ps._PRESETS_FILE = original


@pytest.mark.asyncio
async def test_apply_preset(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/config/presets/snap")
            r = await c.post("/api/config/presets/snap/apply")
        assert r.status_code == 200
        assert r.json()["ok"] is True
    finally:
        ps._PRESETS_FILE = original


@pytest.mark.asyncio
async def test_apply_missing_preset_404(tmp_path):
    import core.preset_store as ps
    original = ps._PRESETS_FILE
    ps._PRESETS_FILE = tmp_path / "presets.json"
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/config/presets/ghost/apply")
        assert r.status_code == 404
    finally:
        ps._PRESETS_FILE = original
