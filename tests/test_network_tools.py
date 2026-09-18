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

def test_detect_dongle_picks_usb_wifi():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names", return_value=["wlp0s20f3", "wlx8c882b000d0f"]), \
         patch("modules.network_tools._is_usb_iface", side_effect=lambda n: n.startswith("wlx")):
        assert _detect_dongle() == "wlx8c882b000d0f"


def test_detect_dongle_explicit_interface_bypasses_detection():
    from modules.network_tools import _detect_dongle
    with patch("modules.network_tools._wifi_device_names") as m:
        assert _detect_dongle("wlxABC") == "wlxABC"
        m.assert_not_called()


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
    with patch("subprocess.run", side_effect=[_run_ok(), _run_ok()]) as mock_run:
        out = disable_wifi_dongle("wlx8c882b000d0f")
    assert "disabled" in out.lower()
    assert mock_run.call_args_list[0].args[0] == ["nmcli", "device", "disconnect", "wlx8c882b000d0f"]
    assert mock_run.call_args_list[1].args[0] == ["nmcli", "device", "set", "wlx8c882b000d0f", "autoconnect", "no"]


def test_enable_wifi_dongle_manages_autoconnects_and_connects():
    from modules.network_tools import enable_wifi_dongle
    with patch("subprocess.run", side_effect=[_run_ok(), _run_ok(), _run_ok()]) as mock_run:
        out = enable_wifi_dongle("wlx8c882b000d0f")
    assert "enabled" in out.lower()
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds[0] == ["nmcli", "device", "set", "wlx8c882b000d0f", "managed", "yes"]
    assert cmds[1] == ["nmcli", "device", "set", "wlx8c882b000d0f", "autoconnect", "yes"]
    assert cmds[2] == ["nmcli", "device", "connect", "wlx8c882b000d0f"]


def test_enable_wifi_dongle_reports_warning_on_failure():
    from modules.network_tools import enable_wifi_dongle
    with patch("subprocess.run", side_effect=[_run_ok(), _run_ok(), _run_fail("device not ready")]):
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
