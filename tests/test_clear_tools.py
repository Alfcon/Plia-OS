"""Bulk-clear tool for reminders.

`delete_reminder` only ever took a single integer id, so clearing everything
would have required the model to chain list -> parse ids -> delete N times,
which it does not do reliably. Timers share the reminders table but are
cancelled separately, so they must survive a bulk clear.

(Chat clearing needs no new tool: `clear_conversation` already exists. The
reason it appeared missing was prompt truncation — see the num_ctx fix.)
"""
import pytest
from unittest.mock import patch, MagicMock

from agents.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(str(tmp_path / "memory.db"), str(tmp_path / "chroma"))


# ── MemoryStore.clear_pending_reminders ──────────────────────────────────────

def test_clear_pending_reminders_marks_all_done(store):
    store.add_reminder("call mom", "2030-01-01T10:00:00+00:00")
    store.add_reminder("take meds", "2030-01-01T11:00:00+00:00")
    assert len(store.list_pending()) == 2

    assert store.clear_pending_reminders() == 2
    assert store.list_pending() == []


def test_clear_pending_reminders_leaves_timers_running(store):
    # Timers share the reminders table via is_timer and have their own
    # cancel_timer tool. "Clear all reminders" must not silently kill them.
    store.add_reminder("call mom", "2030-01-01T10:00:00+00:00")
    store.add_reminder("pasta", "2030-01-01T10:05:00+00:00", is_timer=True)

    assert store.clear_pending_reminders() == 1
    assert store.list_pending() == []
    assert len(store.list_pending(timers_only=True)) == 1


def test_clear_pending_reminders_empty_is_zero(store):
    assert store.clear_pending_reminders() == 0


def test_clear_pending_reminders_ignores_already_done(store):
    rid = store.add_reminder("old", "2030-01-01T10:00:00+00:00")
    store.mark_reminder_done(rid)
    assert store.clear_pending_reminders() == 0


# ── clear_all_reminders tool ─────────────────────────────────────────────────

def test_clear_all_reminders_reports_count():
    mock_store = MagicMock()
    mock_store.clear_pending_reminders.return_value = 3
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import clear_all_reminders
        result = clear_all_reminders()
    mock_store.clear_pending_reminders.assert_called_once_with()
    assert "3" in result


def test_clear_all_reminders_none_pending():
    mock_store = MagicMock()
    mock_store.clear_pending_reminders.return_value = 0
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import clear_all_reminders
        result = clear_all_reminders()
    assert "No pending reminders" in result


def test_clear_all_reminders_singular_plural():
    mock_store = MagicMock()
    mock_store.clear_pending_reminders.return_value = 1
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import clear_all_reminders
        result = clear_all_reminders()
    assert "1 reminder" in result and "reminders" not in result


def test_clear_all_reminders_registered(reset_registry):
    # conftest's autouse reset_registry clears registrations before each test,
    # so the @tool decorator must be re-run. Drop from sys.modules and
    # re-import under set_loading_module, matching test_ocr_tools.py — reload()
    # is order-dependent and blows up once another test touches sys.modules.
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.reminder_tools" in sys.modules:
        del sys.modules["modules.reminder_tools"]
    set_loading_module("reminder_tools")
    try:
        import modules.reminder_tools  # noqa: F401
    finally:
        set_loading_module("")
    assert "clear_all_reminders" in list_tools()
