from unittest.mock import MagicMock, patch

import modules.wireless_tools as wt


def _sudo_ok():
    return MagicMock(returncode=0, stdout="", stderr="")


def _ap(ssid="", bssid="AA:BB:CC:DD:EE:01", channel="6"):
    return {"ssid": ssid, "bssid": bssid, "channel": channel, "enc": "WPA2", "power": -50}


def test_reveal_denied_without_admin():
    with patch.object(wt, "_has_wireless_admin", return_value=False):
        out = wt.reveal_hidden_ssid()
    assert "permission" in out.lower()


def test_reveal_missing_tools():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", side_effect=lambda b: b if b == "airodump-ng" else None):
        out = wt.reveal_hidden_ssid()
    assert "Missing tools" in out
    assert "airodump-ng" in out


def test_reveal_no_hidden_networks():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_run", return_value=([_ap(ssid="Visible")], {})), \
         patch.object(wt, "_stop_monitor"):
        out = wt.reveal_hidden_ssid()
    assert "No hidden networks found" in out


def test_reveal_multiple_hidden_networks():
    aps1 = [
        _ap(bssid="AA:BB:CC:DD:EE:01"),
        _ap(bssid="AA:BB:CC:DD:EE:02", channel="11"),
        _ap(ssid="Visible", bssid="AA:BB:CC:DD:EE:03", channel="1"),
    ]
    aps2 = [
        _ap(ssid="HomeNet", bssid="AA:BB:CC:DD:EE:01"),
        _ap(ssid="OfficeNet", bssid="AA:BB:CC:DD:EE:02", channel="11"),
    ]
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_run", side_effect=[(aps1, {}), (aps2, {})]) as run, \
         patch.object(wt, "_stop_monitor"):
        out = wt.reveal_hidden_ssid()
    assert "Found 2 hidden network(s)" in out
    assert "AA:BB:CC:DD:EE:01" in out and "HomeNet" in out
    assert "AA:BB:CC:DD:EE:02" in out and "OfficeNet" in out
    # both hidden BSSIDs are deauthed in the second capture
    assert run.call_args_list[1].kwargs["deauth_bssids"] == [
        "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02",
    ]


def test_reveal_probe_candidates():
    aps1 = [_ap()]
    probes2 = {"AA:BB:CC:DD:EE:01": {"HomeNet"}}
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_run", side_effect=[(aps1, {}), ([], probes2)]), \
         patch.object(wt, "_stop_monitor"):
        out = wt.reveal_hidden_ssid()
    assert "candidates" in out
    assert "HomeNet" in out


def test_reveal_not_revealed():
    aps1 = [_ap()]
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_detect_wifi_interface", return_value="wlan0"), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=_sudo_ok()), \
         patch.object(wt, "_airodump_run", side_effect=[(aps1, {}), ([], {})]), \
         patch.object(wt, "_stop_monitor"):
        out = wt.reveal_hidden_ssid()
    assert "not revealed" in out


def test_parse_airodump_csv_aps_and_probes(tmp_path):
    csv = tmp_path / "scan-01.csv"
    csv.write_text(
        "BSSID, First time seen, Last time seen, channel, Speed, Privacy, Cipher, Authentication, Power, # beacons, # IV, LAN IP, ID-length, ESSID, Key\n"
        "AA:BB:CC:DD:EE:01, 2020-01-01 00:00:00, 2020-01-01 00:00:15, 6, 54, WPA2, CCMP, PSK, -40, 100, 0, 0.0.0.0, 0, ,\n"
        "AA:BB:CC:DD:EE:02, 2020-01-01 00:00:00, 2020-01-01 00:00:15, 11, 54, WPA2, CCMP, PSK, -60, 100, 0, 0.0.0.0, 8, HomeNet,\n"
        "Station MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs\n"
        "11:22:33:44:55:66, 2020-01-01 00:00:00, 2020-01-01 00:00:15, -30, 50, AA:BB:CC:DD:EE:01, HomeNet,OfficeNet\n"
    )
    aps, probes = wt._parse_airodump_csv(csv)
    assert [a["ssid"] for a in aps] == ["", "HomeNet"]
    assert probes == {"AA:BB:CC:DD:EE:01": {"HomeNet", "OfficeNet"}}
