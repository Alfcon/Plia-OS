import pytest
import tempfile
from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_config_file(tmp_path, monkeypatch):
    import core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "_config", cfg_mod.PliaConfig())


@pytest.fixture(autouse=True)
def reset_registry():
    from core import registry
    registry.clear_tools()
    yield
    registry.clear_tools()


@pytest.fixture(autouse=True)
def reset_events():
    from core import events
    events.clear_subscribers()
    yield
    events.clear_subscribers()
