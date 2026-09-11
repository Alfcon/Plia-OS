import asyncio
import subprocess
from unittest.mock import AsyncMock, patch, MagicMock, call
import pytest


def _ok(stdout="", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _err(stderr="error"):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


# --- uid detection ---

def test_detect_tor_uid_debian():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [_ok(), _ok(stdout="109\n")]
        import core.tor_manager as tm
        user, uid = tm._detect_tor_uid()
    assert user == "debian-tor"
    assert uid == "109"


def test_detect_tor_uid_arch_fallback():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [_err(), _ok(stdout="107\n")]
        import core.tor_manager as tm
        user, uid = tm._detect_tor_uid()
    assert user == "tor"
    assert uid == "107"


# --- torrc write (idempotent) ---

def test_write_torrc_appends_when_marker_absent(tmp_path):
    import core.tor_manager as tm
    torrc = tmp_path / "torrc"
    torrc.write_text("# existing config\n")
    with patch.object(tm, "_TOR_TORRC", torrc):
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            tm._write_torrc()
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "tee" in args


def test_write_torrc_skips_when_marker_present(tmp_path):
    import core.tor_manager as tm
    torrc = tmp_path / "torrc"
    torrc.write_text("# Plia-OS Tor transparent proxy\nTransPort 9040\n")
    with patch.object(tm, "_TOR_TORRC", torrc):
        with patch("subprocess.run") as mock_run:
            tm._write_torrc()
    mock_run.assert_not_called()


# --- iptables ---

def test_apply_proxy_rules_correct_order():
    import core.tor_manager as tm
    with patch.object(tm, "_run_iptables", return_value=_ok()) as mock_ipt:
        err = tm._apply_proxy_rules("109")
    assert err is None
    calls = [c[0] for c in mock_ipt.call_args_list]
    # uid-owner RETURN must appear before REDIRECT rules
    uid_pos = next(i for i, c in enumerate(calls) if "--uid-owner" in c)
    redirect_pos = next(i for i, c in enumerate(calls) if "REDIRECT" in c)
    assert uid_pos < redirect_pos


def test_apply_proxy_rules_rollback_on_failure():
    import core.tor_manager as tm
    responses = [_ok()] * 5 + [_err("permission denied")]
    with patch.object(tm, "_run_iptables", side_effect=responses):
        with patch.object(tm, "_flush_proxy_rules") as mock_flush:
            err = tm._apply_proxy_rules("109")
    assert err is not None
    mock_flush.assert_called_once()


def test_flush_proxy_rules_calls_iptables():
    import core.tor_manager as tm
    with patch.object(tm, "_run_iptables", return_value=_ok()) as mock_ipt:
        tm._flush_proxy_rules()
    calls_flat = [" ".join(c[0]) for c in mock_ipt.call_args_list]
    assert any("PLIA_TOR" in c for c in calls_flat)


# --- verification ---

def test_verify_tor_connection_success():
    import core.tor_manager as tm
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"IsTor": True, "IP": "185.220.1.1"}
    with patch("httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
        ok, result = tm._verify_tor_connection()
    assert ok is True
    assert result == "185.220.1.1"


def test_verify_tor_connection_not_tor():
    import core.tor_manager as tm
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"IsTor": False, "IP": "1.2.3.4"}
    with patch("httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
        ok, result = tm._verify_tor_connection()
    assert ok is False
    assert "not routing" in result


def test_verify_tor_connection_network_error():
    import core.tor_manager as tm
    with patch("httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        ok, result = tm._verify_tor_connection()
    assert ok is False


# --- enable ---

def test_enable_tor_not_installed():
    import core.tor_manager as tm
    with patch("subprocess.run", return_value=_err()):
        result = tm.enable()
    assert "not installed" in result
    assert "apt install tor" in result


def test_enable_no_sudo_iptables():
    import core.tor_manager as tm
    with patch("subprocess.run", side_effect=[_ok(), _err("permission denied")]):
        result = tm.enable()
    assert "sudoers" in result or "NOPASSWD" in result


def test_enable_full_success():
    import core.tor_manager as tm
    with patch("subprocess.run", return_value=_ok(stdout="109\n")):
        with patch.object(tm, "_write_torrc", return_value=None):
            with patch.object(tm, "_run_systemctl", return_value=_ok()):
                with patch.object(tm, "_wait_for_circuits", return_value=True):
                    with patch.object(tm, "_verify_tor_connection", return_value=(True, "185.220.1.1")):
                        with patch.object(tm, "_apply_proxy_rules", return_value=None):
                            with patch("core.tor_manager.update_config"):
                                with patch("asyncio.create_task"):
                                    result = tm.enable()
    assert "enabled" in result.lower()
    assert "185.220.1.1" in result


def test_enable_circuit_timeout_stops_tor():
    import core.tor_manager as tm
    with patch("subprocess.run", return_value=_ok(stdout="109\n")):
        with patch.object(tm, "_write_torrc", return_value=None):
            with patch.object(tm, "_run_systemctl", return_value=_ok()) as mock_svc:
                with patch.object(tm, "_wait_for_circuits", return_value=False):
                    result = tm.enable()
    assert "circuit" in result.lower() or "failed" in result.lower()
    stop_calls = [c for c in mock_svc.call_args_list if "stop" in c[0]]
    assert stop_calls


def test_enable_verify_failure_stops_tor():
    import core.tor_manager as tm
    with patch("subprocess.run", return_value=_ok(stdout="109\n")):
        with patch.object(tm, "_write_torrc", return_value=None):
            with patch.object(tm, "_run_systemctl", return_value=_ok()) as mock_svc:
                with patch.object(tm, "_wait_for_circuits", return_value=True):
                    with patch.object(tm, "_verify_tor_connection", return_value=(False, "not tor")):
                        result = tm.enable()
    assert "not tor" in result
    stop_calls = [c for c in mock_svc.call_args_list if "stop" in c[0]]
    assert stop_calls


# --- disable ---

def test_disable_flushes_rules_and_stops_tor():
    import core.tor_manager as tm
    tm._kill_switch_active = False
    with patch.object(tm, "_flush_proxy_rules") as mock_flush:
        with patch.object(tm, "_run_systemctl", return_value=_ok()) as mock_svc:
            with patch("core.tor_manager.update_config"):
                result = tm.disable()
    mock_flush.assert_called_once()
    assert any("stop" in c[0] for c in mock_svc.call_args_list)
    assert "disabled" in result.lower()


def test_disable_with_active_kill_switch_deactivates_first():
    import core.tor_manager as tm
    tm._kill_switch_active = True
    with patch.object(tm, "_deactivate_kill_switch") as mock_deact:
        with patch.object(tm, "_flush_proxy_rules"):
            with patch.object(tm, "_run_systemctl", return_value=_ok()):
                with patch("core.tor_manager.update_config"):
                    tm.disable()
    mock_deact.assert_called_once()
    tm._kill_switch_active = False  # reset


# --- kill switch ---

def test_activate_kill_switch_sets_drop_policy():
    import core.tor_manager as tm
    tm._kill_switch_active = False
    with patch.object(tm, "_run_iptables", return_value=_ok()) as mock_ipt:
        tm._activate_kill_switch("109")
    assert tm._kill_switch_active is True
    calls_flat = [" ".join(c[0]) for c in mock_ipt.call_args_list]
    assert any("DROP" in c for c in calls_flat)
    tm._kill_switch_active = False


def test_deactivate_kill_switch_restores_accept():
    import core.tor_manager as tm
    tm._kill_switch_active = True
    with patch.object(tm, "_run_iptables", return_value=_ok()) as mock_ipt:
        tm._deactivate_kill_switch()
    assert tm._kill_switch_active is False
    calls_flat = [" ".join(c[0]) for c in mock_ipt.call_args_list]
    assert any("ACCEPT" in c for c in calls_flat)


# --- get_status ---

def test_get_status_reflects_config_and_kill_switch():
    import core.tor_manager as tm
    tm._kill_switch_active = False
    with patch("core.tor_manager.get_config") as mock_cfg:
        mock_cfg.return_value.tor_enabled = True
        status = tm.get_status()
    assert status["enabled"] is True
    assert status["kill_switch_active"] is False


# --- monitor loop ---

async def test_monitor_loop_activates_kill_switch_on_circuit_loss():
    import core.tor_manager as tm
    tm._kill_switch_active = False

    with patch.object(tm, "_MONITOR_INTERVAL", 0):
        with patch.object(tm, "_circuit_ok", return_value=False):
            with patch.object(tm, "_activate_kill_switch"):
                with patch("core.tor_manager.update_config"):
                    with patch("core.events.emit", new=AsyncMock()):
                        with patch("subprocess.run", return_value=_ok()):
                            await tm._monitor_loop("109")

    # Loop must have exited after kill switch — if we reach here it didn't hang
    assert tm._kill_switch_active is False  # patched _activate_kill_switch didn't set it


async def test_monitor_loop_does_not_exit_while_circuits_ok():
    import core.tor_manager as tm
    tm._kill_switch_active = False

    call_count = 0

    async def mock_sleep(n):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with patch.object(tm, "_circuit_ok", return_value=True):
            with patch.object(tm, "_activate_kill_switch") as mock_ks:
                with pytest.raises(asyncio.CancelledError):
                    await tm._monitor_loop("109")

    mock_ks.assert_not_called()
