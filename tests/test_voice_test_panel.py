from __future__ import annotations

import struct
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
import numpy as np


def _make_app():
    from core.main import create_app
    return create_app()


def _float32_bytes(n_samples: int = 16000) -> bytes:
    """1 second of silence at 16kHz as float32 bytes."""
    return np.zeros(n_samples, dtype=np.float32).tobytes()


@pytest.fixture
def app():
    return _make_app()


# ── Upgraded transcribe response fields ───────────────────────────────────────

@pytest.mark.asyncio
async def test_transcribe_returns_latency_ms(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "hello"
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/voice/transcribe",
                content=_float32_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.status_code == 200
    data = r.json()
    assert "latency_ms" in data
    assert isinstance(data["latency_ms"], int)
    assert data["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_transcribe_returns_audio_duration(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "test"
    n_samples = 32000  # 2 seconds at 16kHz
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/voice/transcribe",
                content=np.zeros(n_samples, dtype=np.float32).tobytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    data = r.json()
    assert "audio_duration_s" in data
    assert abs(data["audio_duration_s"] - 2.0) < 0.01


@pytest.mark.asyncio
async def test_transcribe_returns_sample_rate(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = ""
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/voice/transcribe",
                content=_float32_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.json()["sample_rate"] == 16000


@pytest.mark.asyncio
async def test_transcribe_empty_body_returns_zeros(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/voice/transcribe",
            content=b"",
            headers={"Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == ""
    assert data["latency_ms"] == 0
    assert data["audio_duration_s"] == 0.0


@pytest.mark.asyncio
async def test_transcribe_text_still_returned(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "Paris is the capital."
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/voice/transcribe",
                content=_float32_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.json()["text"] == "Paris is the capital."


@pytest.mark.asyncio
async def test_transcribe_rtf_computable(app):
    """latency_ms and audio_duration_s are both present so RTF = latency_s / audio_duration_s."""
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "ok"
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/voice/transcribe",
                content=_float32_bytes(16000),  # 1s of audio
                headers={"Content-Type": "application/octet-stream"},
            )
    data = r.json()
    assert data["audio_duration_s"] > 0
    rtf = (data["latency_ms"] / 1000) / data["audio_duration_s"]
    assert rtf >= 0  # always non-negative
