import json
import pytest
from pathlib import Path
from core.config import reset_config, update_config, get_config, PliaConfig, _load_persisted, _save_persisted


@pytest.fixture(autouse=True)
def clean():
    reset_config()
    yield
    reset_config()


def test_save_writes_json(tmp_path):
    cfg = PliaConfig()
    cfg.ollama_model = "mistral"
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        _save_persisted(cfg)
        data = json.loads((tmp_path / "config.json").read_text())
        assert data["ollama_model"] == "mistral"
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_load_applies_saved_values(tmp_path):
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        (tmp_path / "config.json").write_text(json.dumps({"ollama_model": "phi3", "hass_url": "http://ha.local"}))
        cfg = PliaConfig()
        _load_persisted(cfg)
        assert cfg.ollama_model == "phi3"
        assert cfg.hass_url == "http://ha.local"
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_load_ignores_unknown_keys(tmp_path):
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        (tmp_path / "config.json").write_text(json.dumps({"no_such_field": "value"}))
        cfg = PliaConfig()
        _load_persisted(cfg)  # should not raise
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_load_missing_file_is_noop(tmp_path):
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "nonexistent.json"
    try:
        cfg = PliaConfig()
        _load_persisted(cfg)
        assert cfg.ollama_model == "llama3.2"
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_update_config_persists(tmp_path):
    import core.config as cfg_mod
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    update_config(ollama_model="gemma")
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["ollama_model"] == "gemma"


def test_update_config_persists_hass_credentials(tmp_path):
    import core.config as cfg_mod
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    update_config(hass_url="http://ha.local:8123", hass_token="secret")
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["hass_url"] == "http://ha.local:8123"
    assert data["hass_token"] == "secret"


def test_load_corrupt_file_does_not_raise(tmp_path):
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        (tmp_path / "config.json").write_text("{ not valid json }")
        cfg = PliaConfig()
        _load_persisted(cfg)  # should swallow error
        assert cfg.ollama_model == "llama3.2"
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_update_config_rejects_out_of_range_timing():
    # max_utterance_seconds <= 0 would brick voice capture (the listen loop's
    # deadline is already expired); silence_timeout_seconds = 0 would cut every
    # turn at the first quiet chunk. POST /api/config maps this to a 422.
    with pytest.raises(ValueError):
        update_config(max_utterance_seconds=0)
    with pytest.raises(ValueError):
        update_config(max_utterance_seconds=-5)
    with pytest.raises(ValueError):
        update_config(silence_timeout_seconds=0)
    with pytest.raises(ValueError):
        update_config(prespeech_bail_seconds=0)
    with pytest.raises(ValueError):
        update_config(silence_timeout_seconds=True)  # bool is not a duration


def test_update_config_accepts_in_range_timing():
    cfg = update_config(silence_timeout_seconds=1.5, max_utterance_seconds=30,
                        prespeech_bail_seconds=3.0)
    assert cfg.silence_timeout_seconds == 1.5
    assert cfg.max_utterance_seconds == 30
    assert cfg.prespeech_bail_seconds == 3.0


def test_load_skips_out_of_range_persisted_timing(tmp_path):
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        (tmp_path / "config.json").write_text(json.dumps({
            "silence_timeout_seconds": 8.0,   # old-era default, above range max 3.0
            "max_utterance_seconds": 0,
        }))
        cfg = PliaConfig()
        _load_persisted(cfg)
        assert cfg.silence_timeout_seconds == 0.8
        assert cfg.max_utterance_seconds == 15.0
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_load_migrates_old_semantics_silence_timeout(tmp_path):
    # silence_timeout_seconds reversed meaning (whole-utterance cap ->
    # trailing-silence window). A file still containing the retired
    # silence_chunks_threshold key predates that change, so its
    # silence_timeout_seconds value is old-semantics and must be dropped
    # even when it happens to be inside the new valid range.
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        (tmp_path / "config.json").write_text(json.dumps({
            "silence_chunks_threshold": 10,
            "silence_timeout_seconds": 2,     # in-range, but old meaning
            "ollama_model": "phi3",
        }))
        cfg = PliaConfig()
        _load_persisted(cfg)
        assert cfg.silence_timeout_seconds == 0.8   # new default, not 2
        assert cfg.ollama_model == "phi3"           # other keys still load
    finally:
        cfg_mod._CONFIG_FILE = orig


def test_load_keeps_new_era_silence_timeout(tmp_path):
    # No marker key -> the file was written after the change; the value is
    # new-semantics and must load normally.
    import core.config as cfg_mod
    orig = cfg_mod._CONFIG_FILE
    cfg_mod._CONFIG_FILE = tmp_path / "config.json"
    try:
        (tmp_path / "config.json").write_text(json.dumps({
            "silence_timeout_seconds": 1.2,
        }))
        cfg = PliaConfig()
        _load_persisted(cfg)
        assert cfg.silence_timeout_seconds == 1.2
    finally:
        cfg_mod._CONFIG_FILE = orig
