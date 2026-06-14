import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_transcribe_returns_text(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "hello world"
    audio = np.zeros(16000, dtype=np.float32)
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/voice/transcribe",
                content=audio.tobytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.status_code == 200
    assert r.json()["text"] == "hello world"
    mock_stt.transcribe.assert_called_once()
    called_audio = mock_stt.transcribe.call_args[0][0]
    assert isinstance(called_audio, np.ndarray)
    assert called_audio.dtype == np.float32
    assert len(called_audio) == 16000


@pytest.mark.asyncio
async def test_transcribe_empty_body_returns_empty_text(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/api/voice/transcribe",
            content=b"",
            headers={"Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    assert r.json()["text"] == ""


@pytest.mark.asyncio
async def test_transcribe_empty_transcript_returns_empty(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = ""
    audio = np.zeros(8000, dtype=np.float32)
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/voice/transcribe",
                content=audio.tobytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.status_code == 200
    assert r.json()["text"] == ""
