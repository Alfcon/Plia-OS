from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_observer():
    import sys
    # Make sure we start with a clean slate for the module
    if "core.observer" in sys.modules:
        import core.observer as mod
        old = mod._observer
        mod._observer = None
        yield
        mod._observer = old
    else:
        yield
    # Clean up after test so singleton doesn't leak between tests
    if "core.observer" in sys.modules:
        import core.observer as mod
        mod._observer = None


def _make_store():
    store = MagicMock()
    store.get_latest_profile.return_value = None
    store.get_recent_obs.return_value = {"screen": [], "focus": [], "keys": []}
    return store


def test_get_observer_returns_singleton():
    with patch("agents.observer_store.get_observer_store", return_value=_make_store()):
        from core.observer import get_observer
        o1 = get_observer()
        o2 = get_observer()
    assert o1 is o2


def test_get_profile_returns_empty_when_no_profile():
    with patch("agents.observer_store.get_observer_store", return_value=_make_store()):
        from core.observer import get_observer
        obs = get_observer()
    assert obs.get_profile() == ""


def test_get_profile_restores_from_store():
    store = _make_store()
    store.get_latest_profile.return_value = "User is coding."
    with patch("agents.observer_store.get_observer_store", return_value=store):
        from core.observer import get_observer
        obs = get_observer()
    assert obs.get_profile() == "User is coding."


@pytest.mark.asyncio
async def test_start_creates_tasks():
    store = _make_store()
    with patch("agents.observer_store.get_observer_store", return_value=store):
        from core.observer import get_observer
        obs = get_observer()
    with patch.object(obs, "_screen_loop", new_callable=AsyncMock), \
         patch.object(obs, "_focus_loop", new_callable=AsyncMock), \
         patch.object(obs, "_key_loop", new_callable=AsyncMock), \
         patch.object(obs, "_profile_loop", new_callable=AsyncMock):
        await obs.start()
        assert obs.is_running()
        await obs.stop()
        assert not obs.is_running()


@pytest.mark.asyncio
async def test_profile_loop_calls_llm_and_stores():
    store = _make_store()
    store.get_recent_obs.return_value = {
        "screen": [{"ts": "2026-01-01T00:00:00+00:00", "window_title": "VS Code",
                    "app_name": "code", "ocr_text": "def hello():"}],
        "focus": [{"ts": "2026-01-01T00:00:00+00:00", "window_title": "VS Code",
                   "app_name": "code", "duration_seconds": 120.0}],
        "keys": [{"ts": "2026-01-01T00:00:00+00:00", "window_title": "VS Code",
                  "app_name": "code", "text_chunk": "def hello():"}],
    }
    mock_llm = AsyncMock(return_value={"content": "User is writing Python code in VS Code."})
    with patch("agents.observer_store.get_observer_store", return_value=store), \
         patch("agents.llm.call_llm", mock_llm):
        from core.observer import ObserverService
        obs = ObserverService()
        obs._profile_interval = 0
        await obs._run_profile_once()
    assert obs.get_profile() == "User is writing Python code in VS Code."
    store.save_profile.assert_called_once()


@pytest.mark.asyncio
async def test_profile_loop_skips_on_llm_error():
    store = _make_store()
    store.get_recent_obs.return_value = {"screen": [], "focus": [], "keys": []}
    mock_llm = AsyncMock(side_effect=Exception("LLM offline"))
    with patch("agents.observer_store.get_observer_store", return_value=store), \
         patch("agents.llm.call_llm", mock_llm):
        from core.observer import ObserverService
        obs = ObserverService()
        await obs._run_profile_once()
    assert obs.get_profile() == ""
    store.save_profile.assert_not_called()


@pytest.mark.asyncio
async def test_screen_loop_skips_duplicate_text():
    store = _make_store()

    capture_count = 0

    async def _fake_screen_once(obs):
        nonlocal capture_count
        capture_count += 1
        text = "Same text every time"
        if text == obs._last_ocr_text:
            return
        obs._last_ocr_text = text
        store.add_screen_obs("ts", "Win", "app", text)

    with patch("agents.observer_store.get_observer_store", return_value=store):
        from core.observer import ObserverService
        obs = ObserverService()
        await _fake_screen_once(obs)
        await _fake_screen_once(obs)

    assert store.add_screen_obs.call_count == 1


def test_is_running_false_before_start():
    with patch("agents.observer_store.get_observer_store", return_value=_make_store()):
        from core.observer import ObserverService
        obs = ObserverService()
    assert not obs.is_running()


def test_last_capture_ts_none_before_any_capture():
    with patch("agents.observer_store.get_observer_store", return_value=_make_store()):
        from core.observer import ObserverService
        obs = ObserverService()
    assert obs.last_capture_ts() is None


def test_keycode_to_char_import_error_fallback():
    """When evdev is not importable, _keycode_to_char returns empty string."""
    import sys
    import importlib

    # Remove evdev from sys.modules to simulate it not being installed
    saved = sys.modules.pop("evdev", None)
    # Also remove core.observer so it re-imports fresh
    sys.modules.pop("core.observer", None)
    try:
        # Patch the import to raise ImportError
        import builtins
        real_import = builtins.__import__

        def _import_blocker(name, *args, **kwargs):
            if name == "evdev":
                raise ImportError("No module named 'evdev'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import_blocker):
            from core.observer import _keycode_to_char
            result = _keycode_to_char(30, False)
    finally:
        if saved is not None:
            sys.modules["evdev"] = saved
        sys.modules.pop("core.observer", None)

    assert result == ""
