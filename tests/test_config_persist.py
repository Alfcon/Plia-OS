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
