"""Desktop sudo-password askpass installation."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import core.sudo as sudo


def test_needs_password_detection():
    for msg in (
        "sudo: a password is required",
        "sudo: a terminal is required to read the password",
        "sudo: no tty present and no askpass program specified",
        "sudo: no password was provided",
        "Sorry, try again. 1 incorrect password attempt",
    ):
        assert sudo.needs_password(msg) is True
    assert sudo.needs_password("E: Could not resolve 'archive.ubuntu.com'") is False


def test_no_askpass_on_headless_host(monkeypatch):
    before = dict(os.environ)
    try:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("SUDO_ASKPASS", raising=False)
        monkeypatch.setattr(sudo, "_askpass_path", None)
        with patch.object(sudo.shutil, "which", return_value=None):
            assert sudo.install_askpass() is None
        assert "SUDO_ASKPASS" not in os.environ
    finally:
        os.environ.clear()
        os.environ.update(before)
        sudo._askpass_path = None


def test_install_askpass_creates_executable_helper(monkeypatch):
    before = dict(os.environ)
    made: list[str] = []
    try:
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("SUDO_ASKPASS", raising=False)
        monkeypatch.setattr(sudo, "_askpass_path", None)

        def fake_which(name):
            return "/usr/bin/zenity" if name == "zenity" else None

        with patch.object(sudo.shutil, "which", side_effect=fake_which):
            path = sudo.install_askpass()
            assert path is not None
            made.append(path)
            p = Path(path)
            assert p.exists()
            assert p.stat().st_mode & stat.S_IXUSR
            assert "zenity --password" in p.read_text()
            assert "Plia needs administrator access" in p.read_text()
            assert os.environ["SUDO_ASKPASS"] == path
            assert os.environ["SUDO_ASKPASS_REQUIRE"] == "force"
            # Idempotent: a second call returns the same helper.
            assert sudo.install_askpass() == path
    finally:
        for path in made:
            try:
                os.unlink(path)
            except OSError:
                pass
        os.environ.clear()
        os.environ.update(before)
        sudo._askpass_path = None


def test_existing_askpass_is_respected(monkeypatch, tmp_path):
    before = dict(os.environ)
    script = tmp_path / "custom-askpass.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o700)
    try:
        monkeypatch.setenv("SUDO_ASKPASS", str(script))
        monkeypatch.delenv("SUDO_ASKPASS_REQUIRE", raising=False)
        monkeypatch.setattr(sudo, "_askpass_path", None)
        assert sudo.install_askpass() == str(script)
        assert os.environ["SUDO_ASKPASS_REQUIRE"] == "force"
    finally:
        os.environ.clear()
        os.environ.update(before)
        sudo._askpass_path = None


def test_run_sudo_wraps_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(sudo, "install_askpass", lambda: None)
    monkeypatch.setattr(sudo.subprocess, "run", fake_run)
    r = sudo.run_sudo(["true"], timeout=5)
    assert r.returncode == 0
    cmd, kwargs = calls[0]
    assert cmd == ["sudo", "true"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 5
