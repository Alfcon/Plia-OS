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
