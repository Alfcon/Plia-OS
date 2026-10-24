"""Tests for install_wireless_tools' failure handling and sudo prompt path."""
from __future__ import annotations

from types import SimpleNamespace

import modules.wireless_tools as wt


def _r(rc: int = 0, out: str = "", err: str = ""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def test_needs_password_detection():
    for msg in (
        "sudo: a password is required",
        "sudo: a terminal is required to read the password",
        "sudo: no tty present and no askpass program specified",
        "sudo: no password was provided",
        "Sorry, try again. incorrect password",
    ):
        assert wt._needs_password(msg) is True
    assert wt._needs_password("E: Could not resolve 'archive.ubuntu.com'") is False


def test_dns_failure_detection():
    assert wt._dns_failure("Could not resolve 'archive.ubuntu.com'") is True
    assert wt._dns_failure("Temporary failure resolving 'archive.ubuntu.com'") is True
    assert wt._dns_failure("E: Unable to fetch some archives") is False


def test_install_reports_dns_problem(monkeypatch):
    calls = iter([
        _r(0),  # apt-get update
        _r(1, err="E: Failed to fetch http://archive.ubuntu.com/...\n"
                  "E: Could not resolve 'archive.ubuntu.com'"),
    ])
    monkeypatch.setattr(wt, "_run_apt", lambda *a, **k: next(calls))
    out = wt.install_wireless_tools()
    assert "could not be resolved" in out.lower()
    assert "not a permissions problem" in out
    assert "sudo apt-get update" in out


def test_install_reports_sudo_problem(monkeypatch):
    calls = iter([_r(0), _r(1, err="sudo: a password is required")])
    monkeypatch.setattr(wt, "_run_apt", lambda *a, **k: next(calls))
    out = wt.install_wireless_tools()
    assert "administrator (sudo) permission" in out
    assert "sudo apt-get update" in out


def test_install_success_and_wordlist_guidance(monkeypatch):
    monkeypatch.setattr(wt, "_run_apt", lambda *a, **k: _r(0))
    monkeypatch.setattr(wt, "_bin_missing", lambda _n: None)
    monkeypatch.setattr(wt, "_find_rockyou", lambda: (None, "help"))
    out = wt.install_wireless_tools()
    assert "Installed. Available:" in out
    assert "download_rockyou" in out


def test_update_failure_does_not_block_install(monkeypatch):
    calls = iter([
        _r(1, err="W: Some index files failed to download"),
        _r(0),
    ])
    monkeypatch.setattr(wt, "_run_apt", lambda *a, **k: next(calls))
    monkeypatch.setattr(wt, "_bin_missing", lambda _n: None)
    monkeypatch.setattr(wt, "_find_rockyou", lambda: ("/usr/share/wordlists/rockyou.txt", ""))
    out = wt.install_wireless_tools()
    assert "Installed. Available:" in out


def test_run_apt_retries_with_graphical_prompt(monkeypatch, tmp_path):
    ask = tmp_path / "ask.sh"
    ask.write_text("#!/bin/sh\nexit 0\n")
    ask.chmod(0o700)
    monkeypatch.setattr(wt, "_askpass_script", lambda: str(ask))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:2] == ["sudo", "-n"]:
            return _r(1, err="sudo: a password is required")
        return _r(0)

    monkeypatch.setattr(wt.subprocess, "run", fake_run)
    r = wt._run_apt(["install", "-y", "aircrack-ng"], timeout=5)

    assert r.returncode == 0
    assert calls[0][0][:2] == ["sudo", "-n"]
    assert calls[1][0][:2] == ["sudo", "-A"]
    assert calls[1][1]["env"]["SUDO_ASKPASS"] == str(ask)
    assert ask.exists() is False  # temporary helper is always removed


def test_run_apt_without_gui_returns_original_failure(monkeypatch):
    monkeypatch.setattr(wt, "_askpass_script", lambda: None)
    monkeypatch.setattr(wt.subprocess, "run",
                        lambda *a, **k: _r(1, err="sudo: a terminal is required"))
    r = wt._run_apt(["install", "-y", "aircrack-ng"])
    assert r.returncode == 1
