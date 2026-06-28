from __future__ import annotations

import base64
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_encode_base64():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/encode/base64", json={"text": "hello world"})
    assert r.status_code == 200
    assert r.json()["result"] == base64.b64encode(b"hello world").decode()


@pytest.mark.asyncio
async def test_encode_base64url():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/encode/base64url", json={"text": "hello world"})
    assert r.status_code == 200
    assert r.json()["result"] == base64.urlsafe_b64encode(b"hello world").decode()


@pytest.mark.asyncio
async def test_encode_hex():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/encode/hex", json={"text": "hi"})
    assert r.status_code == 200
    assert r.json()["result"] == b"hi".hex()


@pytest.mark.asyncio
async def test_encode_unknown_scheme_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/encode/rot13", json={"text": "test"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_decode_base64():
    encoded = base64.b64encode(b"hello").decode()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/decode/base64", json={"text": encoded})
    assert r.status_code == 200
    assert r.json()["result"] == "hello"


@pytest.mark.asyncio
async def test_decode_hex():
    encoded = b"world".hex()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/decode/hex", json={"text": encoded})
    assert r.status_code == 200
    assert r.json()["result"] == "world"


@pytest.mark.asyncio
async def test_decode_invalid_base64_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/decode/base64", json={"text": "!!!not-valid-base64!!!"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_encode_empty_string():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/encode/base64", json={"text": ""})
    assert r.status_code == 200
    assert r.json()["result"] == ""
