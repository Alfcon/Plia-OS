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

def test_capture_handshake_reports_failure_when_no_handshake_verified():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_capture_handshake_file", return_value=None):
        out = wt.capture_handshake("wlan0mon", BSSID, "6")
    assert "No WPA handshake captured" in out
    assert "monitor mode" in out          # actionable checklist
    assert "WPA3" in out


def test_capture_handshake_reports_verified_count():
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
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
        cap = wt._capture_handshake_file("wlan0mon", BSSID, "6", prefix_dir="/tmp")
    assert cap == "/tmp/plia_D0DBB7DC1C95-01.cap"
    assert sudo.call_count == 3            # deauth retried, not a single burst
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
    gen = MagicMock(returncode=0, stdout="", stderr="")
    crack = MagicMock(stdout=AIRCRACK_NO_HS, stderr="")

    def fake_run(*cmd, **kwargs):
        return gen if cmd and cmd[0] == "crunch" else crack

    with patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_run", side_effect=fake_run):
        out = wt.crack_handshake_auto(str(cap), BSSID)
    assert "No usable WPA handshake" in out
