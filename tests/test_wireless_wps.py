import subprocess
from unittest.mock import MagicMock, patch

import modules.wireless_tools as wt


def _run(stdout="", stderr=""):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_scan_wps_parses_results():
    out = (
        "BSSID              Ch  dBm  WPS  Lck  ESSID\n"
        "-------------------------------------------\n"
        "AA:BB:CC:DD:EE:FF  6   -40  2.0  No   HomeNet\n"
    )
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch("subprocess.run", return_value=_run(stdout=out)):
        res = wt.scan_wps_networks("wlan0mon", 5)
    assert "HomeNet" in res
    assert "AA:BB:CC:DD:EE:FF" in res


def test_scan_wps_ethernet_interface_hint():
    # no output on an ethernet iface -> helpful monitor-mode hint, not a hang
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch("subprocess.run", return_value=_run(stdout="")):
        res = wt.scan_wps_networks("enp0s31f6", 5)
    assert "monitor" in res.lower()
    assert "enp0s31f6" in res


def test_scan_wps_times_out_returns_message():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired("wash", 15)):
        res = wt.scan_wps_networks("wlan0mon", 5)
    assert "timed out" in res.lower()


def test_scan_wps_permission_gate():
    with patch.object(wt, "_has_wireless_admin", return_value=False):
        res = wt.scan_wps_networks("wlan0mon", 5)
    assert "permission" in res.lower()


def test_scan_wps_missing_wash():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value="wash"):
        res = wt.scan_wps_networks("wlan0mon", 5)
    assert "install_wireless_tools" in res
