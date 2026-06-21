"""Tests for agents/email_store.py account management."""
from __future__ import annotations
import pytest


@pytest.fixture(autouse=True)
def _iso(isolate_email_store):
    pass


def test_list_accounts_empty():
    from agents.email_store import list_accounts
    assert list_accounts() == []


def test_add_and_list_account():
    from agents.email_store import add_account, list_accounts
    add_account({"name": "Work", "provider": "imap", "username": "me@work.com"})
    accounts = list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["name"] == "Work"
    assert accounts[0]["username"] == "me@work.com"


def test_add_account_fills_defaults():
    from agents.email_store import add_account, get_account
    add_account({"name": "Test"})
    acc = get_account("Test")
    assert acc["imap_port"] == 993
    assert acc["smtp_port"] == 587
    assert acc["briefing_enabled"] is False
    assert acc["password"] == ""


def test_add_account_replaces_existing():
    from agents.email_store import add_account, list_accounts
    add_account({"name": "Work", "username": "old@work.com"})
    add_account({"name": "Work", "username": "new@work.com"})
    accounts = list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["username"] == "new@work.com"


def test_get_account_not_found():
    from agents.email_store import get_account
    assert get_account("nonexistent") is None


def test_get_default_account_returns_first():
    from agents.email_store import add_account, get_default_account
    add_account({"name": "First"})
    add_account({"name": "Second"})
    assert get_default_account()["name"] == "First"


def test_get_default_account_empty_returns_none():
    from agents.email_store import get_default_account
    assert get_default_account() is None


def test_remove_account():
    from agents.email_store import add_account, remove_account, list_accounts
    add_account({"name": "ToDelete"})
    removed = remove_account("ToDelete")
    assert removed is True
    assert list_accounts() == []


def test_remove_account_not_found():
    from agents.email_store import remove_account
    assert remove_account("ghost") is False


def test_multiple_accounts_preserved():
    from agents.email_store import add_account, list_accounts
    add_account({"name": "Gmail", "provider": "gmail"})
    add_account({"name": "Work", "provider": "imap"})
    add_account({"name": "Personal", "provider": "imap"})
    accounts = list_accounts()
    assert len(accounts) == 3
    assert accounts[0]["name"] == "Gmail"


def test_add_account_requires_name():
    from agents.email_store import add_account
    with pytest.raises(ValueError, match="name"):
        add_account({"provider": "imap"})
