from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

import httpx

from core.config import get_config, update_config

logger = logging.getLogger(__name__)

_TOR_TORRC = Path("/etc/tor/torrc")
_MARKER = "# Plia-OS Tor transparent proxy"
_TOR_TORRC_ADDITIONS = f"""
{_MARKER}
VirtualAddrNetwork 10.192.0.0/10
AutomapHostsOnResolve 1
SOCKSPort 9050
TransPort 9040
DNSPort 5353
ControlPort 9051
CookieAuthentication 1
"""
_CIRCUIT_TIMEOUT = 30
_MONITOR_INTERVAL = 10

_kill_switch_active: bool = False
_monitor_task: asyncio.Task | None = None
_last_tor_uid: str = ""
_exit_ip: str | None = None


def _detect_tor_uid() -> tuple[str, str]:
    r = subprocess.run(["getent", "passwd", "debian-tor"], capture_output=True)
    user = "debian-tor" if r.returncode == 0 else "tor"
    uid = subprocess.run(["id", "-u", user], capture_output=True, text=True).stdout.strip()
    return user, uid


def _run_iptables(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "iptables", *args], capture_output=True, text=True, timeout=10)


def _run_systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "systemctl", *args], capture_output=True, text=True, timeout=30)


def _write_torrc() -> str | None:
    try:
        current = _TOR_TORRC.read_text() if _TOR_TORRC.exists() else ""
    except PermissionError:
        current = ""
    if _MARKER in current:
        return None
    r = subprocess.run(
        ["sudo", "tee", "-a", str(_TOR_TORRC)],
        input=_TOR_TORRC_ADDITIONS,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0:
        return r.stderr.strip() or "sudo tee failed (add /usr/bin/tee to sudoers)"
    return None


def _apply_proxy_rules(tor_uid: str) -> str | None:
    cmds = [
        ("-t", "nat", "-N", "PLIA_TOR"),
        ("-t", "nat", "-A", "PLIA_TOR", "-m", "owner", "--uid-owner", tor_uid, "-j", "RETURN"),
        ("-t", "nat", "-A", "PLIA_TOR", "-d", "127.0.0.0/8", "-j", "RETURN"),
        ("-t", "nat", "-A", "PLIA_TOR", "-d", "192.168.0.0/16", "-j", "RETURN"),
        ("-t", "nat", "-A", "PLIA_TOR", "-d", "10.0.0.0/8", "-j", "RETURN"),
        ("-t", "nat", "-A", "PLIA_TOR", "-p", "udp", "--dport", "53", "-j", "REDIRECT", "--to-ports", "5353"),
        ("-t", "nat", "-A", "PLIA_TOR", "-p", "tcp", "--syn", "-j", "REDIRECT", "--to-ports", "9040"),
        ("-t", "nat", "-A", "OUTPUT", "-j", "PLIA_TOR"),
    ]
    for cmd in cmds:
        r = _run_iptables(*cmd)
        if r.returncode != 0:
            _flush_proxy_rules()
            return r.stderr.strip()
    return None


def _flush_proxy_rules() -> None:
    _run_iptables("-t", "nat", "-D", "OUTPUT", "-j", "PLIA_TOR")
    _run_iptables("-t", "nat", "-F", "PLIA_TOR")
    _run_iptables("-t", "nat", "-X", "PLIA_TOR")


def _activate_kill_switch(tor_uid: str) -> None:
    global _kill_switch_active
    _run_iptables("-I", "OUTPUT", "1", "-m", "owner", "--uid-owner", tor_uid, "-j", "ACCEPT")
    _run_iptables("-I", "OUTPUT", "2", "-d", "127.0.0.0/8", "-j", "ACCEPT")
    _run_iptables("-P", "OUTPUT", "DROP")
    _kill_switch_active = True


def _deactivate_kill_switch() -> None:
    global _kill_switch_active
    # Remove only the two rules _activate_kill_switch inserted; don't flush whole chain
    _run_iptables("-D", "OUTPUT", "-m", "owner", "--uid-owner", _last_tor_uid, "-j", "ACCEPT")
    _run_iptables("-D", "OUTPUT", "-d", "127.0.0.0/8", "-j", "ACCEPT")
    _run_iptables("-P", "OUTPUT", "ACCEPT")
    _kill_switch_active = False


def _wait_for_circuits(timeout: int = _CIRCUIT_TIMEOUT) -> bool:
    try:
        from stem.control import Controller
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with Controller.from_port(port=9051) as ctrl:
                    ctrl.authenticate()
                    if ctrl.get_info("status/circuit-established") == "1":
                        return True
            except Exception:
                pass
            time.sleep(1)
        return False
    except ImportError:
        time.sleep(5)
        r = subprocess.run(["pgrep", "-x", "tor"], capture_output=True)
        return r.returncode == 0


def _verify_tor_connection() -> tuple[bool, str]:
    try:
        transport = httpx.HTTPTransport(proxy="socks5://127.0.0.1:9050")
        with httpx.Client(transport=transport, timeout=15.0) as client:
            resp = client.get("https://check.torproject.org/api/ip")
        data = resp.json()
        if data.get("IsTor"):
            return True, data.get("IP", "unknown")
        return False, "Traffic not routing through Tor — iptables may be misconfigured"
    except Exception as exc:
        return False, str(exc)


def _circuit_ok() -> bool:
    try:
        from stem.control import Controller
        with Controller.from_port(port=9051) as ctrl:
            ctrl.authenticate()
            return ctrl.get_info("status/circuit-established") == "1"
    except ImportError:
        r = subprocess.run(["pgrep", "-x", "tor"], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def enable() -> str:
    global _monitor_task, _last_tor_uid, _exit_ip

    if _kill_switch_active:
        _deactivate_kill_switch()

    r = subprocess.run(["which", "tor"], capture_output=True)
    if r.returncode != 0:
        return "tor not installed. Run: sudo apt install tor"

    r = _run_iptables("-L", "-n")
    if r.returncode != 0:
        return (
            "sudo iptables access denied. Add to /etc/sudoers.d/plia-tor:\n"
            "plia ALL=(root) NOPASSWD: /usr/sbin/iptables, "
            "/usr/bin/systemctl start tor, /usr/bin/systemctl stop tor, "
            "/usr/bin/systemctl restart tor, /usr/bin/tee"
        )

    _, tor_uid = _detect_tor_uid()
    _last_tor_uid = tor_uid
    torrc_err = _write_torrc()
    if torrc_err:
        return f"Failed to write torrc: {torrc_err}"

    r = _run_systemctl("restart", "tor")
    if r.returncode != 0:
        return f"Failed to start tor: {r.stderr.strip()}"

    if not _wait_for_circuits():
        _run_systemctl("stop", "tor")
        return "Tor failed to establish circuits within 30s"

    ok, result = _verify_tor_connection()
    if not ok:
        _run_systemctl("stop", "tor")
        return result

    _exit_ip = result
    err = _apply_proxy_rules(tor_uid)
    if err is not None:
        _run_systemctl("stop", "tor")
        return f"iptables error: {err or '(no stderr — check dmesg)'}"

    update_config(tor_enabled=True)
    return f"Tor enabled. Exit node: {result}"


def disable() -> str:
    global _monitor_task, _exit_ip

    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
    _monitor_task = None

    if _kill_switch_active:
        _deactivate_kill_switch()

    _flush_proxy_rules()
    _run_systemctl("stop", "tor")
    update_config(tor_enabled=False)
    _exit_ip = None
    return "Tor disabled. Clearnet restored."


def get_status() -> dict:
    cfg = get_config()
    return {
        "enabled": cfg.tor_enabled,
        "kill_switch_active": _kill_switch_active,
        "exit_ip": _exit_ip,
    }


async def _monitor_loop(tor_uid: str) -> None:
    from core import events

    while True:
        await asyncio.sleep(_MONITOR_INTERVAL)
        ok = await asyncio.to_thread(_circuit_ok)
        if not ok:
            await asyncio.to_thread(_activate_kill_switch, tor_uid)
            await asyncio.to_thread(_flush_proxy_rules)
            await asyncio.to_thread(update_config, tor_enabled=False)
            await events.emit("tor_status", {
                "enabled": False,
                "kill_switch_active": True,
                "error": "Tor circuits dropped",
            })
            await asyncio.to_thread(
                subprocess.run,
                ["notify-send", "Plia: Tor dropped", "All traffic blocked. Run 'enable tor' to reconnect."],
                capture_output=True,
                timeout=5,
            )
            break
