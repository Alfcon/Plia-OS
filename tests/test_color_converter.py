from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_hex_conversion():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "#ff6600"})
    assert r.status_code == 200
    d = r.json()
    assert d["hex"] == "#ff6600"
    assert d["hex_upper"] == "#FF6600"
    assert "rgb" in d
    assert "hsl" in d


@pytest.mark.asyncio
async def test_shorthand_hex():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "#f60"})
    assert r.status_code == 200
    assert r.json()["rgb_values"] == [255, 102, 0]


@pytest.mark.asyncio
async def test_rgb_input():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "rgb(255, 102, 0)"})
    assert r.status_code == 200
    assert r.json()["hex"] == "#ff6600"


@pytest.mark.asyncio
async def test_hsl_input():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "hsl(0, 100%, 50%)"})
    assert r.status_code == 200
    d = r.json()
    assert d["rgb_values"][0] == 255
    assert d["rgb_values"][1] == 0


@pytest.mark.asyncio
async def test_luminance_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "#ffffff"})
    assert r.status_code == 200
    assert r.json()["luminance"] == 1.0


@pytest.mark.asyncio
async def test_invalid_value_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "notacolor"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_value_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_rgba_rejected_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "rgba(255, 0, 0, 0.5)"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_hsla_rejected_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/color", json={"value": "hsla(0, 100%, 50%, 0.5)"})
    assert r.status_code == 422
