import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture(autouse=True)
def _temp_db(monkeypatch, tmp_path):
    """Redirect chat history DB to a temp file per test."""
    import agents.chat_history as ch
    db = tmp_path / "test_chat.db"
    monkeypatch.setattr(ch, "_DB_PATH", db)
    ch._init_db()
    yield


def test_add_and_get_recent():
    from agents.chat_history import add_message, get_recent
    add_message("user", "hello")
    add_message("assistant", "hi there")
    msgs = get_recent()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["role"] == "assistant"
    assert "ts" in msgs[0]


def test_get_recent_respects_limit():
    from agents.chat_history import add_message, get_recent
    for i in range(10):
        add_message("user", f"msg {i}")
    assert len(get_recent(5)) == 5


def test_get_recent_order_oldest_first():
    from agents.chat_history import add_message, get_recent
    add_message("user", "first")
    add_message("user", "second")
    msgs = get_recent()
    assert msgs[0]["content"] == "first"
    assert msgs[1]["content"] == "second"


def test_clear():
    from agents.chat_history import add_message, get_recent, clear
    add_message("user", "hello")
    clear()
    assert get_recent() == []


def test_empty_db_returns_empty_list():
    from agents.chat_history import get_recent
    assert get_recent() == []
