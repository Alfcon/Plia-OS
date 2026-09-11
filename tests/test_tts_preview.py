from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_tts(text=""):
    svc = MagicMock()
    svc.synthesise.return_value = np.zeros(24000, dtype=np.int16)
    return svc


@pytest.mark.asyncio
async def test_preview_returns_wav():
    with patch("voice.tts.get_tts_service", return_value=_mock_tts()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/preview", json={"text": "hello"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


@pytest.mark.asyncio
async def test_preview_has_latency_header():
    with patch("voice.tts.get_tts_service", return_value=_mock_tts()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/preview", json={"text": "hello"})
    assert "X-Latency-Ms" in r.headers


@pytest.mark.asyncio
async def test_preview_no_tts_503():
    with patch("voice.tts.get_tts_service", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/preview", json={"text": "hello"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_preview_uses_default_text():
    captured = {}
    svc = MagicMock()
    def _synth(text):
        captured["text"] = text
        return np.zeros(24000, dtype=np.int16)
    svc.synthesise.side_effect = _synth
    with patch("voice.tts.get_tts_service", return_value=svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/tts/preview", json={})
    assert captured["text"] == "Hello, I am Plia."


@pytest.mark.asyncio
async def test_preview_truncates_long_text():
    long_text = "x" * 500
    captured = {}
    svc = MagicMock()
    def _synth(text):
        captured["text"] = text
        return np.zeros(24000, dtype=np.int16)
    svc.synthesise.side_effect = _synth
    with patch("voice.tts.get_tts_service", return_value=svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/tts/preview", json={"text": long_text})
    assert len(captured["text"]) <= 200


@pytest.mark.asyncio
async def test_preview_tts_error_500():
    svc = MagicMock()
    svc.synthesise.side_effect = RuntimeError("synthesis failed")
    with patch("voice.tts.get_tts_service", return_value=svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/preview", json={"text": "hello"})
    assert r.status_code == 500
