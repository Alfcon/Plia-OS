"""Network Check — thin wrapper over the standalone netpass auditing program.

Each tool shells out to the real netpass program using netpass's own virtualenv
interpreter, equivalent to the shell alias:

    alias netpass='sudo /home/alfcon/Projects/Netpass/netpass/bin/python \
                   /home/alfcon/Projects/Netpass/netpass.py'

The local-network scan runs under sudo — netpass needs root for SYN/OS
detection and MAC/vendor resolution. The password, Wi-Fi, and external-exposure
checks need no root, so they run without sudo. All are read-only and advisory;
use the scan only on networks you own or are authorized to test.

Elevation for the scan uses Plia's process-wide sudo askpass helper: if no
passwordless rule or cached credentials exist, a desktop password dialog opens
and the user can approve the scan. On a headless host without a dialog, it
fails with a pointer to the dashboard. The dashboard's `/api/netcheck/scan`
endpoint can also take a sudo password and uses `sudo -S`.
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

# Shown when sudo still refuses to run without a password (headless host, or the
# password dialog was cancelled): the caller gets actionable guidance instead of
# a long wait on an unanswerable prompt.
_SUDO_HINT = (
    "netpass needs root for host/MAC/OS detection. Approve the Plia "
    "administrator-password dialog, or run the scan from the dashboard "
    "(Monitor/Developer → Network Check), where the password is used once and "
    "never stored — or add a NOPASSWD rule for netpass."
)


def _sudo_needs_password(stderr: str) -> bool:
    """True when sudo refused to run because it wanted a password (no NOPASSWD rule)."""
    low = (stderr or "").lower()
    return (
        "password is required" in low
        or "a terminal is required" in low
        or "no tty present" in low
    )


def _run_netpass(
    args: list[str], *, sudo: bool = False, sudo_password: str | None = None,
    timeout: float = _QUICK_TIMEOUT_S,
) -> str:
    """Run netpass.py with the given flags and return its output as a string.

    sudo_password, when given, elevates via `sudo -S` (password read from stdin,
    never placed on the command line). It is used once and never stored or
    logged. Plain sudo=True runs `sudo`, which opens Plia's administrator
    password dialog if no cached credentials are available.
    """
    stdin_text: str | None = None
    if sudo_password is not None:
        # -S reads the password from stdin; -p '' suppresses the prompt so it
        # cannot leak into captured stderr.
        prefix = ["sudo", "-S", "-p", ""]
        stdin_text = sudo_password + "\n"
    elif sudo:
        # The process-wide SUDO_ASKPASS helper handles the prompt graphically.
        prefix = ["sudo"]
    else:
        prefix = []
    cmd = prefix + [NETPASS_PYTHON, NETPASS_SCRIPT] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, input=stdin_text,
        )
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
        if sudo and sudo_password is None and _sudo_needs_password(err):
            return _SUDO_HINT
        return f"netpass failed: {err or out or f'exit code {proc.returncode}'}"
    return out or err or "(netpass produced no output)"


def run_scan(target: str = "", deep: bool = False, sudo_password: str | None = None) -> str:
    """Build and run the netpass local-network scan.

    Shared by the LLM tool (no password → literal sudo) and the dashboard's
    elevated-scan endpoint (sudo_password → `sudo -S`). Not a registered tool.
    """
    args: list[str] = []
    t = (target or "").strip()
    if t:
        args.append(t)
    args.append("--report")
    if deep:
        args.append("--deep")
    timeout = _DEEP_TIMEOUT_S if deep else _SCAN_TIMEOUT_S
    if sudo_password:
        return _run_netpass(args, sudo_password=sudo_password, timeout=timeout)
    return _run_netpass(args, sudo=True, timeout=timeout)


@tool(
    "Check how strong a Wi-Fi password (or any password) is, via the netpass program. "
    "Pass the password string; it is evaluated locally and reported with weaknesses and "
    "how to fix them."
)
def check_password(password: str) -> str:
    return _run_netpass(["--check-password", password])


def _saved_wifi_password() -> str:
    """Read the PSK of the active WiFi connection via nmcli.

    Used when netpass is unavailable (or its project checkout is missing). Reads
    only the local NetworkManager profile; the key never leaves the machine.
    """
    def nmcli(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["nmcli", *args], capture_output=True, text=True,
                              timeout=15)

    active = nmcli(["-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
    if active.returncode != 0:
        return f"Could not read NetworkManager connections: {(active.stderr or '').strip()}"
    wifi: list[str] = []
    for line in (active.stdout or "").splitlines():
        if not line.strip():
            continue
        name, _, typ = line.partition(":")
        if typ.strip() == "802-11-wireless" and name:
            wifi.append(name.replace("\\:", ":"))
    if not wifi:
        return "Not connected to a WiFi network."
    for name in wifi:
        for prop in ("802-11-wireless-security.psk", "wifi-sec.psk"):
            r = nmcli(["-s", "-g", prop, "connection", "show", name])
            psk = (r.stdout or "").strip()
            if r.returncode == 0 and psk:
                return f"SSID/connection: {name}\nWiFi password: {psk}"
    return ("Connected to WiFi, but the saved password for "
            f"{', '.join(wifi)} is not readable without administrator access.")


@tool(
    "Show the saved WiFi password for the network this machine is connected to. Reads "
    "NetworkManager's local profile (nmcli) and never sends the key anywhere. Falls back "
    "to netpass if nmcli has no saved key."
)
def check_wifi_password() -> str:
    out = _run_netpass(["--check-wifi"])
    if out.startswith("netpass not found"):
        return _saved_wifi_password()
    return out


@tool(
    "Scan your local network for devices and flag risky exposed services (telnet, SMB, "
    "exposed databases, open proxies, outdated services, etc.) with plain-language fixes, "
    "via the netpass program (needs root for full host/MAC/OS detection; it elevates "
    "without prompting, so where a sudo password is required it points you at the "
    "dashboard's Network Check panel instead). "
    "target: a host, hostname, or CIDR range; leave blank to auto-detect your /24 subnet. "
    "deep=True also runs nmap's CVE scripts (much slower). Use only on networks you own or "
    "are authorized to scan."
)
def scan_local_network(target: str = "", deep: bool = False) -> str:
    return run_scan(target, deep)


@tool(
    "Check what your network exposes to the public internet, via the netpass program "
    "(Shodan's free InternetDB). Shows your public IP, any internet-reachable ports with "
    "hardening advice, and known CVEs seen on that IP. Contacts external services, which "
    "will see your IP."
)
def external_exposure_check() -> str:
    return _run_netpass(["--external"])
