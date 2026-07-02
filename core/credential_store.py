from __future__ import annotations

import base64
import getpass
import hashlib
import json
import logging
import os
import socket
from pathlib import Path

from core.config import get_config, update_config

logger = logging.getLogger(__name__)

_SERVICE = "plia-research"

_CRED_FILE = Path(
    os.environ.get(
        "PLIA_CRED_FILE",
        str(
            Path(
                os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))
            ).parent
            / "credentials.enc"
        ),
    )
)


def _derive_key() -> bytes:
    try:
        user = getpass.getuser()
    except Exception:
        user = "plia"
    raw = (socket.gethostname() + user).encode()
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest)


def _load_file() -> dict:
    if not _CRED_FILE.exists():
        return {}
    try:
        from cryptography.fernet import Fernet
        return json.loads(Fernet(_derive_key()).decrypt(_CRED_FILE.read_bytes()))
    except Exception as exc:
        logger.warning("Failed to decrypt credential file: %s", exc)
        return {}


def _save_file(data: dict) -> None:
    from cryptography.fernet import Fernet
    _CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CRED_FILE.write_bytes(Fernet(_derive_key()).encrypt(json.dumps(data).encode()))
    _CRED_FILE.chmod(0o600)


def _classify_keyring_error(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "nokeyring" in name.lower() or "nobackend" in name.lower():
        return "no keyring backend installed"
    if "permission" in name.lower() or "dbus" in name.lower() or "locked" in msg:
        return "keyring locked or headless environment"
    return f"keyring error: {name}"


def set_credentials(site_slug: str, username: str, password: str) -> str:
    cfg = get_config()

    if cfg.credential_backend == "file":
        data = _load_file()
        data[site_slug] = {"username": username, "password": password}
        _save_file(data)
        return f"Stored credentials for '{site_slug}' in encrypted file."

    try:
        import keyring
        blob = json.dumps({"username": username, "password": password})
        keyring.set_password(_SERVICE, site_slug, blob)
        return f"Stored credentials for '{site_slug}' in system keyring."
    except Exception as exc:
        reason = _classify_keyring_error(exc)
        logger.warning("Keyring unavailable (%s), falling back to encrypted file", reason)
        update_config(credential_backend="file")
        data = _load_file()
        data[site_slug] = {"username": username, "password": password}
        _save_file(data)
        return f"Keyring unavailable ({reason}). Stored credentials for '{site_slug}' in encrypted file."


def get_credentials(site_slug: str) -> dict | None:
    cfg = get_config()

    if cfg.credential_backend == "file":
        data = _load_file()
        return data.get(site_slug)

    try:
        import keyring
        blob = keyring.get_password(_SERVICE, site_slug)
        if blob is None:
            return None
        return json.loads(blob)
    except Exception as exc:
        logger.warning("Keyring read failed (%s), using file backend", _classify_keyring_error(exc))
        update_config(credential_backend="file")
        data = _load_file()
        return data.get(site_slug)


def has_credentials(site_slug: str) -> bool:
    return get_credentials(site_slug) is not None


def remove_credentials(site_slug: str) -> bool:
    cfg = get_config()

    if cfg.credential_backend == "file":
        data = _load_file()
        if site_slug not in data:
            return False
        del data[site_slug]
        _save_file(data)
        return True

    try:
        import keyring
        if keyring.get_password(_SERVICE, site_slug) is None:
            return False
        keyring.delete_password(_SERVICE, site_slug)
        return True
    except Exception as exc:
        logger.warning("Keyring remove failed (%s), using file backend", _classify_keyring_error(exc))
        update_config(credential_backend="file")
        data = _load_file()
        if site_slug not in data:
            return False
        del data[site_slug]
        _save_file(data)
        return True
