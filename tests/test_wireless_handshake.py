"""Handshake verification: a capture file's existence must never be taken as proof.

aircrack-ng's own count is the source of truth — a capture with no EAPOL data has
to be reported as such instead of being handed to the cracker.
"""
from unittest.mock import MagicMock, patch

import modules.wireless_tools as wt

AIRCRACK_NO_HS = (
    "Reading packets, please wait...\n"
    "Opening /tmp/cap-01.cap\n"
    "Read 1788 packets.\n\n"
    "1 potential targets\n\n"
    "Packets contained no EAPOL data; unable to process this AP.\n"
)
AIRCRACK_0 = "   1  D0:DB:B7:DC:1C:95  NetComm 2979              WPA (0 handshake)\n"
AIRCRACK_1 = "   1  D0:DB:B7:DC:1C:95  NetComm 2979              WPA (1 handshake)\n"
AIRCRACK_2 = "   1  D0:DB:B7:DC:1C:95  NetComm 2979              WPA (2 handshakes)\n"
AIRCRACK_OTHER = "   1  AA:BB:CC:DD:EE:FF  Other                     WPA (2 handshakes)\n"

BSSID = "D0:DB:B7:DC:1C:95"


# ---------------------------------------------------------------------------
# parse_handshake_count / handshake_count
# ---------------------------------------------------------------------------

def test_parse_handshake_count_reads_zero_one_and_two():
    assert wt.parse_handshake_count(AIRCRACK_0, BSSID) == 0
    assert wt.parse_handshake_count(AIRCRACK_1, BSSID) == 1
    assert wt.parse_handshake_count(AIRCRACK_2, BSSID) == 2
    assert wt.parse_handshake_count(AIRCRACK_NO_HS, BSSID) == 0
    assert wt.parse_handshake_count("", BSSID) == 0


def test_parse_handshake_count_is_scoped_to_target_bssid():
    # A handshake for another AP must not be credited to the target.
    assert wt.parse_handshake_count(AIRCRACK_OTHER, BSSID) == 0
    assert wt.parse_handshake_count(AIRCRACK_OTHER, "AA:BB:CC:DD:EE:FF") == 2
    # With no bssid given, the best count in the output is used.
    assert wt.parse_handshake_count(AIRCRACK_OTHER) == 2


def test_handshake_count_uses_aircrack_and_handles_missing_file(tmp_path):
    cap = tmp_path / "cap.cap"
    cap.write_text("x")
    with patch.object(wt, "_run", return_value=MagicMock(stdout=AIRCRACK_1, stderr="")):
        assert wt.handshake_count(str(cap), BSSID) == 1
    # Missing file → 0 with no aircrack call.
    with patch.object(wt, "_run") as run:
        assert wt.handshake_count(str(tmp_path / "nope.cap"), BSSID) == 0
    run.assert_not_called()


# ---------------------------------------------------------------------------
# capture_handshake
# ---------------------------------------------------------------------------

def test_capture_handshake_reports_failure_when_no_handshake_verified(tmp_path):
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1}), \
         patch.object(wt, "_capture_handshake_file", return_value=None):
        out = wt.capture_handshake("wlan0mon", BSSID, "6", output_dir=str(tmp_path))
    assert "No WPA handshake captured" in out
    assert "monitor mode" in out          # actionable checklist
    assert "WPA3" in out


def test_capture_handshake_reports_verified_count():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1}), \
         patch.object(wt, "_capture_handshake_file", return_value="/tmp/cap-01.cap"), \
         patch.object(wt, "handshake_count", return_value=1):
        out = wt.capture_handshake("wlan0mon", BSSID, "6")
    assert "Handshake captured (1 handshake)" in out
    assert "/tmp/cap-01.cap" in out


def test_capture_handshake_file_retries_deauth_until_verified():
    proc = MagicMock()
    # 0, 0, then 1 handshake → succeeds on the third attempt.
    with patch.object(wt.subprocess, "Popen", return_value=proc), \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo") as sudo, \
         patch.object(wt, "_count_handshakes_live", side_effect=[0, 0, 1]):
        cap = wt._capture_handshake_file(
            "wlan0mon", BSSID, "6", prefix_dir="/tmp",
            prefix="/tmp/plia_D0DBB7DC1C95")
    assert cap == "/tmp/plia_D0DBB7DC1C95-01.cap"
    assert sudo.call_count == 2            # deauth retried, not a single burst
    proc.terminate.assert_called_once()


def test_capture_handshake_file_returns_none_when_never_verified():
    proc = MagicMock()
    with patch.object(wt.subprocess, "Popen", return_value=proc), \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo"), \
         patch.object(wt, "_count_handshakes_live", return_value=0):
        cap = wt._capture_handshake_file("wlan0mon", BSSID, "6", prefix_dir="/tmp")
    assert cap is None


# ---------------------------------------------------------------------------
# crack tools surface "no EAPOL" instead of raw aircrack noise
# ---------------------------------------------------------------------------

def test_crack_wordlist_reports_missing_handshake(tmp_path):
    cap = tmp_path / "cap.cap"; cap.write_text("x")
    wl = tmp_path / "words.txt"; wl.write_text("123456\n")
    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_run", return_value=MagicMock(stdout=AIRCRACK_NO_HS, stderr="")):
        out = wt.crack_handshake_wordlist(str(cap), BSSID, str(wl))
    assert "No usable WPA handshake" in out
    assert "capture_handshake" in out
    assert "Packets contained no EAPOL" in out


def test_crack_rockyou_reports_missing_handshake(tmp_path):
    cap = tmp_path / "cap.cap"; cap.write_text("x")
    wl = tmp_path / "rockyou.txt"; wl.write_text("123456\n")
    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_find_rockyou", return_value=(str(wl), None)), \
         patch.object(wt, "_run", return_value=MagicMock(stdout=AIRCRACK_NO_HS, stderr="")):
        out = wt.crack_handshake_rockyou(str(cap), BSSID)
    assert "No usable WPA handshake" in out


def test_crack_wordlist_still_returns_found_key(tmp_path):
    cap = tmp_path / "cap.cap"; cap.write_text("x")
    wl = tmp_path / "words.txt"; wl.write_text("123456\n")
    found = "KEY FOUND! [ hunter2 ]"
    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_run", return_value=MagicMock(stdout=found, stderr="")):
        out = wt.crack_handshake_wordlist(str(cap), BSSID, str(wl))
    assert out == found


def test_crack_wordlist_still_reports_plain_miss(tmp_path):
    cap = tmp_path / "cap.cap"; cap.write_text("x")
    wl = tmp_path / "words.txt"; wl.write_text("123456\n")
    miss = "\n".join(f"  {i}  1234/10000 keys tested" for i in range(40))
    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_run", return_value=MagicMock(stdout=miss, stderr="")):
        out = wt.crack_handshake_wordlist(str(cap), BSSID, str(wl))
    assert "No usable WPA handshake" not in out
    assert "keys tested" in out


def test_crack_auto_reports_missing_handshake(tmp_path):
    cap = tmp_path / "cap.cap"; cap.write_text("x")
    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_stream_auto_crack", return_value=AIRCRACK_NO_HS):
        out = wt.crack_handshake_auto(str(cap), BSSID)
    assert "No usable WPA handshake" in out


# ---------------------------------------------------------------------------
# capture_handshake: monitor mode lifecycle + client preflight
# ---------------------------------------------------------------------------

def test_capture_handshake_starts_and_restores_monitor_mode():
    ok = MagicMock(returncode=0, stdout="", stderr="")
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", side_effect=[False, True]), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=ok) as sudo, \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1}), \
         patch.object(wt, "_capture_handshake_file", return_value="/tmp/cap-01.cap"), \
         patch.object(wt, "handshake_count", return_value=1), \
         patch.object(wt, "_stop_monitor") as stop:
        out = wt.capture_handshake("wlan0", BSSID, "6")
    assert "Handshake captured" in out
    assert "monitor mode was stopped" in out.lower()
    sudo.assert_called_once_with("airmon-ng", "start", "wlan0", timeout=15)
    stop.assert_called_once_with("wlan0mon")


def test_capture_handshake_without_clients_never_starts_capture():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value="No clients are associated with ..."), \
         patch.object(wt, "_capture_handshake_file") as capture:
        out = wt.capture_handshake("wlan0mon", BSSID, "6")
    assert "No clients are associated" in out
    capture.assert_not_called()


def test_preflight_target_explains_idle_bssid_and_points_at_alternate():
    other = "A2:AF:11:34:43:68"
    aps = [
        {"ssid": "Contarino", "bssid": BSSID, "channel": "11", "enc": "WPA2", "power": -30},
        {"ssid": "Contarino", "bssid": other, "channel": "40", "enc": "WPA2", "power": -45},
    ]
    stations = [{"station": "AA:BB:CC:DD:EE:FF", "power": -50, "ap": other}]
    with patch.object(wt, "_scan_network", return_value=(aps, stations)):
        out = wt._preflight_target("wlan0mon", BSSID, "11")
    assert isinstance(out, str)
    assert "No clients are associated" in out
    assert other in out
    assert "ch 40" in out


def test_preflight_target_passes_with_actual_channel_and_clients():
    aps = [{"ssid": "Contarino", "bssid": BSSID, "channel": "11",
            "enc": "WPA2", "power": -30}]
    stations = [{"station": "AA:BB:CC:DD:EE:FF", "power": -50, "ap": BSSID}]
    with patch.object(wt, "_scan_network", return_value=(aps, stations)):
        out = wt._preflight_target("wlan0mon", BSSID, "11")
    assert out == {"channel": "11", "ssid": "Contarino", "clients": 1,
                   "client_macs": ["AA:BB:CC:DD:EE:FF"]}


def test_parse_stations_reads_associated_clients(tmp_path):
    csv = tmp_path / "scan-01.csv"
    csv.write_text(
        "BSSID, First time seen, Last time seen, channel, Speed, Privacy\n"
        "\n"
        "Station MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs\n"
        f"AA:BB:CC:DD:EE:FF, 1, 2, -45, 10, {BSSID}, Contarino\n"
        "11:22:33:44:55:66, 1, 2, -70, 3, (not associated), \n"
    )
    rows = wt._parse_stations(csv)
    assert rows[0] == {"station": "AA:BB:CC:DD:EE:FF", "power": -45, "ap": BSSID}
    assert rows[1]["ap"] == "(not associated)"


def test_capture_handshake_explains_empty_capture(tmp_path):
    cap = tmp_path / f"plia_{BSSID.replace(':', '')}_1700000000-01.cap"
    cap.write_bytes(b"\x00" * 24)
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1}), \
         patch.object(wt, "_capture_handshake_file", return_value=None), \
         patch.object(wt.time, "time", return_value=1700000000):
        out = wt.capture_handshake("wlan0mon", BSSID, "6", output_dir=str(tmp_path))
    assert "capture file is empty" in out


def test_format_ap_table_includes_band():
    rows = [
        {"ssid": "Home", "bssid": BSSID, "channel": "6", "power": -40, "enc": "WPA2"},
        {"ssid": "Home5", "bssid": "AA:BB:CC:DD:EE:FF", "channel": "149",
         "power": -50, "enc": "WPA2"},
    ]
    out = wt._format_ap_table(rows)
    assert "BAND" in out
    assert "2.4 GHz" in out
    assert "5 GHz" in out


def test_capture_handshake_uses_unique_prefix_by_default():
    proc = MagicMock()
    with patch.object(wt.subprocess, "Popen", return_value=proc) as popen, \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo"), \
         patch.object(wt, "_count_handshakes_live", return_value=1):
        cap = wt._capture_handshake_file("wlan0mon", BSSID, "6", prefix_dir="/tmp")
    cmd = popen.call_args.args[0]
    prefix = cmd[cmd.index("-w") + 1]
    assert prefix.startswith("/tmp/plia_D0DBB7DC1C95_")
    assert prefix != "/tmp/plia_D0DBB7DC1C95"
    assert cap == prefix + "-01.cap"


def test_capture_handshake_retries_after_killing_interfering_processes():
    ok = MagicMock(returncode=0, stdout="", stderr="")
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", side_effect=[False, True, True]), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=ok) as sudo, \
         patch.object(wt, "_preflight_target",
                      side_effect=["not seen", {"channel": "6", "ssid": "x", "clients": 1}]), \
         patch.object(wt, "_capture_handshake_file", return_value="/tmp/cap-01.cap"), \
         patch.object(wt, "handshake_count", return_value=1), \
         patch.object(wt, "_stop_monitor"), \
         patch.object(wt.time, "sleep"):
        out = wt.capture_handshake("wlan0", BSSID, "6")
    flat = [c.args for c in sudo.call_args_list]
    assert ("airmon-ng", "start", "wlan0") in flat
    assert ("airmon-ng", "check", "kill") in flat
    assert "check kill" in out
    assert "Handshake captured" in out


def test_capture_handshake_does_not_kill_nm_for_external_monitor():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target", return_value="not seen"), \
         patch.object(wt, "_sudo") as sudo, \
         patch.object(wt, "_capture_handshake_file") as capture:
        out = wt.capture_handshake("wlan0mon", BSSID, "6")
    assert "not seen" in out
    capture.assert_not_called()
    sudo.assert_not_called()


def test_capture_handshake_file_sends_unicast_deauth_to_known_clients():
    proc = MagicMock()
    clients = ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
    with patch.object(wt.subprocess, "Popen", return_value=proc), \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo") as sudo, \
         patch.object(wt, "_count_handshakes_live", side_effect=[0, 1]):
        cap = wt._capture_handshake_file(
            "wlan0mon", BSSID, "6", prefix_dir="/tmp",
            prefix="/tmp/plia_test", client_macs=clients)
    assert cap == "/tmp/plia_test-01.cap"
    calls = [c.args for c in sudo.call_args_list]
    assert ("aireplay-ng", "-0", "3", "--deauth-rc", "1",
            "-a", BSSID, "-c", clients[0], "wlan0mon") in calls
    assert ("aireplay-ng", "-0", "3", "--deauth-rc", "1",
            "-a", BSSID, "-c", clients[1], "wlan0mon") in calls
    assert ("aireplay-ng", "-0", "3", "--deauth-rc", "1",
            "-a", BSSID, "wlan0mon") in calls


def test_capture_handshake_reports_partial_eapol(tmp_path):
    cap = tmp_path / f"plia_{BSSID.replace(':', '')}_1700000001-01.cap"
    cap.write_bytes(b"\x00" * 500)
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1,
                                    "client_macs": ["AA:BB:CC:DD:EE:FF"]}), \
         patch.object(wt, "_capture_handshake_file", return_value=None), \
         patch.object(wt, "_eapol_frame_count", return_value=3), \
         patch.object(wt.time, "time", return_value=1700000001):
        out = wt.capture_handshake("wlan0mon", BSSID, "6", output_dir=str(tmp_path))
    assert "Only 3 EAPOL" in out
    assert "M2" in out


def test_capture_handshake_passive_skips_deauth():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1,
                                    "client_macs": ["AA:BB:CC:DD:EE:FF"]}), \
         patch.object(wt, "_capture_handshake_file", return_value="/tmp/cap-01.cap") as capture, \
         patch.object(wt, "handshake_count", return_value=1):
        out = wt.capture_handshake("wlan0mon", BSSID, "6", passive=True)
    kwargs = capture.call_args.kwargs
    assert kwargs["deauth"] is False
    assert kwargs["passive_seconds"] == 90
    assert "Passive capture" in out
    assert "Handshake captured" in out


def test_capture_handshake_file_passive_mode_sends_no_deauth():
    proc = MagicMock()
    with patch.object(wt.subprocess, "Popen", return_value=proc), \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo") as sudo, \
         patch.object(wt, "_count_handshakes_live", side_effect=[0, 1]):
        cap = wt._capture_handshake_file(
            "wlan0mon", BSSID, "6", prefix_dir="/tmp", prefix="/tmp/plia_passive",
            deauth=False, passive_seconds=30)
    sudo.assert_not_called()
    assert cap == "/tmp/plia_passive-01.cap"


def test_capture_handshake_explains_deauth_was_sent_but_ignored(tmp_path):
    cap = tmp_path / f"plia_{BSSID.replace(':', '')}_1700000002-01.cap"
    cap.write_bytes(b"\x00" * 500)
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_preflight_target",
                      return_value={"channel": "6", "ssid": "Test", "clients": 1,
                                    "client_macs": ["AA:BB:CC:DD:EE:FF"]}), \
         patch.object(wt, "_capture_handshake_file", return_value=None), \
         patch.object(wt, "_eapol_frame_count", return_value=0), \
         patch.object(wt, "_deauth_frame_count", return_value=1536), \
         patch.object(wt.time, "time", return_value=1700000002):
        out = wt.capture_handshake("wlan0mon", BSSID, "6", output_dir=str(tmp_path))
    assert "Deauth was transmitted (1536" in out
    assert "PMF" in out
    assert "passive=true" in out


def test_airodump_scans_both_bands():
    proc = MagicMock()
    with patch.object(wt.subprocess, "Popen", return_value=proc) as popen, \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo"), \
         patch.object(wt, "_count_handshakes_live", return_value=1):
        wt._capture_handshake_file("wlan0mon", BSSID, "40",
                                   prefix="/tmp/plia_band_test", attempts=1)
    cmd = popen.call_args.args[0]
    assert cmd[cmd.index("--band") + 1] == "abg"

    with patch.object(wt.subprocess, "Popen", return_value=proc) as popen2, \
         patch.object(wt.time, "sleep"):
        wt._scan_network("wlan0mon", 1)
    cmd2 = popen2.call_args.args[0]
    assert cmd2[cmd2.index("--band") + 1] == "abg"


def test_preflight_lists_other_bssids_even_without_clients():
    other = "A2:AF:11:34:43:68"
    aps = [
        {"ssid": "Contarino", "bssid": BSSID, "channel": "11", "enc": "WPA2", "power": -30},
        {"ssid": "Contarino", "bssid": other, "channel": "40", "enc": "WPA2", "power": -45},
    ]
    with patch.object(wt, "_scan_network", return_value=(aps, [])):
        out = wt._preflight_target("wlan0mon", BSSID, "11")
    assert isinstance(out, str)
    assert "Other BSSIDs" in out
    assert other in out
    assert "5 GHz" in out


def test_capture_handshake_refuses_non_injecting_adapter():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_iface_driver", return_value="iwlwifi"):
        out = wt.capture_handshake("wlp0s20f3", BSSID, "40")
    assert "cannot inject" in out
    assert "USB" in out
    assert "passive=true" in out


def test_capture_handshake_file_uses_requested_deauth_reason():
    proc = MagicMock()
    with patch.object(wt.subprocess, "Popen", return_value=proc), \
         patch.object(wt.time, "sleep"), \
         patch.object(wt, "_sudo") as sudo, \
         patch.object(wt, "_count_handshakes_live", return_value=1):
        wt._capture_handshake_file("wlan0mon", BSSID, "6", prefix="/tmp/plia_rc",
                                   attempts=1, deauth_rc=3)
    assert ("aireplay-ng", "-0", "3", "--deauth-rc", "3",
            "-a", BSSID, "wlan0mon") in [c.args for c in sudo.call_args_list]


def test_auto_crack_covers_8_to_15_digits():
    assert wt._AUTO_WORDLIST_MIN == "8"
    assert wt._AUTO_WORDLIST_MAX == "15"
    assert wt._AUTO_WORDLIST_CHARSET == "0123456789"


def test_find_target_ap_by_bssid():
    ap = {"ssid": "Contarino", "bssid": "A2:AF:11:34:43:68",
          "channel": "40", "enc": "WPA2", "power": -30}
    assert wt._find_target_ap("a2:af:11:34:43:68", [ap]) is ap
    assert wt._find_target_ap("Contarino", [ap]) is ap
    assert wt._find_target_ap("A2:AF:11:24:43:68", [ap]) is None


def test_create_wordlist_refuses_huge_mixed_lists():
    with patch.object(wt, "_bin_missing", return_value=None):
        out = wt.create_wordlist(8, 15)
    assert "Refusing" in out
    assert "too large" in out
    assert "crack_handshake_auto" in out


def test_create_wordlist_allows_small_charset():
    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_run", return_value=MagicMock(returncode=0, stderr="")) as run:
        out = wt.create_wordlist(2, 2, "ab", "/tmp/plia_small.txt")
    assert "Wordlist saved" in out
    assert run.call_args.args[:4] == ("crunch", "2", "2", "ab")
