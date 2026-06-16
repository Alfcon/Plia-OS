from unittest.mock import patch, MagicMock


def _mock_status(used=2.5, total=8.0, studio=False, active_heavy=None, models=None):
    return {
        "vram_used_gb": used,
        "vram_total_gb": total,
        "studio_mode": studio,
        "active_heavy": active_heavy,
        "models": models or {},
    }


def test_get_vram_status_basic():
    mock_broker = MagicMock()
    mock_broker.status.return_value = _mock_status(used=2.5, total=8.0)
    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        from modules.example_module import get_vram_status
        result = get_vram_status()
    assert "2.5" in result
    assert "8.0" in result
    assert "VRAM" in result


def test_get_vram_status_shows_gpu_models():
    models = {
        "whisper": {"state": "cpu", "vram_gb": 0.0},
        "tts": {"state": "gpu", "vram_gb": 2.5},
    }
    mock_broker = MagicMock()
    mock_broker.status.return_value = _mock_status(models=models)
    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        from modules.example_module import get_vram_status
        result = get_vram_status()
    assert "tts" in result
    assert "gpu" in result
    assert "whisper" in result
    assert "cpu" in result


def test_get_vram_status_studio_mode():
    mock_broker = MagicMock()
    mock_broker.status.return_value = _mock_status(studio=True, active_heavy="chatterbox")
    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        from modules.example_module import get_vram_status
        result = get_vram_status()
    assert "yes" in result
    assert "chatterbox" in result


def test_get_vram_status_no_models():
    mock_broker = MagicMock()
    mock_broker.status.return_value = _mock_status(models={})
    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        from modules.example_module import get_vram_status
        result = get_vram_status()
    assert "VRAM" in result
