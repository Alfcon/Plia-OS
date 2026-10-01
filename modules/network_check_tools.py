"""Network Check — thin wrapper over the standalone netpass auditing program.

Each tool shells out to the real netpass program using netpass's own virtualenv
interpreter, equivalent to the shell alias:

    alias netpass='sudo /home/alfcon/Projects/Netpass/netpass/bin/python \
                   /home/alfcon/Projects/Netpass/netpass.py'

The local-network scan runs under sudo — netpass needs root for SYN/OS
detection and MAC/vendor resolution. The password, Wi-Fi, and external-exposure
checks need no root, so they run without sudo. All are read-only and advisory;
use the scan only on networks you own or are authorized to test.
"""
from __future__ import annotations

import logging
import subprocess

from core.registry import tool

logger = logging.getLogger(__name__)

# The netpass program and its own virtualenv interpreter (which has python-nmap).
NETPASS_PYTHON = "/home/alfcon/Projects/Netpass/netpass/bin/python"
NETPASS_SCRIPT = "/home/alfcon/Projects/Netpass/netpass.py"

# netpass invokes nmap, so scans are slow; the password/wifi/external checks are quick.
_QUICK_TIMEOUT_S = 60
_SCAN_TIMEOUT_S = 300
_DEEP_TIMEOUT_S = 1800


def _run_netpass(args: list[str], *, sudo: bool = False, timeout: float = _QUICK_TIMEOUT_S) -> str:
    """Run netpass.py with the given flags and return its output as a string."""
    cmd = (["sudo"] if sudo else []) + [NETPASS_PYTHON, NETPASS_SCRIPT] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return (
            f"netpass not found. Expected interpreter {NETPASS_PYTHON} and script "
            f"{NETPASS_SCRIPT} — check the paths in modules/network_check_tools.py."
        )
    except subprocess.TimeoutExpired:
        return f"netpass timed out after {int(timeout)}s."
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return f"netpass failed: {err or out or f'exit code {proc.returncode}'}"
    return out or err or "(netpass produced no output)"


@tool(
    "Check how strong a Wi-Fi password (or any password) is, via the netpass program. "
    "Pass the password string; it is evaluated locally and reported with weaknesses and "
    "how to fix them."
)
def check_password(password: str) -> str:
    return _run_netpass(["--check-password", password])


@tool(
    "Check the strength of the Wi-Fi password this machine is currently connected to, via "
    "the netpass program. Reads the saved key locally (may need elevated access) and never "
    "sends it anywhere."
)
def check_wifi_password() -> str:
    return _run_netpass(["--check-wifi"])


@tool(
    "Scan your local network for devices and flag risky exposed services (telnet, SMB, "
    "exposed databases, open proxies, outdated services, etc.) with plain-language fixes, "
    "via the netpass program (runs under sudo for full host/MAC/OS detection). "
    "target: a host, hostname, or CIDR range; leave blank to auto-detect your /24 subnet. "
    "deep=True also runs nmap's CVE scripts (much slower). Use only on networks you own or "
    "are authorized to scan."
)
def scan_local_network(target: str = "", deep: bool = False) -> str:
    args: list[str] = []
    t = (target or "").strip()
    if t:
        args.append(t)
    args.append("--report")
    if deep:
        args.append("--deep")
    return _run_netpass(args, sudo=True, timeout=_DEEP_TIMEOUT_S if deep else _SCAN_TIMEOUT_S)


@tool(
    "Check what your network exposes to the public internet, via the netpass program "
    "(Shodan's free InternetDB). Shows your public IP, any internet-reachable ports with "
    "hardening advice, and known CVEs seen on that IP. Contacts external services, which "
    "will see your IP."
)
def external_exposure_check() -> str:
    return _run_netpass(["--external"])
