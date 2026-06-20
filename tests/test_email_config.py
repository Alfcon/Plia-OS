"""Tests for email config fields."""
from __future__ import annotations


def test_email_config_defaults():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.email_provider == ""
    assert cfg.email_imap_host == ""
    assert cfg.email_imap_port == 993
    assert cfg.email_smtp_host == ""
    assert cfg.email_smtp_port == 587
    assert cfg.email_username == ""
    assert cfg.email_password == ""
    assert cfg.email_gmail_credentials_file == ""
    assert cfg.email_briefing_enabled is False


def test_email_config_persists():
    # isolate_config_file (autouse) already redirects _CONFIG_FILE to tmp_path
    from core.config import update_config, get_config
    update_config(
        email_provider="imap",
        email_imap_host="mail.example.com",
        email_imap_port=993,
        email_username="user@example.com",
        email_briefing_enabled=True,
    )
    cfg = get_config()
    assert cfg.email_provider == "imap"
    assert cfg.email_imap_host == "mail.example.com"
    assert cfg.email_briefing_enabled is True
