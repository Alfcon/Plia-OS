import os
from core.config import reset_config, update_config, get_config


def setup_function():
    reset_config()


def teardown_function():
    reset_config()


def test_fallback_provider_defaults_empty():
    assert get_config().fallback_provider == ""


def test_fallback_model_defaults_empty():
    assert get_config().fallback_model == ""


def test_web_search_default_is_ddg():
    assert get_config().web_search_default == "ddg"


def test_memory_dir_default():
    assert get_config().memory_dir == os.path.expanduser("~/.plia")


def test_update_fallback_provider():
    update_config(fallback_provider="openai")
    assert get_config().fallback_provider == "openai"


def test_update_web_search_default():
    update_config(web_search_default="google")
    assert get_config().web_search_default == "google"


def test_tts_engine_valid_values_accepted():
    for engine in ("kokoro", "chatterbox", "dramabox"):
        update_config(tts_engine=engine)
        assert get_config().tts_engine == engine


def test_tts_engine_invalid_value_raises():
    import pytest
    with pytest.raises(ValueError, match="tts_engine"):
        update_config(tts_engine="garbage")


def test_studio_pipeline_mode_invalid_raises():
    import pytest
    with pytest.raises(ValueError, match="studio_pipeline_mode"):
        update_config(studio_pipeline_mode="invalid")
