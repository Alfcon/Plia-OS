import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_set_credentials_stores_in_keyring(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.set_password") as mock_set, \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials
        result = set_credentials("google-scholar", "user1", "pass1")

    mock_set.assert_called_once_with(
        "plia-research",
        "google-scholar",
        json.dumps({"username": "user1", "password": "pass1"}),
    )
    assert "system keyring" in result


def test_set_credentials_falls_back_to_file_on_no_keyring(tmp_path):
    import keyring.errors
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.set_password", side_effect=keyring.errors.NoKeyringError()), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store.update_config") as mock_update, \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials
        result = set_credentials("arxiv", "user2", "pass2")

    mock_update.assert_called_once_with(credential_backend="file")
    assert "encrypted file" in result
    assert cred_file.exists()


def test_set_credentials_uses_file_when_backend_is_file(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "file"

    with patch("keyring.set_password") as mock_set, \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials
        result = set_credentials("jstor", "u", "p")

    mock_set.assert_not_called()
    assert cred_file.exists()


def test_get_credentials_from_keyring(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"
    blob = json.dumps({"username": "alice", "password": "secret"})

    with patch("keyring.get_password", return_value=blob), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import get_credentials
        creds = get_credentials("google-scholar")

    assert creds == {"username": "alice", "password": "secret"}


def test_get_credentials_returns_none_when_not_found(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value=None), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import get_credentials
        assert get_credentials("unknown-site") is None


def test_roundtrip_file_backend(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "file"

    with patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store.update_config"), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials, get_credentials
        set_credentials("jstor", "bob", "hunter2")
        creds = get_credentials("jstor")

    assert creds == {"username": "bob", "password": "hunter2"}


def test_has_credentials_true(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"
    blob = json.dumps({"username": "x", "password": "y"})

    with patch("keyring.get_password", return_value=blob), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import has_credentials
        assert has_credentials("jstor") is True


def test_has_credentials_false(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value=None), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import has_credentials
        assert has_credentials("no-site") is False


def test_remove_credentials_keyring(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value='{"username":"a","password":"b"}'), \
         patch("keyring.delete_password") as mock_del, \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import remove_credentials
        result = remove_credentials("google-scholar")

    mock_del.assert_called_once_with("plia-research", "google-scholar")
    assert result is True


def test_remove_credentials_returns_false_when_not_found(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value=None), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import remove_credentials
        assert remove_credentials("missing") is False
