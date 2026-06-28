from __future__ import annotations

import hashlib
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_hash_returns_all_algorithms():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": "hello"})
    assert r.status_code == 200
    d = r.json()
    for alg in ("md5", "sha1", "sha256", "sha512"):
        assert alg in d


@pytest.mark.asyncio
async def test_hash_md5_correct():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": "hello"})
    assert r.json()["md5"] == hashlib.md5(b"hello").hexdigest()


@pytest.mark.asyncio
async def test_hash_sha256_correct():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": "test input"})
    assert r.json()["sha256"] == hashlib.sha256(b"test input").hexdigest()


@pytest.mark.asyncio
async def test_hash_sha512_correct():
    text = "another test"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": text})
    assert r.json()["sha512"] == hashlib.sha512(text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_hash_empty_string():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": ""})
    assert r.status_code == 200
    assert r.json()["md5"] == hashlib.md5(b"").hexdigest()
    assert r.json()["length"] == 0


@pytest.mark.asyncio
async def test_hash_length_field():
    text = "abc"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": text})
    assert r.json()["length"] == len(text.encode())


@pytest.mark.asyncio
async def test_hash_unicode_text():
    text = "héllo wörld"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/hash", json={"text": text})
    assert r.status_code == 200
    assert r.json()["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
