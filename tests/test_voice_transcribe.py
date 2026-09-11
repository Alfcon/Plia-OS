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


def test_transcribe_passes_vad_args():
    """Whisper hallucinates stock phrases on non-speech.

    A false wake on ambient noise produced 2.24s of rms=0.077 audio that
    faster-whisper transcribed as "Yes." — a phrase the user never said, which
    reached the LLM as a real turn. vad_filter runs Silero VAD so Whisper never
    sees non-speech; condition_on_previous_text=True (the default) lets earlier
    text seed the next decode, a known hallucination amplifier.
    """
    from voice.stt import STTService

    svc = STTService()
    svc._model = MagicMock()
    svc._model.transcribe.return_value = ([], None)

    svc.transcribe(np.zeros(16000, dtype=np.float32))

    kwargs = svc._model.transcribe.call_args.kwargs
    assert kwargs["vad_filter"] is True
    assert kwargs["condition_on_previous_text"] is False


def test_transcribe_file_keeps_whisper_defaults():
    """transcribe_file must NOT get the anti-hallucination settings.

    Its production callers are video/audio summarization
    (agents/video_summarize.py) — not /api/voice/transcribe, which calls
    transcribe(). For long-form media, vad_filter can drop quiet dialog under
    background music and condition_on_previous_text=False hurts decode
    coherence, so Whisper defaults are kept deliberately.
    """
    from voice.stt import STTService

    svc = STTService()
    svc._model = MagicMock()
    svc._model.transcribe.return_value = ([], None)

    svc.transcribe_file("/tmp/whatever.wav")

    kwargs = svc._model.transcribe.call_args.kwargs
    assert "vad_filter" not in kwargs
    assert "condition_on_previous_text" not in kwargs


def test_transcribe_still_honours_language():
    # The VAD args must not displace the existing language handling.
    from core.config import update_config
    from voice.stt import STTService

    update_config(stt_language="en")
    svc = STTService()
    svc._model = MagicMock()
    svc._model.transcribe.return_value = ([], None)

    svc.transcribe(np.zeros(16000, dtype=np.float32))
    assert svc._model.transcribe.call_args.kwargs["language"] == "en"


def test_transcribe_auto_language_still_passes_none():
    from core.config import update_config
    from voice.stt import STTService

    update_config(stt_language="auto")
    svc = STTService()
    svc._model = MagicMock()
    svc._model.transcribe.return_value = ([], None)

    svc.transcribe(np.zeros(16000, dtype=np.float32))
    assert svc._model.transcribe.call_args.kwargs["language"] is None
