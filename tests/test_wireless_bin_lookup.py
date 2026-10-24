"""_bin_missing must find binaries that are not on the inherited PATH.

On Debian/Ubuntu the aircrack suite lives in /usr/sbin, which a GUI-launched
process frequently does not have on PATH. Searching PATH alone made every
wireless tool answer "airmon-ng not found. Run: install_wireless_tools" on a
machine where it is installed.
"""
import modules.wireless_tools as wt


def _fake_bin(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_bin_missing_finds_binary_outside_path(tmp_path, monkeypatch):
    _fake_bin(tmp_path / "sbin", "airmon-ng")
    monkeypatch.setattr(wt, "_EXTRA_BIN_DIRS", (str(tmp_path / "sbin"),))
    monkeypatch.setenv("PATH", "/nonexistent-path")
    assert wt._bin_missing("airmon-ng") is None


def test_bin_missing_finds_binary_on_path(monkeypatch):
    monkeypatch.setattr(wt, "_EXTRA_BIN_DIRS", ())
    assert wt._bin_missing("sh") is None


def test_bin_missing_reports_a_genuinely_absent_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(wt, "_EXTRA_BIN_DIRS", (str(tmp_path),))
    monkeypatch.setenv("PATH", "/nonexistent-path")
    assert wt._bin_missing("no-such-tool-xyz") == "no-such-tool-xyz"


def test_bin_missing_ignores_non_executable_and_directories(tmp_path, monkeypatch):
    (tmp_path / "notexec").write_text("nope\n")        # mode 644
    (tmp_path / "adir").mkdir()
    monkeypatch.setattr(wt, "_EXTRA_BIN_DIRS", (str(tmp_path),))
    monkeypatch.setenv("PATH", "/nonexistent-path")
    assert wt._bin_missing("notexec") == "notexec"
    assert wt._bin_missing("adir") == "adir"


def test_start_monitor_mode_reaches_airmon_when_it_is_sbin_only(tmp_path, monkeypatch):
    # End-to-end: the sbin lookup is what lets the tool actually run.
    _fake_bin(tmp_path / "sbin", "airmon-ng")
    monkeypatch.setattr(wt, "_EXTRA_BIN_DIRS", (str(tmp_path / "sbin"),))
    monkeypatch.setenv("PATH", "/nonexistent-path")
    from unittest.mock import MagicMock, patch
    ran = MagicMock(returncode=0, stdout="(monitor mode enabled)", stderr="")
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", return_value=None), \
         patch.object(wt, "_sudo", return_value=ran) as sudo:
        out = wt.start_monitor_mode("")
    assert "not found" not in out
    sudo.assert_called_once()
