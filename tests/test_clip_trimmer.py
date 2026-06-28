from __future__ import annotations

import io
import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from scipy.io import wavfile


def _make_app():
    from core.main import create_app
    return create_app()


def _make_wav_bytes(duration_s: float = 1.0, rate: int = 16000) -> bytes:
    samples = np.zeros(int(rate * duration_s), dtype=np.int16)
    buf = io.BytesIO()
    wavfile.write(buf, rate, samples)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_trim_invalid_filename_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/clips/../secret.wav/trim", json={"start_s": 0})
    assert r.status_code in (400, 404, 422)


@pytest.mark.asyncio
async def test_trim_not_found_404(tmp_path):
    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/nonexistent.wav/trim", json={"start_s": 0})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_trim_non_wav_400(tmp_path):
    p = tmp_path / "voice.mp3"
    p.write_bytes(b"fake mp3")
    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/voice.mp3/trim", json={"start_s": 0})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_trim_returns_wav(tmp_path):
    wav = _make_wav_bytes(2.0)
    p = tmp_path / "clip.wav"
    p.write_bytes(wav)
    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/clip.wav/trim", json={"start_s": 0.0, "end_s": 1.0})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


@pytest.mark.asyncio
async def test_trim_content_shorter(tmp_path):
    rate = 16000
    wav = _make_wav_bytes(2.0, rate)
    p = tmp_path / "clip.wav"
    p.write_bytes(wav)
    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/clip.wav/trim", json={"start_s": 0.0, "end_s": 1.0})
    result_rate, result_data = wavfile.read(io.BytesIO(r.content))
    assert len(result_data) == rate  # 1s of samples


@pytest.mark.asyncio
async def test_trim_invalid_range_400(tmp_path):
    wav = _make_wav_bytes(1.0)
    p = tmp_path / "clip.wav"
    p.write_bytes(wav)
    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/clip.wav/trim", json={"start_s": 5.0, "end_s": 6.0})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_trim_content_disposition(tmp_path):
    wav = _make_wav_bytes(1.0)
    p = tmp_path / "myvoice.wav"
    p.write_bytes(wav)
    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/myvoice.wav/trim", json={"start_s": 0.0})
    assert "trimmed" in r.headers.get("content-disposition", "")
