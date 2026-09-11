import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from voice.tts import TTSService
from voice.vram_broker import get_vram_broker
import voice.vram_broker as broker_module
from core.config import reset_config, update_config, get_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


@pytest.fixture(autouse=True)
def reset_broker():
    broker_module._broker = None
    yield
    broker_module._broker = None


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


def test_chatterbox_on_demand_load():
    import torch
    fake_audio = np.zeros(24000, dtype=np.float32)
    fake_wav = torch.zeros(1, 24000)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])
    mock_cb = MagicMock()
    mock_cb.generate.return_value = fake_wav

    with patch("voice.tts.KPipeline", return_value=mock_kokoro), \
         patch("voice.tts.ChatterboxTTS") as MockCB:
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()  # loads kokoro (default engine)
        update_config(tts_engine="chatterbox")
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
    MockCB.from_pretrained.assert_called_once()
    mock_cb.generate.assert_called_once()


def test_dramabox_fallback_to_kokoro_on_error():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])
    mock_db = MagicMock()
    mock_db.synthesise.side_effect = RuntimeError("OOM")

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS") as MockDB, \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        MockDB.return_value = mock_db
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)


def test_chatterbox_load_failure_reverts_engine_to_kokoro():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])

    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        MockCB.from_pretrained.side_effect = RuntimeError("CUDA init failed")
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
    assert get_config().tts_engine == "kokoro"


def test_chatterbox_unload_clears_instance():
    import torch
    fake_wav = torch.zeros(1, 24000)
    mock_cb = MagicMock()
    mock_cb.generate.return_value = fake_wav

    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB:
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        assert svc._chatterbox is not None

        get_vram_broker().release("chatterbox")
        assert svc._chatterbox is None
