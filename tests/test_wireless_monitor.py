"""Monitor-mode helper: killing the processes airmon-ng warns about, on demand."""
import subprocess
from unittest.mock import MagicMock, patch

import modules.wireless_tools as wt

AIRMON_WARNING = (
    "Found 4 processes that could cause trouble.\n"
    "Kill them using 'airmon-ng check kill' before putting\n"
    "the card in monitor mode, they will interfere by changing channels\n"
    "and sometimes putting the interface back in managed mode\n\n"
    "    PID Name\n"
    "   1036 avahi-daemon\n"
    "   1112 wpa_supplicant\n"
    " 168351 NetworkManager\n"
)


def _ok(stdout="", stderr=""):
    return MagicMock(returncode=0, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# start_monitor_mode surfaces the follow-up action
# ---------------------------------------------------------------------------

def test_start_monitor_mode_flags_interfering_processes():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", return_value=None), \
         patch.object(wt, "_sudo", return_value=_ok(stdout=AIRMON_WARNING)):
        out = wt.start_monitor_mode("")
    assert "Monitor mode started on wlan0mon" in out
    assert "Interfering processes detected" in out
    assert "kill_interfering_processes" in out


def test_start_monitor_mode_no_hint_without_warning():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", return_value=None), \
         patch.object(wt, "_sudo", return_value=_ok(stdout="(monitor mode enabled)")):
        out = wt.start_monitor_mode("")
    assert "Interfering processes detected" not in out
    assert "kill_interfering_processes" not in out


# ---------------------------------------------------------------------------
# kill_interfering_processes
# ---------------------------------------------------------------------------

def test_kill_interfering_processes_requires_admin():
    with patch.object(wt, "_has_wireless_admin", return_value=False), \
         patch.object(wt, "_sudo") as sudo:
        out = wt.kill_interfering_processes()
    assert "Permission denied" in out
    sudo.assert_not_called()


def test_kill_interfering_processes_missing_airmon():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value="airmon-ng"), \
         patch.object(wt, "_sudo") as sudo:
        out = wt.kill_interfering_processes()
    assert "install_wireless_tools" in out
    sudo.assert_not_called()


def test_kill_interfering_processes_runs_airmon_check_kill():
    killed = "Killing NetworkManager\nKilling wpa_supplicant\n"
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_sudo", return_value=_ok(stdout=killed)) as sudo:
        out = wt.kill_interfering_processes()
    sudo.assert_called_once()
    assert sudo.call_args.args[:3] == ("airmon-ng", "check", "kill")
    assert "Killed the processes" in out
    assert "NetworkManager" in out
    assert "stop_monitor_mode" in out          # tells the user how to get back online


def test_kill_interfering_processes_reports_failure():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_sudo", return_value=MagicMock(returncode=1, stdout="", stderr="denied")):
        out = wt.kill_interfering_processes()
    assert "failed" in out.lower()
    assert "denied" in out


def test_kill_tool_is_registered_and_admin_gated():
    import sys
    from core import registry
    registry.clear_tools()
    sys.modules.pop("modules.wireless_tools", None)
    import modules.wireless_tools  # noqa: F401  (fresh import re-runs @tool)
    assert "kill_interfering_processes" in registry.list_tools()
