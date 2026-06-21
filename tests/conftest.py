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


@pytest.fixture
def isolate_email_store(tmp_path, monkeypatch):
    """Redirect email account store to a temp directory so tests never touch ~/.email_client."""
    import agents.email_store as es
    monkeypatch.setattr(es, "_CLIENT_DIR", tmp_path / "email_client")
    monkeypatch.setattr(es, "_ACCOUNTS_FILE", tmp_path / "email_client" / "accounts.json")


@pytest.fixture(autouse=True)
def reset_tor_manager():
    yield
    import core.tor_manager as tm
    tm._kill_switch_active = False
    tm._monitor_task = None
    tm._last_tor_uid = ""
    tm._exit_ip = None
