"""attack_wps: the fast attack first, a resumable PIN attack second, and a timeout
that reports what reaver found instead of a bare "timed out"."""
from unittest.mock import MagicMock, patch

import modules.wireless_tools as wt

BSSID = "AA:BB:CC:DD:EE:FF"


def _admin(**extra):
    """Patch the preflight so only the reaver behaviour under test matters."""
    return (
        patch.object(wt, "_has_wireless_admin", return_value=True),
        patch.object(wt, "_bin_missing", return_value=None),
        patch.object(wt, "_wps_session_file", return_value=__import__("pathlib").Path("/tmp/plia_test_wps")),
    )


def _run_attack(reaver_outputs, **kwargs):
    """Call attack_wps with `_reaver_run` returning `reaver_outputs` in order."""
    calls = []

    def fake_reaver(interface, bssid, channel, timeout=120, *, args=(), session=None, stream_tool=""):
        calls.append({"timeout": timeout, "args": tuple(args), "stream_tool": stream_tool})
        return reaver_outputs.pop(0) if reaver_outputs else ""

    a, b, c = _admin()
    with a, b, c, \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_emit_wps_extend"), \
         patch.object(wt, "_reaver_run", side_effect=fake_reaver):
        return wt.attack_wps("wlan0mon", BSSID, "6", **kwargs), calls


def test_pixie_dust_is_tried_first_and_wins_fast():
    out, calls = _run_attack(["WPS PIN: '12345678'\nWPA PSK: 'goldenkey'"])
    assert "Recovered via Pixie Dust" in out
    assert "goldenkey" in out
    assert calls[0]["args"] == ("-K", "1")          # pixie dust, not the PIN brute force
    assert len(calls) == 1                          # PIN attack never needed


def test_pin_attack_runs_after_pixie_dust_fails():
    out, calls = _run_attack(["[+] Pixie Dust failed", "WPA PSK: 'foundit'"])
    assert "Recovered via WPS PIN" in out
    assert "foundit" in out
    assert calls[0]["args"] == ("-K", "1")
    assert calls[1]["args"] == ()                   # plain PIN attack


def test_timeout_reports_progress_and_how_to_resume():
    # This is the bug: a 120s cap on an hours-long attack used to discard reaver's
    # output and answer with a bare "timed out after 120s".
    partial = "\n".join(f"[+] Trying pin 1234{i}" for i in range(5))
    partial += "\n[!] WPS transaction failed"
    # _reaver_run returns stdout + stderr, and our timeout lands in stderr.
    out, calls = _run_attack(["nothing from pixie", partial + "\ntimed out after 120s"])
    assert out.strip() != "timed out after 120s"       # not the bare wrapper message
    assert "Trying pin 1234" in out                    # partial output is reported
    assert "takes hours" in out
    assert "resume" in out.lower() or "continue" in out.lower()
    assert [c["timeout"] for c in calls] == [90, 300, 900, 1800]
    assert all(c["stream_tool"] == "attack_wps" for c in calls)  # streams to chat


def test_timeout_seconds_is_honoured_and_bounded():
    _, calls = _run_attack(["x", "y"], timeout_seconds=1800)
    assert calls[0]["timeout"] == 90                  # pixie dust capped at 90s
    assert calls[1]["timeout"] == 1800                # PIN phase uses the budget
    _, calls = _run_attack(["x", "y"], timeout_seconds=99999)
    assert calls[1]["timeout"] == 3600                # bounded

    for bad in (0, -5, "nonsense"):
        _, calls = _run_attack(["x", "y"], timeout_seconds=bad)
        assert calls[1]["timeout"] == 300, bad        # 0/nonsense = automatic stages


def test_pixie_dust_can_be_disabled():
    _, calls = _run_attack(["x", "y", "z"], pixie_dust=False)
    assert [c["timeout"] for c in calls] == [300, 900, 1800]
    assert calls[0]["args"] == ()


def test_locked_ap_is_called_out():
    out, _ = _run_attack(["nothing", "[!] WPS PIN: AP is locked (Lck: Yes)"])
    assert "locked" in out.lower()


def test_attack_wps_validates_arguments():
    assert wt.attack_wps("wlan0mon", BSSID, "6", pixie_dust=False) is not None
    with patch.object(wt, "_has_wireless_admin", return_value=False):
        assert "Permission denied" in wt.attack_wps("wlan0mon", BSSID, "6")
    with patch.object(wt, "_has_wireless_admin", return_value=True):
        assert "required" in wt.attack_wps("", BSSID, "6")
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value="reaver"):
        assert "install_wireless_tools" in wt.attack_wps("wlan0mon", BSSID, "6")


def test_attack_wps_starts_monitor_mode_for_managed_interface():
    ok = MagicMock(returncode=0, stdout="", stderr="")
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_wps_session_file",
                      return_value=__import__("pathlib").Path("/tmp/plia_test_wps")), \
         patch.object(wt, "_is_monitor_iface", side_effect=[False, True]), \
         patch.object(wt, "_detect_monitor_interface", side_effect=[None, "wlan0mon"]), \
         patch.object(wt, "_sudo", return_value=ok) as sudo, \
         patch.object(wt, "_reaver_run", return_value="WPA PSK: 'wpskey'") as reaver, \
         patch.object(wt, "_stop_monitor") as stop:
        out = wt.attack_wps("wlan0", BSSID, "6")
    assert "Recovered via Pixie Dust" in out
    sudo.assert_called_once_with("airmon-ng", "start", "wlan0", timeout=15)
    assert reaver.call_args.args[0] == "wlan0mon"
    stop.assert_called_once_with("wlan0mon")


def test_automatic_stages_are_300_900_1800_then_prompt_for_extension():
    emitted = []
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_wps_session_file",
                      return_value=__import__("pathlib").Path("/tmp/plia_test_wps")), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_reaver_run", return_value="") as reaver, \
         patch.object(wt, "_emit_wps_extend",
                      side_effect=lambda *a: emitted.append(a)):
        out = wt.attack_wps("wlan0mon", BSSID, "6")
    assert [c.args[3] for c in reaver.call_args_list] == [90, 300, 900, 1800]
    assert emitted == [("wlan0mon", BSSID, "6")]
    assert "Automatic WPS PIN stages complete" in out
    assert "Do you want to extend it?" in out
    assert "timeout_seconds=3600" in out


def test_explicit_extension_runs_one_budget_then_asks_again():
    emitted = []
    with patch.object(wt, "_has_wireless_admin", return_value=True), \
         patch.object(wt, "_bin_missing", return_value=None), \
         patch.object(wt, "_wps_session_file",
                      return_value=__import__("pathlib").Path("/tmp/plia_test_wps")), \
         patch.object(wt, "_is_monitor_iface", return_value=True), \
         patch.object(wt, "_reaver_run", return_value="") as reaver, \
         patch.object(wt, "_emit_wps_extend",
                      side_effect=lambda *a: emitted.append(a)):
        out = wt.attack_wps("wlan0mon", BSSID, "6", timeout_seconds=3600)
    assert [c.args[3] for c in reaver.call_args_list] == [90, 3600]
    assert emitted == [("wlan0mon", BSSID, "6")]
    assert "WPS PIN extension of 3600s" in out
    assert "Do you want to extend it?" in out
