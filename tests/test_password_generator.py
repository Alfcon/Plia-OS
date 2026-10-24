from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_password_default_params():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={})
    assert r.status_code == 200
    d = r.json()
    assert "passwords" in d
    assert len(d["passwords"]) == 1
    assert len(d["passwords"][0]) == 16


@pytest.mark.asyncio
async def test_password_custom_length():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={"length": 32, "count": 3})
    assert r.status_code == 200
    d = r.json()
    assert len(d["passwords"]) == 3
    assert all(len(p) == 32 for p in d["passwords"])


@pytest.mark.asyncio
async def test_password_length_capped():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={"length": 9999})
    assert r.status_code == 200
    assert len(r.json()["passwords"][0]) == 128


@pytest.mark.asyncio
async def test_password_count_capped():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={"count": 999})
    assert r.status_code == 200
    assert len(r.json()["passwords"]) == 20


@pytest.mark.asyncio
async def test_password_digits_only():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={
            "upper": False, "lower": False, "digits": True, "symbols": False, "length": 20,
        })
    assert r.status_code == 200
    assert all(c.isdigit() for c in r.json()["passwords"][0])


@pytest.mark.asyncio
async def test_password_no_charset_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={
            "upper": False, "lower": False, "digits": False, "symbols": False,
        })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_password_entropy_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/password", json={})
    assert r.status_code == 200
    d = r.json()
    assert "entropy_bits" in d
    assert d["entropy_bits"] > 0
    assert "charset_size" in d
