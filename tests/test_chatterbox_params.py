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
