import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from voice.tts import TTSService
from core.config import reset_config, update_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def test_kokoro_synthesise_returns_array():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = iter([(None, None, fake_audio)])

    with patch("voice.tts.KPipeline", return_value=mock_pipeline):
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
    assert result.shape == (24000,)


def test_chatterbox_synthesise_returns_array():
    import torch
    fake_wav = torch.zeros(1, 24000)
    mock_model = MagicMock()
    mock_model.generate.return_value = fake_wav

    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB:
        MockCB.from_pretrained.return_value = mock_model
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
    mock_model.generate.assert_called_once()


def test_synthesise_before_load_raises():
    svc = TTSService()
    with pytest.raises(RuntimeError, match="load\\(\\)"):
        svc.synthesise("hi")


def test_chatterbox_fallback_to_kokoro_on_error():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])

    mock_cb = MagicMock()
    mock_cb.generate.side_effect = RuntimeError("GPU OOM")

    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
