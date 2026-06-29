from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_basic_cidr():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "192.168.1.0/24"})
    assert r.status_code == 200
    d = r.json()
    assert d["network"] == "192.168.1.0"
    assert d["broadcast"] == "192.168.1.255"
    assert d["prefix"] == 24


@pytest.mark.asyncio
async def test_usable_hosts_24():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "10.0.0.0/24"})
    d = r.json()
    assert d["usable_hosts"] == 254
    assert d["total_addresses"] == 256


@pytest.mark.asyncio
async def test_mask_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "172.16.0.0/16"})
    assert r.json()["mask"] == "255.255.0.0"


@pytest.mark.asyncio
async def test_private_flag():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "10.0.0.0/8"})
    assert r.json()["is_private"] is True


@pytest.mark.asyncio
async def test_loopback():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "127.0.0.0/8"})
    assert r.json()["is_loopback"] is True


@pytest.mark.asyncio
async def test_single_host_accepts_strict_false():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "192.168.1.5/24"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_invalid_value_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={"value": "notanip"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_value_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ip/calc", json={})
    assert r.status_code == 422
