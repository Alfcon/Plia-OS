import sys
import types
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

# NOTE: import the tools INSIDE each test, not at module top. The module loader
# (core/loader.py) re-execs each modules/*.py and replaces its sys.modules entry
# whenever the registry is cleared — which the autouse reset_registry fixture
# does between every test. A top-level import would bind the pre-reload object
# while a string patch() target resolves the current one, so patches of module
# internals (e.g. _local_subnet) would miss. The existing network_tools tests
# follow the same in-function-import pattern for this reason.


# --- Password strength ---

def test_check_password_flags_weak_common_digit_sequence():
    from modules.network_check_tools import check_password
    out = check_password("12345678")
    assert "HIGH RISK" in out
    assert "common password" in out
    assert "all digits" in out


def test_check_password_strong_passphrase_is_ok():
    from modules.network_check_tools import check_password
    assert "looks strong" in check_password("correct-horse-battery-staple-9")


def test_check_password_never_echoes_the_password():
    from modules.network_check_tools import check_password
    secret = "hunter2pw"
    assert secret not in check_password(secret)


def test_assess_password_empty_is_open_network_high():
    from modules.network_check_tools import _assess_password
    sev, reasons = _assess_password("")
    assert sev == "HIGH"
    assert "open network" in reasons[0]


def test_assess_password_equal_to_ssid_is_serious():
    from modules.network_check_tools import _assess_password
    sev, reasons = _assess_password("MyHomeWiFiLongEnough", ssid="MyHomeWiFiLongEnough")
    assert sev == "HIGH"
    assert any("same as the network name" in r for r in reasons)


# --- Wi-Fi saved-password check ---

def _nmcli(active_stdout, psk_stdout):
    def run(cmd, *a, **k):
        m = MagicMock()
        m.returncode = 0
        if "dev" in cmd and "wifi" in cmd:
            m.stdout = active_stdout
        else:
            m.stdout = psk_stdout
        return m
    return run


def test_check_wifi_password_reads_and_assesses_saved_key():
    from modules.network_check_tools import check_wifi_password
    with patch("subprocess.run", side_effect=_nmcli("yes:HomeNet\n", "password\n")):
        out = check_wifi_password()
    assert 'for "HomeNet"' in out
    assert "HIGH RISK" in out


def test_check_wifi_password_not_connected():
    from modules.network_check_tools import check_wifi_password
    with patch("subprocess.run", side_effect=_nmcli("no:Other\n", "")):
        out = check_wifi_password()
    assert "Could not detect a connected Wi-Fi network" in out


def test_check_wifi_password_connected_but_key_unreadable():
    from modules.network_check_tools import check_wifi_password
    with patch("subprocess.run", side_effect=_nmcli("yes:HomeNet\n", "")):
        out = check_wifi_password()
    assert "saved password could not be read" in out


def test_check_wifi_password_nmcli_missing():
    from modules.network_check_tools import check_wifi_password
    with patch("subprocess.run", side_effect=FileNotFoundError("nmcli")):
        assert "Could not detect" in check_wifi_password()


# --- Service-exposure heuristics ---

def test_assess_host_flags_telnet_high_and_skips_closed_ports():
    from modules.network_check_tools import _assess_host
    findings = _assess_host({
        "23": {"state": "open", "name": "telnet"},
        "3306": {"state": "closed", "name": "mysql"},
    })
    titles = {f["title"] for f in findings}
    assert "Telnet enabled" in titles
    assert not any(f["port"] == 3306 for f in findings)
    assert findings[0]["severity"] == "HIGH"


def test_assess_host_clean_host_has_no_findings():
    from modules.network_check_tools import _assess_host
    assert _assess_host({"443": {"state": "open", "name": "https"}}) == []


# --- Local network scan ---

def test_scan_local_network_without_python_nmap_returns_install_hint():
    from modules.network_check_tools import scan_local_network
    with patch.dict(sys.modules, {"nmap": None}):
        out = scan_local_network("192.168.1.0/24")
    assert "python-nmap" in out


def _fake_nmap_module(hosts):
    """A stand-in `nmap` module whose PortScanner returns the given hosts."""
    mod = types.ModuleType("nmap")

    class PortScannerError(Exception):
        pass

    class _Host:
        def __init__(self, data):
            self._data = data

        def hostname(self):
            return self._data.get("hostname", "")

        def get(self, key, default=None):
            return self._data.get(key, default)

    class PortScanner:
        def scan(self, hosts, arguments=""):
            self._args = arguments

        def all_hosts(self):
            return list(hosts.keys())

        def __getitem__(self, host):
            return _Host(hosts[host])

    mod.PortScanner = PortScanner
    mod.PortScannerError = PortScannerError
    return mod


def test_scan_local_network_reports_exposed_services():
    from modules.network_check_tools import scan_local_network
    hosts = {
        "192.168.1.10": {
            "hostname": "nas",
            "tcp": {"23": {"state": "open", "name": "telnet"}},
        },
    }
    with patch.dict(sys.modules, {"nmap": _fake_nmap_module(hosts)}):
        out = scan_local_network("192.168.1.0/24")
    assert "Scanned 192.168.1.0/24" in out
    assert "SECURITY REPORT" in out
    assert "Telnet enabled" in out
    assert "1 high" in out


def test_scan_local_network_auto_detects_subnet_when_blank():
    import modules.network_check_tools as nc
    with patch.object(nc, "_local_subnet", return_value="10.0.0.0/24"), \
         patch.dict(sys.modules, {"nmap": _fake_nmap_module({})}):
        out = nc.scan_local_network("")
    assert "Scanned 10.0.0.0/24" in out
    assert "No hosts responded" in out


# --- External exposure ---

@respx.mock
async def test_external_exposure_check_reports_open_ports():
    from modules.network_check_tools import external_exposure_check
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, text="203.0.113.5"))
    respx.get("https://internetdb.shodan.io/203.0.113.5").mock(
        return_value=httpx.Response(200, json={"ports": [3389], "vulns": [], "hostnames": [], "tags": []})
    )
    out = await external_exposure_check()
    assert "Public IP: 203.0.113.5" in out
    assert "Port 3389" in out
    assert "Remote Desktop" in out


@respx.mock
async def test_external_exposure_check_clean_when_not_indexed():
    from modules.network_check_tools import external_exposure_check
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, text="203.0.113.9"))
    respx.get("https://internetdb.shodan.io/203.0.113.9").mock(return_value=httpx.Response(404))
    out = await external_exposure_check()
    assert "No open ports are visible from the internet" in out


@respx.mock
async def test_external_exposure_check_no_public_ip():
    from modules.network_check_tools import external_exposure_check
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        respx.get(url).mock(side_effect=httpx.ConnectError("offline"))
    out = await external_exposure_check()
    assert "Could not determine your public IP" in out
