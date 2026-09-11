from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _make_audio_bytes(seconds: float = 1.0) -> bytes:
    samples = np.zeros(int(16000 * seconds), dtype=np.float32)
    return samples.tobytes()


@pytest.mark.asyncio
async def test_detect_language_no_body_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/voice/detect-language", content=b"")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_detect_language_model_not_loaded_503():
    mock_svc = MagicMock()
    mock_svc._model = None
    with patch("voice.stt.get_stt_service", return_value=mock_svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/voice/detect-language", content=_make_audio_bytes(),
                             headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_detect_language_returns_language_string():
    mock_model = MagicMock()
    mock_model.detect_language.return_value = ("en", 0.98)
    mock_svc = MagicMock()
    mock_svc._model = mock_model
    with patch("voice.stt.get_stt_service", return_value=mock_svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/voice/detect-language", content=_make_audio_bytes(),
                             headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    d = r.json()
    assert d["language"] == "en"


@pytest.mark.asyncio
async def test_detect_language_returns_probability():
    mock_model = MagicMock()
    mock_model.detect_language.return_value = ("fr", 0.87)
    mock_svc = MagicMock()
    mock_svc._model = mock_model
    with patch("voice.stt.get_stt_service", return_value=mock_svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/voice/detect-language", content=_make_audio_bytes(),
                             headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    d = r.json()
    assert d["probability"] == pytest.approx(0.87, abs=0.001)


@pytest.mark.asyncio
async def test_detect_language_has_latency_ms():
    mock_model = MagicMock()
    mock_model.detect_language.return_value = ("de", 0.92)
    mock_svc = MagicMock()
    mock_svc._model = mock_model
    with patch("voice.stt.get_stt_service", return_value=mock_svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/voice/detect-language", content=_make_audio_bytes(),
                             headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    assert "latency_ms" in r.json()


@pytest.mark.asyncio
async def test_detect_language_prob_dict_format():
    # faster-whisper can return (lang, dict[lang->prob])
    mock_model = MagicMock()
    mock_model.detect_language.return_value = ("es", {"es": 0.75, "pt": 0.2})
    mock_svc = MagicMock()
    mock_svc._model = mock_model
    with patch("voice.stt.get_stt_service", return_value=mock_svc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/voice/detect-language", content=_make_audio_bytes(),
                             headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    d = r.json()
    assert d["language"] == "es"
    assert d["probability"] == pytest.approx(0.75, abs=0.001)
