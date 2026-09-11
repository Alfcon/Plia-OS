# tests/test_chatterbox_params.py
import pytest
from core.config import reset_config, update_config, get_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def test_studio_pipeline_mode_default():
    assert get_config().studio_pipeline_mode == "cpu_stt"


def test_studio_pipeline_mode_accepted():
    update_config(studio_pipeline_mode="pause")
    assert get_config().studio_pipeline_mode == "pause"


def test_chatterbox_seed_default_is_none():
    assert get_config().chatterbox_seed is None


def test_chatterbox_temperature_default():
    assert get_config().chatterbox_temperature == 0.8


def test_chatterbox_cfg_weight_default():
    assert get_config().chatterbox_cfg_weight == 0.5


def test_chatterbox_new_fields_accepted():
    update_config(chatterbox_seed=42, chatterbox_temperature=1.2, chatterbox_cfg_weight=0.7)
    cfg = get_config()
    assert cfg.chatterbox_seed == 42
    assert cfg.chatterbox_temperature == 1.2
    assert cfg.chatterbox_cfg_weight == 0.7


def test_chatterbox_seed_accepts_none():
    update_config(chatterbox_seed=42)
    update_config(chatterbox_seed=None)
    assert get_config().chatterbox_seed is None


import random
import torch
import numpy as np
from unittest.mock import MagicMock, patch
import voice.tts as tts_module
from voice.tts import TTSService
import voice.vram_broker as broker_module


@pytest.fixture(autouse=True)
def reset_singletons():
    broker_module._broker = None
    original = getattr(tts_module, '_service', None)
    tts_module._service = None
    yield
    broker_module._broker = None
    tts_module._service = original


def _fake_kokoro_audio():
    mock = MagicMock()
    mock.return_value = iter([(None, None, np.zeros(24000, dtype=np.float32))])
    return mock


def test_kokoro_registered_with_broker():
    from voice.vram_broker import get_vram_broker
    update_config(tts_engine="kokoro")
    with patch("voice.tts.KPipeline", _fake_kokoro_audio()):
        svc = TTSService()
        svc.load()
    broker = get_vram_broker()
    assert "kokoro" in broker._models
    assert broker._models["kokoro"].state == "gpu"


def test_chatterbox_registered_as_heavy():
    from voice.vram_broker import get_vram_broker
    mock_cb = MagicMock()
    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _fake_kokoro_audio()):
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
    broker = get_vram_broker()
    assert "chatterbox" in broker._models
    assert broker._models["chatterbox"].priority == 3


def test_chatterbox_synthesise_passes_new_params():
    mock_cb = MagicMock()
    mock_cb.generate.return_value = torch.zeros(1, 24000)
    update_config(
        tts_engine="chatterbox",
        chatterbox_seed=99,
        chatterbox_temperature=1.5,
        chatterbox_cfg_weight=0.3,
        chatterbox_exaggeration=0.7,
    )
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _fake_kokoro_audio()), \
         patch("torch.manual_seed") as mock_seed:
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        svc.synthesise("hello")
    mock_seed.assert_called_with(99)
    mock_cb.generate.assert_called_once_with(
        "hello",
        audio_prompt_path=None,
        exaggeration=0.7,
        cfg_weight=0.3,
        temperature=1.5,
    )


def test_chatterbox_synthesise_randomises_seed_when_none():
    mock_cb = MagicMock()
    mock_cb.generate.return_value = torch.zeros(1, 24000)
    update_config(tts_engine="chatterbox", chatterbox_seed=None)
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _fake_kokoro_audio()), \
         patch("torch.manual_seed") as mock_seed:
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        svc.synthesise("hello")
    mock_seed.assert_called_once()
    used_seed = mock_seed.call_args[0][0]
    assert isinstance(used_seed, int)
    assert 0 <= used_seed < 2**31


def _make_callable_kokoro():
    """Returns a mock KPipeline class whose instances are callable iterators."""
    instance_mock = MagicMock()
    instance_mock.return_value = iter([(None, None, np.zeros(24000, dtype=np.float32))])
    class_mock = MagicMock()
    class_mock.return_value = instance_mock
    return class_mock


def test_chatterbox_fallback_releases_heavy_model():
    """Synthesis failure must release the heavy model before loading Kokoro fallback."""
    from voice.vram_broker import get_vram_broker
    mock_cb = MagicMock()
    mock_cb.generate.side_effect = RuntimeError("synthesis failed")
    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _make_callable_kokoro()):
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        # Verify broker state: chatterbox on GPU, kokoro evicted
        broker = get_vram_broker()
        assert broker._models["chatterbox"].state == "gpu"
        # Now synthesise — chatterbox will fail, should release and load kokoro
        result = svc.synthesise("hello")
    # After fallback: chatterbox released, kokoro restored
    assert broker._models["chatterbox"].state == "unloaded"
    assert isinstance(result, np.ndarray)
