import json
import pytest
from unittest.mock import patch, MagicMock


def _ifaces_mock(interfaces_json: bytes):
    m = MagicMock()
    m.stdout = interfaces_json
    m.returncode = 0
    return m


def _run_ok():
    m = MagicMock()
    m.returncode = 0
    m.stderr = ""
    return m


def _run_fail(stderr="Operation failed"):
    m = MagicMock()
    m.returncode = 1
    m.stderr = stderr
    return m


IFACES = json.dumps([
    {"ifname": "lo",    "link_type": "loopback", "flags": ["LOOPBACK", "UP"], "address": "00:00:00:00:00:00"},
    {"ifname": "eth0",  "link_type": "ether",    "flags": ["UP", "LOWER_UP"], "address": "aa:bb:cc:dd:ee:ff"},
    {"ifname": "wlan0", "link_type": "ether",    "flags": [],                  "address": "11:22:33:44:55:66"},
]).encode()


# --- show_mac ---

def test_show_mac_auto_detects_first_up_ether():
    from modules.network_tools import show_mac
    with patch("subprocess.run", return_value=_ifaces_mock(IFACES)):
        result = show_mac("")
    assert "eth0" in result
    assert "aa:bb:cc:dd:ee:ff" in result


def test_show_mac_named_interface():
    from modules.network_tools import show_mac
    with patch("subprocess.run", return_value=_ifaces_mock(IFACES)):
        result = show_mac("wlan0")
    assert "wlan0" in result
    assert "11:22:33:44:55:66" in result


def test_show_mac_unknown_interface_returns_error():
    from modules.network_tools import show_mac
    with patch("subprocess.run", return_value=_ifaces_mock(IFACES)):
        result = show_mac("eth99")
    assert "not found" in result.lower()


def test_show_mac_no_active_interface():
    from modules.network_tools import show_mac
    no_ether = json.dumps([
        {"ifname": "lo", "link_type": "loopback", "flags": ["LOOPBACK", "UP"], "address": "00:00:00:00:00:00"},
    ]).encode()
    with patch("subprocess.run", return_value=_ifaces_mock(no_ether)):
        result = show_mac("")
    assert "no active" in result.lower()


# --- _random_mac ---

def test_random_mac_locally_administered_unicast():
    from modules.network_tools import _random_mac
    for _ in range(50):
        mac = _random_mac()
        first_octet = int(mac.split(":")[0], 16)
        assert first_octet & 0x01 == 0, "Must be unicast (bit 0 = 0)"
        assert first_octet & 0x02 != 0, "Must be locally administered (bit 1 = 1)"


# --- randomize_mac ---

def test_randomize_mac_saves_original_and_shows_old_mac():
    from modules.network_tools import randomize_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = None
    # 4 calls: 1 resolve + 3 ip link (down/address/up)
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES), _run_ok(), _run_ok(), _run_ok()]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store), \
         patch("modules.network_tools._has_mac_admin", return_value=True):
        result = randomize_mac("")
    mock_store.remember.assert_called_once_with("original_mac_eth0", "aa:bb:cc:dd:ee:ff")
    assert "eth0" in result
    assert "aa:bb:cc:dd:ee:ff" in result  # old MAC shown in output


def test_randomize_mac_does_not_overwrite_stored_original():
    from modules.network_tools import randomize_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = "original:was:here"
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES), _run_ok(), _run_ok(), _run_ok()]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store):
        randomize_mac("")
    mock_store.remember.assert_not_called()


def test_randomize_mac_ip_fail_returns_error():
    from modules.network_tools import randomize_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = None
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES), _run_fail("SIOCSIFHWADDR: Operation not permitted")]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store):
        result = randomize_mac("")
    assert "failed" in result.lower()


# --- set_mac ---

def test_set_mac_valid_saves_original_and_succeeds():
    from modules.network_tools import set_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = None
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES), _run_ok(), _run_ok(), _run_ok()]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store), \
         patch("modules.network_tools._has_mac_admin", return_value=True):
        result = set_mac("eth0", "AA:BB:CC:DD:EE:FF")
    assert "AA:BB:CC:DD:EE:FF" in result
    mock_store.remember.assert_called_once_with("original_mac_eth0", "aa:bb:cc:dd:ee:ff")


def test_set_mac_invalid_format_no_subprocess_call():
    from modules.network_tools import set_mac
    with patch("subprocess.run") as mock_run:
        result = set_mac("eth0", "not-a-mac")
    mock_run.assert_not_called()
    assert "invalid mac" in result.lower()


def test_set_mac_does_not_overwrite_original_if_already_stored():
    from modules.network_tools import set_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = "already:stored:original"
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES), _run_ok(), _run_ok(), _run_ok()]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store):
        set_mac("eth0", "DE:AD:BE:EF:00:01")
    mock_store.remember.assert_not_called()


# --- restore_mac ---

def test_restore_mac_applies_stored_original():
    from modules.network_tools import restore_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = "aa:bb:cc:dd:ee:ff"
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES), _run_ok(), _run_ok(), _run_ok()]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store), \
         patch("modules.network_tools._has_mac_admin", return_value=True):
        result = restore_mac("")
    assert "aa:bb:cc:dd:ee:ff" in result
    assert "restored" in result.lower()


def test_restore_mac_no_original_returns_error_without_ip_call():
    from modules.network_tools import restore_mac
    mock_store = MagicMock()
    mock_store.get_fact.return_value = None
    # only 1 subprocess call (interface resolution) — no ip link cmds
    with patch("subprocess.run", side_effect=[_ifaces_mock(IFACES)]), \
         patch("modules.network_tools.get_memory_store", return_value=mock_store):
        result = restore_mac("")
    assert "no original" in result.lower()


# --- USB WiFi dongle enable/disable ---

def _dongle_present(name="wlx8c882b000d0f"):
    return patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3", name])


def _nmcli_status(stdout):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def test_list_wifi_interfaces_filters_wifi_and_keeps_colons_in_connection():
    from modules.network_tools import list_wifi_interfaces
    status = _nmcli_status(
        "enp3s0:ethernet:connected:Wired 1\n"
        "wlp0s20f3:wifi:connected:Cafe:5G\n"
        "p2p-dev-wlp0s20f3:wifi-p2p:disconnected:\n"
    )
    with patch("subprocess.run", return_value=status):
        out = list_wifi_interfaces()
    assert "enp3s0" not in out
    assert "Cafe:5G" in out
    assert "p2p-dev-wlp0s20f3" in out
    assert "—" in out


def test_list_wifi_interfaces_nmcli_unavailable():
    from modules.network_tools import list_wifi_interfaces
    with patch("subprocess.run", side_effect=FileNotFoundError("nmcli")):
        assert list_wifi_interfaces() == "nmcli not available."


def test_wifi_device_names_excludes_p2p():
    from modules.network_tools import _wifi_device_names
    status = _nmcli_status(
        "wlp0s20f3:wifi:connected:Home\n"
        "wlx8c882b000d0f:wifi:unmanaged:\n"
        "p2p-dev-wlp0s20f3:wifi-p2p:disconnected:\n"
    )
    with patch("subprocess.run", return_value=status):
        assert _wifi_device_names() == ["wlp0s20f3", "wlx8c882b000d0f"]


def test_wifi_device_names_nmcli_failure_raises():
    from modules.network_tools import _wifi_device_names
    with patch("subprocess.run", return_value=_run_fail("Error: NetworkManager is not running.")):
        with pytest.raises(ValueError, match="nmcli not available"):
            _wifi_device_names()


def test_disable_wifi_dongle_reports_nmcli_unavailable_not_missing_dongle():
    from modules.network_tools import disable_wifi_dongle
    with patch("subprocess.run", return_value=_run_fail("Error: NetworkManager is not running.")) as mock_run:
        out = disable_wifi_dongle()
    assert out == "nmcli not available."
    assert mock_run.call_count == 1


def test_enable_wifi_dongle_unknown_interface_runs_no_nmcli_actions():
    from modules.network_tools import enable_wifi_dongle
    with _dongle_present(), patch("subprocess.run") as mock_run:
        out = enable_wifi_dongle("wlan9")
    assert out == "WiFi interface 'wlan9' not found."
    mock_run.assert_not_called()


def test_enable_wifi_dongle_connect_timeout_reported_as_warning():
    import subprocess
    from modules.network_tools import enable_wifi_dongle
    timeout = subprocess.TimeoutExpired(["nmcli", "device", "connect", "wlx8c882b000d0f"], 45)
    with _dongle_present(), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_ok(), timeout]):
        out = enable_wifi_dongle("wlx8c882b000d0f")
    assert "with warnings" in out
    assert "timed out after 45s" in out


def test_detect_dongle_picks_usb_wifi():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3", "wlx8c882b000d0f"]), \
         patch("modules.network_tools._is_usb_iface", side_effect=lambda n: n.startswith("wlx")):
        assert _detect_dongle() == "wlx8c882b000d0f"


def test_detect_dongle_explicit_interface_skips_usb_detection():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3", "wlxABC"]), \
         patch("modules.network_tools._is_usb_iface") as usb:
        assert _detect_dongle("wlxABC") == "wlxABC"
        usb.assert_not_called()


def test_detect_dongle_explicit_unknown_interface_raises():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3"]):
        with pytest.raises(ValueError, match="'wlan9' not found"):
            _detect_dongle("wlan9")


def test_detect_dongle_none_present_raises():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3"]), \
         patch("modules.network_tools._is_usb_iface", return_value=False):
        with pytest.raises(ValueError, match="No USB WiFi dongle"):
            _detect_dongle()


def test_detect_dongle_multiple_usb_raises():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlx111", "wlx222"]), \
         patch("modules.network_tools._is_usb_iface", return_value=True):
        with pytest.raises(ValueError, match="Multiple USB WiFi"):
            _detect_dongle()


def test_disable_wifi_dongle_disconnects_and_sets_autoconnect():
    from modules.network_tools import disable_wifi_dongle
    with _dongle_present(), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_ok()]) as mock_run:
        out = disable_wifi_dongle("wlx8c882b000d0f")
    assert "disabled" in out.lower()
    assert mock_run.call_args_list[0].args[0] == ["nmcli", "device", "disconnect", "wlx8c882b000d0f"]
    assert mock_run.call_args_list[1].args[0] == ["nmcli", "device", "set", "wlx8c882b000d0f", "autoconnect", "no"]


def test_enable_wifi_dongle_manages_autoconnects_and_connects():
    from modules.network_tools import enable_wifi_dongle
    with _dongle_present(), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_ok(), _run_ok()]) as mock_run:
        out = enable_wifi_dongle("wlx8c882b000d0f")
    assert "enabled" in out.lower()
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds[0] == ["nmcli", "device", "set", "wlx8c882b000d0f", "managed", "yes"]
    assert cmds[1] == ["nmcli", "device", "set", "wlx8c882b000d0f", "autoconnect", "yes"]
    assert cmds[2] == ["nmcli", "device", "connect", "wlx8c882b000d0f"]


def test_enable_wifi_dongle_reports_warning_on_failure():
    from modules.network_tools import enable_wifi_dongle
    with _dongle_present(), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_ok(), _run_fail("device not ready")]):
        out = enable_wifi_dongle("wlx8c882b000d0f")
    assert "warning" in out.lower()
    assert "device not ready" in out


def test_disable_wifi_dongle_no_dongle_returns_friendly_message():
    from modules.network_tools import disable_wifi_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3"]), \
         patch("modules.network_tools._is_usb_iface", return_value=False), \
         patch("subprocess.run") as mock_run:
        out = disable_wifi_dongle()
    assert "No USB WiFi dongle" in out
    mock_run.assert_not_called()


# --- Internal WiFi blacklist (full disable) ---

def test_disable_internal_wifi_denied_without_grant():
    from modules.network_tools import disable_internal_wifi
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=False), \
         patch("subprocess.run") as mock_run:
        out = disable_internal_wifi()
    assert "Permission denied" in out
    mock_run.assert_not_called()


def test_disable_internal_wifi_writes_blacklist_and_rebuilds():
    from modules.network_tools import disable_internal_wifi, _BLACKLIST_CONF, _BLACKLIST_CONTENT
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=True), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_ok()]) as mock_run:
        out = disable_internal_wifi()
    assert "blacklisted" in out.lower()
    assert "reboot" in out.lower()
    tee_call = mock_run.call_args_list[0]
    assert tee_call.args[0] == ["sudo", "tee", _BLACKLIST_CONF]
    assert tee_call.kwargs["input"] == _BLACKLIST_CONTENT
    assert mock_run.call_args_list[1].args[0] == ["sudo", "update-initramfs", "-u"]


def test_disable_internal_wifi_initramfs_failure_reported():
    from modules.network_tools import disable_internal_wifi
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=True), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_fail("initramfs boom")]):
        out = disable_internal_wifi()
    assert "update-initramfs failed" in out
    assert "initramfs boom" in out


def test_disable_internal_wifi_initramfs_timeout_reported():
    import subprocess
    from modules.network_tools import disable_internal_wifi
    timeout = subprocess.TimeoutExpired(["sudo", "update-initramfs", "-u"], 180)
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=True), \
         patch("subprocess.run", side_effect=[_run_ok(), timeout]):
        out = disable_internal_wifi()
    assert out.startswith("Blacklist written, but update-initramfs failed")
    assert "timed out after 180s" in out


def test_enable_internal_wifi_initramfs_timeout_reported_and_skips_modprobe():
    import subprocess
    from modules.network_tools import enable_internal_wifi
    timeout = subprocess.TimeoutExpired(["sudo", "update-initramfs", "-u"], 180)
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=True), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run", side_effect=[_run_ok(), timeout]) as mock_run:
        out = enable_internal_wifi()
    assert out.startswith("Blacklist removed, but update-initramfs failed")
    assert "timed out after 180s" in out
    assert mock_run.call_count == 2


def test_enable_internal_wifi_removes_blacklist_and_loads():
    from modules.network_tools import enable_internal_wifi, _BLACKLIST_CONF
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=True), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run", side_effect=[_run_ok(), _run_ok(), _run_ok()]) as mock_run:
        out = enable_internal_wifi()
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds[0] == ["sudo", "rm", _BLACKLIST_CONF]
    assert cmds[1] == ["sudo", "update-initramfs", "-u"]
    assert cmds[2] == ["sudo", "modprobe", "iwlwifi"]
    assert "iwlwifi loaded" in out.lower()


def test_enable_internal_wifi_no_file_still_modprobes():
    from modules.network_tools import enable_internal_wifi
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=True), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("subprocess.run", side_effect=[_run_ok()]) as mock_run:
        out = enable_internal_wifi()
    assert [c.args[0] for c in mock_run.call_args_list] == [["sudo", "modprobe", "iwlwifi"]]
    assert "No blacklist file was present" in out


def test_enable_internal_wifi_denied_without_grant():
    from modules.network_tools import enable_internal_wifi
    with patch("modules.network_tools._has_internal_wifi_admin", return_value=False), \
         patch("subprocess.run") as mock_run:
        out = enable_internal_wifi()
    assert "Permission denied" in out
    mock_run.assert_not_called()


def test_internal_wifi_status_reports_presence_and_load():
    from modules.network_tools import internal_wifi_status
    lsmod = MagicMock(); lsmod.stdout = "iwlmvm 12288 1\niwlwifi 65536 1 iwlmvm\n"; lsmod.returncode = 0
    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run", return_value=lsmod):
        out = internal_wifi_status()
    assert "present" in out
    assert "yes" in out


def test_internal_wifi_status_not_loaded():
    from modules.network_tools import internal_wifi_status
    lsmod = MagicMock(); lsmod.stdout = "bluetooth 1048576 0\n"; lsmod.returncode = 0
    with patch("pathlib.Path.exists", return_value=False), \
         patch("subprocess.run", return_value=lsmod):
        out = internal_wifi_status()
    assert "absent" in out
    assert "no" in out


# --- scan_wifi / parse_nmcli_wifi_row ---

def _nmcli_scan(stdout: str):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def test_parse_nmcli_wifi_row_handles_hidden_and_colon_ssid():
    from modules.network_tools import parse_nmcli_wifi_row

    hidden = parse_nmcli_wifi_row(":6A:CA:59:D9:11:6E:64:WPA2:1")
    assert hidden["ssid"] == "<hidden>"
    assert hidden["bssid"] == "6A:CA:59:D9:11:6E"

    colon = parse_nmcli_wifi_row("My:Net:AA:BB:CC:DD:EE:FF:80:WPA2 WPA3:6")
    assert colon["ssid"] == "My:Net"
    assert colon["bssid"] == "AA:BB:CC:DD:EE:FF"
    assert colon["signal"] == 80
    assert colon["security"] == "WPA2 WPA3"
    assert colon["chan"] == "6"


def test_parse_nmcli_wifi_row_open_network_and_no_mac():
    from modules.network_tools import parse_nmcli_wifi_row

    assert parse_nmcli_wifi_row("OpenNet:12:34:56:78:9A:BC:50::11")["security"] == "open"
    assert parse_nmcli_wifi_row("no mac on this line") is None
    assert parse_nmcli_wifi_row("") is None


def test_scan_wifi_shows_mac_address():
    from modules.network_tools import scan_wifi
    out = (
        "Alf&Leisa50:F8:CA:59:D9:11:6C:74:WPA2:149\n"
        ":6A:CA:59:D9:11:6E:64:WPA2:1\n"
    )
    with patch("subprocess.run", return_value=_nmcli_scan(out)):
        result = scan_wifi()
    assert "BSSID" in result
    assert "F8:CA:59:D9:11:6C" in result
    assert "6A:CA:59:D9:11:6E" in result  # hidden network still shows its MAC


def test_scan_wifi_dedupes_by_bssid_and_sorts_by_signal():
    from modules.network_tools import scan_wifi
    out = (
        "NetA:AA:BB:CC:DD:EE:01:20:WPA2:1\n"
        "NetA:AA:BB:CC:DD:EE:01:20:WPA2:1\n"   # duplicate BSSID -> collapsed
        "NetB:AA:BB:CC:DD:EE:02:90:WPA2:1\n"
    )
    with patch("subprocess.run", return_value=_nmcli_scan(out)):
        result = scan_wifi()
    assert result.count("AA:BB:CC:DD:EE:01") == 1
    assert result.index("AA:BB:CC:DD:EE:02") < result.index("AA:BB:CC:DD:EE:01")


# --- virtual / container interface filtering ---

def test_is_virtual_iface_matches_container_prefixes():
    from modules.network_tools import _is_virtual_iface
    for name in ("vethc3e3dcc", "docker0", "br-c178647986e7", "virbr0", "vmnet1", "vnet0", "dummy0"):
        assert _is_virtual_iface(name), name
    for name in ("enp0s31f6", "wlp0s20f3", "wlx8c882b000d0f", "eth0", "wlan0mon", "br0", "lo", ""):
        assert not _is_virtual_iface(name), name


def _mixed_ifaces():
    return json.dumps([
        {"ifname": "lo",          "link_type": "loopback", "flags": ["UP"], "address": "00:00:00:00:00:00"},
        {"ifname": "docker0",     "link_type": "ether",    "flags": ["UP"], "address": "02:42:aa:bb:cc:01"},
        {"ifname": "vethc3e3dcc", "link_type": "ether",    "flags": ["UP"], "address": "02:42:aa:bb:cc:02"},
        {"ifname": "br-c178647986e7", "link_type": "ether", "flags": ["UP"], "address": "02:42:aa:bb:cc:03"},
        {"ifname": "enp0s31f6",   "link_type": "ether",    "flags": ["UP"], "address": "aa:bb:cc:dd:ee:03"},
    ]).encode()


def test_list_macs_hides_container_interfaces():
    from modules.network_tools import list_macs
    with patch("subprocess.run", return_value=_ifaces_mock(_mixed_ifaces())):
        out = list_macs()
    assert "enp0s31f6" in out
    assert "vethc3e3dcc" not in out
    assert "docker0" not in out
    assert "br-abc" not in out and "br-c178647986e7" not in out


def test_resolve_mac_auto_detect_skips_container_interfaces():
    from modules.network_tools import _resolve_and_get_mac
    with patch("subprocess.run", return_value=_ifaces_mock(_mixed_ifaces())):
        name, mac = _resolve_and_get_mac("")
    assert name == "enp0s31f6"
    assert mac == "aa:bb:cc:dd:ee:03"


def test_resolve_ip_iface_fallback_skips_container_interfaces():
    from modules.network_tools import _resolve_ip_iface
    route = MagicMock(); route.stdout = "[]"; route.returncode = 0

    def fake_run(cmd, **kwargs):
        return _ifaces_mock(_mixed_ifaces()) if "link" in cmd else route

    with patch("subprocess.run", side_effect=fake_run), \
         patch("modules.network_tools._get_ipv4", side_effect=lambda n: "10.0.0.5/24"):
        assert _resolve_ip_iface("") == "enp0s31f6"
