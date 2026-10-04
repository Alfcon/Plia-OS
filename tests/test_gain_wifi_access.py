import subprocess
from unittest.mock import MagicMock, patch

import modules.wireless_tools as wt


def _ap(ssid="Home", bssid="AA:BB:CC:DD:EE:FF", channel="6"):
    return {"ssid": ssid, "bssid": bssid, "channel": channel, "enc": "WPA2", "power": -40}


def _sudo_ok():
    return MagicMock(returncode=0, stdout="", stderr="")


def test_gain_denied_without_admin():
    with patch.object(wt, "_has_wireless_admin", return_value=False):
        out = wt.gain_wifi_access("Home")
    assert "permission" in out.lower()


def test_gain_missing_tools():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", side_effect=lambda b: b if b == "airmon-ng" else None):
        out = wt.gain_wifi_access("Home")
    assert "Missing tools" in out
    assert "airmon-ng" in out


def test_gain_requires_ssid():
    with patch.object(wt, "_has_wireless_admin", return_value=True):
        assert wt.gain_wifi_access("") == "ssid is required."


def test_gain_wps_recovers_and_connects():
    ap = _ap()
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_scan", return_value=[ap]), \
         patch.object(wt, "_find_target_ap", return_value=ap), \
         patch.object(wt, "_wps_psk", return_value="hunter2"), \
         patch.object(wt, "_stop_monitor") as stop, \
         patch("modules.network_tools.connect_wifi", return_value="Connected to 'Home'.") as conn:
        out = wt.gain_wifi_access("Home")
    assert "WPS" in out
    conn.assert_called_once_with("Home", "wlan0", "hunter2")
    stop.assert_called_once_with("wlan0mon")


def test_gain_handshake_crack_recovers_and_connects():
    ap = _ap()
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_scan", return_value=[ap]), \
         patch.object(wt, "_find_target_ap", return_value=ap), \
         patch.object(wt, "_wps_psk", return_value=None), \
         patch.object(wt, "_capture_handshake_file", return_value="/tmp/x-01.cap"), \
         patch.object(wt, "_crack_with_wordlists", return_value="hunter2"), \
         patch.object(wt, "_stop_monitor"), \
         patch("modules.network_tools.connect_wifi", return_value="Connected to 'Home'.") as conn:
        out = wt.gain_wifi_access("Home")
    assert "handshake cracking" in out
    conn.assert_called_once_with("Home", "wlan0", "hunter2")


def test_gain_target_not_found():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_scan", return_value=[]), \
         patch.object(wt, "_find_target_ap", return_value=None), \
         patch.object(wt, "_stop_monitor"):
        out = wt.gain_wifi_access("Ghost")
    assert "Could not find 'Ghost'" in out


def test_gain_no_handshake_captured():
    ap = _ap()
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_scan", return_value=[ap]), \
         patch.object(wt, "_find_target_ap", return_value=ap), \
         patch.object(wt, "_wps_psk", return_value=None), \
         patch.object(wt, "_capture_handshake_file", return_value=None), \
         patch.object(wt, "_stop_monitor"):
        out = wt.gain_wifi_access("Home")
    assert "No handshake captured" in out


def test_gain_crack_fails_reports_capture():
    ap = _ap()
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_scan", return_value=[ap]), \
         patch.object(wt, "_find_target_ap", return_value=ap), \
         patch.object(wt, "_wps_psk", return_value=None), \
         patch.object(wt, "_capture_handshake_file", return_value="/tmp/x-01.cap"), \
         patch.object(wt, "_crack_with_wordlists", return_value=None), \
         patch.object(wt, "_stop_monitor"):
        out = wt.gain_wifi_access("Home")
    assert "wordlists" in out


def test_find_target_ap_exact_then_containment():
    nets = [
        {"ssid": "Home 5G", "bssid": "B", "channel": "44", "enc": "WPA2", "power": -80},
        {"ssid": "Home", "bssid": "A", "channel": "6", "enc": "WPA2", "power": -50},
    ]
    assert wt._find_target_ap("home", nets)["bssid"] == "A"
    assert wt._find_target_ap("home 5", nets)["bssid"] == "B"
    assert wt._find_target_ap("missing", nets) is None


def test_sudo_returns_completed_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["sudo", "reaver"], 120)):
        r = wt._sudo("reaver", timeout=120)
    assert r.returncode == -1
    assert "timed out" in r.stderr


def test_wps_psk_returns_none_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["sudo", "reaver"], 120)):
        assert wt._wps_psk("wlan0mon", "AA:BB:CC:DD:EE:FF", "6") is None


def test_gain_catches_unexpected_error_and_stops_monitor():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_scan", side_effect=RuntimeError("boom")), \
         patch.object(wt, "_stop_monitor") as stop:
        out = wt.gain_wifi_access("Home")
    assert "Access recovery failed" in out
    assert "boom" in out
    stop.assert_called_once_with("wlan0mon")
