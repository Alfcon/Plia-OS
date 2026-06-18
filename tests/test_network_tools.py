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
