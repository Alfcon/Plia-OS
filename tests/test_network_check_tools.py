import subprocess
from unittest.mock import MagicMock, patch

import pytest

# NOTE: import the tools INSIDE each test, not at module top. The module loader
# (core/loader.py) re-execs each modules/*.py and replaces its sys.modules entry
# whenever the registry is cleared — which the autouse reset_registry fixture
# does between every test. A top-level import would bind the pre-reload object
# while a string patch() target resolves the current one. The existing
# network_tools tests follow the same in-function-import pattern.

PY = "/home/alfcon/Projects/Netpass/netpass/bin/python"
SCRIPT = "/home/alfcon/Projects/Netpass/netpass.py"


def _completed(stdout="", stderr="", returncode=0):
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


def _last_cmd(mock_run):
    return mock_run.call_args.args[0]


# --- command construction ---

def test_check_password_runs_netpass_without_sudo():
    from modules.network_check_tools import check_password
    with patch("subprocess.run", return_value=_completed("HIGH RISK — weak")) as run:
        out = check_password("12345678")
    assert out == "HIGH RISK — weak"
    assert _last_cmd(run) == [PY, SCRIPT, "--check-password", "12345678"]


def test_check_wifi_password_runs_netpass_without_sudo():
    from modules.network_check_tools import check_wifi_password
    with patch("subprocess.run", return_value=_completed("looks strong")) as run:
        out = check_wifi_password()
    assert out == "looks strong"
    assert _last_cmd(run) == [PY, SCRIPT, "--check-wifi"]


def test_external_exposure_check_runs_netpass_without_sudo():
    from modules.network_check_tools import external_exposure_check
    with patch("subprocess.run", return_value=_completed("No open ports are visible")) as run:
        out = external_exposure_check()
    assert out == "No open ports are visible"
    assert _last_cmd(run) == [PY, SCRIPT, "--external"]


def test_scan_local_network_uses_sudo_and_report():
    from modules.network_check_tools import scan_local_network
    with patch("subprocess.run", return_value=_completed("SECURITY REPORT\n...")) as run:
        out = scan_local_network("192.168.1.0/24")
    assert "SECURITY REPORT" in out
    assert _last_cmd(run) == ["sudo", PY, SCRIPT, "192.168.1.0/24", "--report"]


def test_scan_local_network_blank_target_omits_positional():
    from modules.network_check_tools import scan_local_network
    with patch("subprocess.run", return_value=_completed("ok")) as run:
        scan_local_network("")
    assert _last_cmd(run) == ["sudo", PY, SCRIPT, "--report"]


def test_scan_local_network_deep_adds_flag_and_longer_timeout():
    from modules.network_check_tools import scan_local_network, _DEEP_TIMEOUT_S
    with patch("subprocess.run", return_value=_completed("ok")) as run:
        scan_local_network("10.0.0.0/24", deep=True)
    assert _last_cmd(run) == ["sudo", PY, SCRIPT, "10.0.0.0/24", "--report", "--deep"]
    assert run.call_args.kwargs["timeout"] == _DEEP_TIMEOUT_S


def test_scan_local_network_strips_whitespace_target():
    from modules.network_check_tools import scan_local_network
    with patch("subprocess.run", return_value=_completed("ok")) as run:
        scan_local_network("  host.lan  ")
    assert _last_cmd(run) == ["sudo", PY, SCRIPT, "host.lan", "--report"]


# --- error / edge handling ---

def test_nonzero_exit_reports_stderr():
    from modules.network_check_tools import check_wifi_password
    with patch("subprocess.run", return_value=_completed(stderr="boom", returncode=1)):
        out = check_wifi_password()
    assert out == "netpass failed: boom"


def test_timeout_is_reported():
    from modules.network_check_tools import scan_local_network, _SCAN_TIMEOUT_S
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="netpass", timeout=_SCAN_TIMEOUT_S)):
        out = scan_local_network("192.168.1.0/24")
    assert out == f"netpass timed out after {_SCAN_TIMEOUT_S}s."


def test_missing_netpass_reports_paths():
    from modules.network_check_tools import external_exposure_check
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        out = external_exposure_check()
    assert "netpass not found" in out
    assert SCRIPT in out


def test_empty_output_has_placeholder():
    from modules.network_check_tools import check_password
    with patch("subprocess.run", return_value=_completed(stdout="", stderr="")):
        out = check_password("x")
    assert out == "(netpass produced no output)"


# --- elevated scan via sudo -S (password path) ---

def test_run_scan_without_password_uses_literal_sudo():
    from modules.network_check_tools import run_scan
    with patch("subprocess.run", return_value=_completed("ok")) as run:
        run_scan("192.168.1.0/24")
    assert _last_cmd(run) == ["sudo", PY, SCRIPT, "192.168.1.0/24", "--report"]
    assert run.call_args.kwargs.get("input") is None


def test_run_scan_with_password_uses_sudo_S_and_feeds_stdin():
    from modules.network_check_tools import run_scan
    with patch("subprocess.run", return_value=_completed("SECURITY REPORT")) as run:
        out = run_scan("192.168.1.0/24", sudo_password="s3cret")
    assert out == "SECURITY REPORT"
    cmd = _last_cmd(run)
    assert cmd[:4] == ["sudo", "-S", "-p", ""]
    assert cmd[4:] == [PY, SCRIPT, "192.168.1.0/24", "--report"]
    # password is fed via stdin, never on the command line
    assert "s3cret" not in cmd
    assert run.call_args.kwargs["input"] == "s3cret\n"


def test_run_scan_password_bad_auth_reports_failure():
    from modules.network_check_tools import run_scan
    with patch("subprocess.run", return_value=_completed(stderr="Sorry, try again.", returncode=1)):
        out = run_scan("10.0.0.0/24", sudo_password="wrong")
    assert out == "netpass failed: Sorry, try again."


def test_scan_local_network_tool_takes_no_password():
    # The LLM-facing tool must not accept a password parameter (leak surface).
    import inspect
    from modules.network_check_tools import scan_local_network
    params = inspect.signature(scan_local_network).parameters
    assert "sudo_password" not in params
    assert set(params) == {"target", "deep"}


# --- dashboard endpoint (not a tool) ---

@pytest.mark.asyncio
async def test_netcheck_scan_endpoint_passes_password_to_run_scan():
    from httpx import AsyncClient, ASGITransport
    from core.main import create_app
    app = create_app()
    with patch("modules.network_check_tools.run_scan", return_value="REPORT") as rs:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/netcheck/scan",
                              json={"target": "192.168.1.0/24", "deep": True, "sudo_password": "pw"})
    assert r.status_code == 200
    assert r.json()["result"] == "REPORT"
    rs.assert_called_once_with("192.168.1.0/24", True, "pw")


@pytest.mark.asyncio
async def test_netcheck_scan_endpoint_without_password_passes_none():
    from httpx import AsyncClient, ASGITransport
    from core.main import create_app
    app = create_app()
    with patch("modules.network_check_tools.run_scan", return_value="REPORT") as rs:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/netcheck/scan", json={"target": "", "deep": False})
    assert r.status_code == 200
    rs.assert_called_once_with("", False, None)


def test_netcheck_scan_is_not_a_registered_tool():
    # The elevated endpoint must not be reachable as an LLM tool.
    import core.main as m
    from core.registry import list_modules
    m.load_modules()
    all_tools = {t for tools in list_modules().values() for t in tools}
    assert "netcheck_scan" not in all_tools
    assert "run_scan" not in all_tools
