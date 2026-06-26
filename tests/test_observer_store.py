from __future__ import annotations
import pytest
from unittest.mock import patch


@pytest.fixture
def store(tmp_path):
    from agents.observer_store import ObserverStore
    return ObserverStore(str(tmp_path / "observer.db"))


def test_add_and_get_screen_obs(store):
    store.add_screen_obs("2026-01-01T00:00:00+00:00", "Firefox", "firefox", "Hello world")
    obs = store.get_recent_obs(minutes=60 * 24 * 365)
    assert len(obs["screen"]) == 1
    assert obs["screen"][0]["ocr_text"] == "Hello world"
    assert obs["screen"][0]["app_name"] == "firefox"
    assert obs["screen"][0]["window_title"] == "Firefox"


def test_add_and_get_focus_event(store):
    store.add_focus_event("2026-01-01T00:00:00+00:00", "Terminal", "bash", 45.5)
    obs = store.get_recent_obs(minutes=60 * 24 * 365)
    assert len(obs["focus"]) == 1
    assert obs["focus"][0]["duration_seconds"] == 45.5
    assert obs["focus"][0]["app_name"] == "bash"


def test_add_and_get_key_chunk(store):
    store.add_key_chunk("2026-01-01T00:00:00+00:00", "VS Code", "code", "hello world")
    obs = store.get_recent_obs(minutes=60 * 24 * 365)
    assert len(obs["keys"]) == 1
    assert obs["keys"][0]["text_chunk"] == "hello world"
    assert obs["keys"][0]["app_name"] == "code"


def test_get_recent_obs_filters_by_time(store):
    store.add_screen_obs("2020-01-01T00:00:00+00:00", "Old", "old", "stale text")
    obs = store.get_recent_obs(minutes=10)
    assert len(obs["screen"]) == 0


def test_get_recent_obs_returns_all_tables(store):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    store.add_screen_obs(now, "Browser", "firefox", "text")
    store.add_focus_event(now, "Terminal", "bash", 10.0)
    store.add_key_chunk(now, "Editor", "code", "typed")
    obs = store.get_recent_obs(minutes=5)
    assert len(obs["screen"]) == 1
    assert len(obs["focus"]) == 1
    assert len(obs["keys"]) == 1


def test_save_and_get_latest_profile(store):
    store.save_profile("2026-01-01T00:00:00+00:00", "User is coding in Python.")
    assert store.get_latest_profile() == "User is coding in Python."


def test_get_latest_profile_returns_most_recent(store):
    store.save_profile("2026-01-01T00:00:00+00:00", "First profile")
    store.save_profile("2026-01-01T01:00:00+00:00", "Second profile")
    assert store.get_latest_profile() == "Second profile"


def test_get_latest_profile_empty(store):
    assert store.get_latest_profile() is None


def test_prune_old_removes_stale_obs(store):
    store.add_screen_obs("2020-01-01T00:00:00+00:00", "Old", "old", "stale")
    store.prune_old(retention_hours=24)
    obs = store.get_recent_obs(minutes=60 * 24 * 365 * 10)
    assert len(obs["screen"]) == 0


def test_prune_old_keeps_recent_obs(store):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    store.add_screen_obs(now, "Browser", "firefox", "recent")
    store.prune_old(retention_hours=24)
    obs = store.get_recent_obs(minutes=10)
    assert len(obs["screen"]) == 1


def test_prune_old_removes_stale_profiles(store):
    store.save_profile("2020-01-01T00:00:00+00:00", "Old profile")
    store.prune_old(retention_hours=24)
    assert store.get_latest_profile() is None


def test_get_observer_store_singleton(tmp_path):
    import agents.observer_store as mod
    old_store = mod._store
    mod._store = None
    try:
        with patch("core.config.get_config") as mock_cfg:
            mock_cfg.return_value.memory_dir = str(tmp_path)
            s1 = mod.get_observer_store()
            s2 = mod.get_observer_store()
        assert s1 is s2
    finally:
        mod._store = old_store
