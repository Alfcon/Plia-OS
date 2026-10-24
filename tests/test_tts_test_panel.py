from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_tts(n_samples: int = 24000):
    svc = MagicMock()
    svc.synthesise.return_value = np.zeros(n_samples, dtype=np.float32)
    return svc


# ── POST /api/tts/synthesize ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synthesize_returns_wav():
    with patch("voice.tts.get_tts_service", return_value=_mock_tts()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "Hello world."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"  # WAV magic bytes


@pytest.mark.asyncio
async def test_synthesize_returns_latency_header():
    with patch("voice.tts.get_tts_service", return_value=_mock_tts()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "Test."})
    assert "x-latency-ms" in r.headers
    assert int(r.headers["x-latency-ms"]) >= 0


@pytest.mark.asyncio
async def test_synthesize_returns_audio_duration_header():
    n_samples = 48000  # 2s at 24kHz
    with patch("voice.tts.get_tts_service", return_value=_mock_tts(n_samples)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "Two seconds."})
    dur = float(r.headers["x-audio-duration-s"])
    assert abs(dur - 2.0) < 0.01


@pytest.mark.asyncio
async def test_synthesize_missing_text_422():
    with patch("voice.tts.get_tts_service", return_value=_mock_tts()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_empty_text_422():
    with patch("voice.tts.get_tts_service", return_value=_mock_tts()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "   "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_tts_not_loaded_503():
    with patch("voice.tts.get_tts_service", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "Hello."})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_synthesize_engine_error_500():
    svc = MagicMock()
    svc.synthesise.side_effect = RuntimeError("engine crashed")
    with patch("voice.tts.get_tts_service", return_value=svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "Crash test."})
    assert r.status_code == 500
    assert "engine crashed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_synthesize_calls_service_with_text():
    svc = _mock_tts()
    with patch("voice.tts.get_tts_service", return_value=svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/tts/synthesize", json={"text": "Check me."})
    svc.synthesise.assert_called_once_with("Check me.")


@pytest.mark.asyncio
async def test_synthesize_wav_is_valid_size():
    n_samples = 24000
    with patch("voice.tts.get_tts_service", return_value=_mock_tts(n_samples)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tts/synthesize", json={"text": "Size check."})
    # WAV header (44 bytes) + float32 samples (4 bytes each)
    expected_min = 44 + n_samples * 4
    assert len(r.content) >= expected_min
