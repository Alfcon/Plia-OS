from __future__ import annotations
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CLIENT_DIR = Path.home() / ".email_client"
_ACCOUNTS_FILE = _CLIENT_DIR / "accounts.json"

_DEFAULTS: dict = {
    "name": "",
    "provider": "",           # "gmail" | "imap"
    "username": "",
    "password": "",           # app password — never logged
    "imap_host": "",
    "imap_port": 993,
    "smtp_host": "",
    "smtp_port": 587,
    "gmail_credentials_file": "",
    "briefing_enabled": False,
}


def client_dir() -> Path:
    return _CLIENT_DIR


def _load() -> list[dict]:
    if not _ACCOUNTS_FILE.exists():
        return []
    try:
        return json.loads(_ACCOUNTS_FILE.read_text())
    except Exception:
        logger.exception("Failed to read %s", _ACCOUNTS_FILE)
        return []


def _save(accounts: list[dict]) -> None:
    _CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    _ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))


def list_accounts() -> list[dict]:
    return _load()


def get_account(name: str) -> dict | None:
    return next((a for a in _load() if a.get("name") == name), None)


def get_default_account() -> dict | None:
    accounts = _load()
    return accounts[0] if accounts else None


def add_account(account: dict) -> dict:
    """Add or replace account by name. Returns the full account dict."""
    if not account.get("name"):
        raise ValueError("account name is required")
    accounts = _load()
    accounts = [a for a in accounts if a.get("name") != account["name"]]
    full = {**_DEFAULTS, **account}
    accounts.append(full)
    _save(accounts)
    return full


def remove_account(name: str) -> bool:
    accounts = _load()
    new = [a for a in accounts if a.get("name") != name]
    if len(new) == len(accounts):
        return False
    _save(new)
    return True
