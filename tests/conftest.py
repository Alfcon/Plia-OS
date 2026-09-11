import pytest
import tempfile
from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_config_file(tmp_path, monkeypatch):
    import core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "_config", cfg_mod.PliaConfig())


@pytest.fixture(autouse=True)
def isolate_memory_store(isolate_config_file):
    """Point memory_dir at a private temp dir so tests never touch ~/.plia.

    isolate_config_file resets config to defaults, whose memory_dir is the real
    ~/.plia — so the MemoryStore singleton must be rebuilt against a temp dir,
    and the event_log table re-created there (its module-level _init only ran
    once at import). Uses its own temp dir, not tmp_path, so tests that list
    tmp_path contents don't see isolation files.
    """
    import core.event_log as event_log
    from core.config import get_config

    def _reset_stores():
        # Every store singleton that captures memory_dir at construction.
        import agents.memory_store, agents.cron_store, agents.document_store
        import agents.observer_store, agents.adaptation, agents.calendar_store
        for mod in (agents.memory_store, agents.cron_store, agents.document_store,
                    agents.observer_store, agents.adaptation, agents.calendar_store):
            mod._store = None

    with tempfile.TemporaryDirectory() as td:
        get_config().memory_dir = td
        _reset_stores()
        event_log._init()
        yield
        _reset_stores()


@pytest.fixture(autouse=True)
def isolate_chat_history(monkeypatch):
    """Redirect chat history DB to a temp path so tests never touch data/chat_history.db."""
    import agents.chat_history as ch
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(ch, "_DB_PATH", Path(td) / "chat_history.db")
        ch._init_db()
        yield


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


@pytest.fixture(autouse=True)
def reset_watchdog():
    from core import watchdog
    watchdog._reset_for_tests()
    yield
    watchdog._reset_for_tests()


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
