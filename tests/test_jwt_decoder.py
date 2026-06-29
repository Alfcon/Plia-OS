from __future__ import annotations

import base64
import json
import time
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _make_token(header: dict, payload: dict, sig: str = "sig") -> str:
    def _enc(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{_enc(header)}.{_enc(payload)}.{sig}"


_TOKEN = _make_token({"alg": "HS256", "typ": "JWT"}, {"sub": "1234", "name": "Alice", "iat": 1000000})


@pytest.mark.asyncio
async def test_decode_returns_header_and_payload():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": _TOKEN})
    assert r.status_code == 200
    d = r.json()
    assert d["header"]["alg"] == "HS256"
    assert d["payload"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_decode_signature_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": _TOKEN})
    assert r.json()["signature"] == "sig"


@pytest.mark.asyncio
async def test_expired_token():
    token = _make_token({"alg": "HS256"}, {"exp": int(time.time()) - 3600})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": token})
    assert r.status_code == 200
    assert r.json()["expired"] is True


@pytest.mark.asyncio
async def test_valid_exp():
    token = _make_token({"alg": "HS256"}, {"exp": int(time.time()) + 3600})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": token})
    d = r.json()
    assert d["expired"] is False
    assert d["seconds_until_exp"] > 0


@pytest.mark.asyncio
async def test_missing_token_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_parts_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": "not.a.jwt.with.five.parts"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_iat_iso_field():
    token = _make_token({"alg": "HS256"}, {"iat": 1000000})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": token})
    assert r.json()["iat_iso"] is not None


@pytest.mark.asyncio
async def test_exp_zero_is_expired():
    token = _make_token({"alg": "HS256"}, {"exp": 0})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": token})
    assert r.status_code == 200
    assert r.json()["expired"] is True


@pytest.mark.asyncio
async def test_array_payload_422():
    # payload segment that decodes to a JSON array, not a dict
    arr_payload = base64.urlsafe_b64encode(b"[1,2,3]").rstrip(b"=").decode()
    token = f"eyJhbGciOiJIUzI1NiJ9.{arr_payload}.sig"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/jwt/decode", json={"token": token})
    assert r.status_code == 422
