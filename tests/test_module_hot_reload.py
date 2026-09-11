from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
import pathlib


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_reload_single_not_found_404():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/reload/nonexistent_module_xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reload_single_found_ok(tmp_path):
    mod_file = tmp_path / "mymod.py"
    mod_file.write_text("# empty module\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/modules/reload/mymod")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["name"] == "mymod"


@pytest.mark.asyncio
async def test_reload_single_returns_tools(tmp_path):
    mod_file = tmp_path / "tmod.py"
    mod_file.write_text("# empty module\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/modules/reload/tmod")
    assert "tools" in r.json()
    assert isinstance(r.json()["tools"], list)


@pytest.mark.asyncio
async def test_reload_single_does_not_affect_other_modules(tmp_path):
    mod_file = tmp_path / "isolated.py"
    mod_file.write_text("# no tools\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r1 = await c.post("/api/modules/reload/isolated")
            r2 = await c.get("/api/modules")
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_reload_all_still_works():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/reload")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_benchmark_chart_endpoint():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/benchmark/chart")
    assert r.status_code == 200
    d = r.json()
    assert "labels" in d
    assert "latency_ms" in d
    assert "tokens_per_sec" in d
    assert "models" in d
