import pytest
from core.config import reset_config, update_config, get_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def test_dramabox_config_fields_accepted():
    update_config(
        tts_engine="dramabox",
        dramabox_voice_ref="/tmp/ref.wav",
        dramabox_cfg_scale=3.0,
        dramabox_stg_scale=2.0,
        dramabox_seed=123,
        dramabox_duration_multiplier=1.2,
    )
    cfg = get_config()
    assert cfg.tts_engine == "dramabox"
    assert cfg.dramabox_voice_ref == "/tmp/ref.wav"
    assert cfg.dramabox_cfg_scale == 3.0
    assert cfg.dramabox_stg_scale == 2.0
    assert cfg.dramabox_seed == 123
    assert cfg.dramabox_duration_multiplier == 1.2


def test_dramabox_config_defaults():
    cfg = get_config()
    assert cfg.dramabox_voice_ref is None
    assert cfg.dramabox_cfg_scale == 2.5
    assert cfg.dramabox_stg_scale == 1.5
    assert cfg.dramabox_seed == 42
    assert cfg.dramabox_duration_multiplier == 1.1


def test_unknown_config_key_raises():
    with pytest.raises(ValueError, match="Unknown config key"):
        update_config(dramabox_nonexistent="x")


import torch
import numpy as np
from unittest.mock import MagicMock, patch


def _make_mock_server():
    """Mock TTSServer: synthesise returns (1-ch float32 tensor at 48kHz, 48000)."""
    mock = MagicMock()
    mock.generate.return_value = (torch.zeros(1, 48000), 48000)
    mock.generate_to_file.return_value = "/tmp/out.wav"
    return mock


def test_dramabox_wrapper_synthesise_returns_tensor_and_sr():
    from voice.dramabox.wrapper import DramaboxTTS
    mock_server = _make_mock_server()
    db = DramaboxTTS()
    db._server = mock_server

    update_config(dramabox_voice_ref=None, dramabox_cfg_scale=2.5,
                  dramabox_stg_scale=1.5, dramabox_seed=42,
                  dramabox_duration_multiplier=1.1)
    waveform, sr = db.synthesise("hello")

    assert isinstance(waveform, torch.Tensor)
    assert sr == 48000
    mock_server.generate.assert_called_once_with(
        prompt="hello",
        voice_ref=None,
        cfg_scale=2.5,
        stg_scale=1.5,
        seed=42,
        duration_multiplier=1.1,
    )


def test_dramabox_wrapper_generate_to_file_calls_server():
    from voice.dramabox.wrapper import DramaboxTTS
    mock_server = _make_mock_server()
    db = DramaboxTTS()
    db._server = mock_server

    update_config(dramabox_voice_ref="/ref.wav", dramabox_cfg_scale=2.5,
                  dramabox_stg_scale=1.5, dramabox_seed=42,
                  dramabox_duration_multiplier=1.1)
    result = db.generate_to_file("hello", "/tmp/out.wav")

    assert result == "/tmp/out.wav"
    mock_server.generate_to_file.assert_called_once_with(
        prompt="hello",
        output="/tmp/out.wav",
        voice_ref="/ref.wav",
        cfg_scale=2.5,
        stg_scale=1.5,
        seed=42,
        duration_multiplier=1.1,
        watermark=True,
        progress_callback=None,
    )


import voice.tts as tts_module
from voice.tts import TTSService


@pytest.fixture(autouse=True)
def reset_tts_singleton():
    original = getattr(tts_module, '_service', None)
    if hasattr(tts_module, '_service'):
        tts_module._service = None
    yield
    if hasattr(tts_module, '_service'):
        tts_module._service = original


def test_dramabox_synthesise_resamples_to_24k():
    fake_wav = torch.zeros(1, 48000)  # 48 kHz, 1 channel
    mock_db = MagicMock()
    mock_db.synthesise.return_value = (fake_wav, 48000)

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS", return_value=mock_db):
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello dramabox")

    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    assert result.shape == (24000,)   # 48000 downsampled to 24000


def test_dramabox_load_failure_falls_back_to_kokoro():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS") as MockDB, \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        MockDB.return_value.load.side_effect = RuntimeError("CUDA OOM")
        svc = TTSService()
        svc.load()

    assert get_config().tts_engine == "kokoro"


def test_get_tts_service_returns_none_before_load():
    from voice.tts import get_tts_service
    assert get_tts_service() is None


def test_get_tts_service_returns_instance_after_load():
    from voice.tts import get_tts_service
    with patch("voice.tts.KPipeline"):
        svc = TTSService()
        svc.load()
    assert get_tts_service() is svc


def test_dramabox_synthesis_fallback_to_kokoro_on_error():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])

    mock_db = MagicMock()
    mock_db.synthesise.side_effect = RuntimeError("inference failed")

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS", return_value=mock_db), \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
