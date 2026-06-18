from __future__ import annotations
import json
import logging
import random
import re
import subprocess

from core.registry import tool
from agents.memory_store import get_memory_store

logger = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _get_interfaces() -> list[dict]:
    result = subprocess.run(
        ["ip", "-j", "link", "show"],
        capture_output=True,
        timeout=5,
    )
    return json.loads(result.stdout or "[]")


def _resolve_and_get_mac(interface: str) -> tuple[str, str]:
    """Return (ifname, current_mac). Raises ValueError if interface not found."""
    ifaces = _get_interfaces()
    if interface:
        for iface in ifaces:
            if iface.get("ifname") == interface:
                return interface, iface.get("address", "")
        raise ValueError(f"Interface {interface!r} not found.")
    for iface in ifaces:
        if iface.get("link_type") == "ether" and "UP" in iface.get("flags", []):
            return iface["ifname"], iface.get("address", "")
    raise ValueError("No active network interface found.")


def _random_mac() -> str:
    octets = [random.randint(0, 255) for _ in range(6)]
    octets[0] = (octets[0] & 0xFE) | 0x02
    return ":".join(f"{o:02x}" for o in octets)


def _run_ip(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ip", *args], capture_output=True, text=True, timeout=5)


def _apply_mac(ifname: str, mac: str) -> str | None:
    """Run ip link down/address/up. Returns error string on failure, None on success."""
    try:
        r = _run_ip("link", "set", "dev", ifname, "down")
        if r.returncode != 0:
            return r.stderr.strip() or "unknown error"
        r = _run_ip("link", "set", "dev", ifname, "address", mac)
        if r.returncode != 0:
            # Restore interface even if address change failed
            _run_ip("link", "set", "dev", ifname, "up")
            return r.stderr.strip() or "unknown error"
        r = _run_ip("link", "set", "dev", ifname, "up")
        if r.returncode != 0:
            return r.stderr.strip() or "unknown error"
    except subprocess.TimeoutExpired:
        return f"timed out on {ifname}"
    return None


def _save_original_if_new(ifname: str, current_mac: str) -> None:
    store = get_memory_store()
    if store.get_fact(f"original_mac_{ifname}") is None:
        store.remember(f"original_mac_{ifname}", current_mac)


@tool(description="List all network interfaces with their MAC addresses and type (Ethernet/WiFi).")
def list_macs() -> str:
    ifaces = _get_interfaces()
    rows = []
    for iface in ifaces:
        if iface.get("link_type") != "ether":
            continue
        name = iface["ifname"]
        mac = iface.get("address", "unknown")
        if name.startswith("wl"):
            itype = "WiFi"
        elif name.startswith(("en", "eth")):
            itype = "Ethernet"
        else:
            itype = "Other"
        rows.append((name, mac, itype))
    if not rows:
        return "No network interfaces found."
    w = max(len(r[0]) for r in rows)
    return "\n".join(f"{name:<{w}}  {mac}  {itype}" for name, mac, itype in rows)


@tool(description="Show the current MAC address of a network interface. Leave interface empty to auto-detect.")
def show_mac(interface: str = "") -> str:
    try:
        ifname, mac = _resolve_and_get_mac(interface)
    except ValueError as exc:
        return str(exc)
    return f"{ifname}: {mac}"


@tool(description="Randomize the MAC address of a network interface. Saves original MAC for later restore. Leave interface empty to auto-detect.")
def randomize_mac(interface: str = "") -> str:
    try:
        ifname, old_mac = _resolve_and_get_mac(interface)
    except ValueError as exc:
        return str(exc)
    _save_original_if_new(ifname, old_mac)
    new_mac = _random_mac()
    err = _apply_mac(ifname, new_mac)
    if err:
        return f"MAC change failed: {err}"
    return f"{ifname}: {old_mac} → {new_mac}"


@tool(description="Set the MAC address of a network interface to a specific value. Format: XX:XX:XX:XX:XX:XX. Leave interface empty to auto-detect.")
def set_mac(interface: str = "", mac_address: str = "") -> str:
    if not mac_address:
        return "MAC address is required."
    if not _MAC_RE.match(mac_address):
        return "Invalid MAC address format. Expected XX:XX:XX:XX:XX:XX."
    try:
        ifname, old_mac = _resolve_and_get_mac(interface)
    except ValueError as exc:
        return str(exc)
    _save_original_if_new(ifname, old_mac)
    err = _apply_mac(ifname, mac_address)
    if err:
        return f"MAC change failed: {err}"
    return f"{ifname}: set to {mac_address}"


@tool(description="Restore the original MAC address of a network interface. Only works if MAC was previously changed via Plia-OS.")
def restore_mac(interface: str = "") -> str:
    try:
        ifname, _ = _resolve_and_get_mac(interface)
    except ValueError as exc:
        return str(exc)
    original = get_memory_store().get_fact(f"original_mac_{ifname}")
    if original is None:
        return f"No original MAC stored for {ifname}. Randomize first to save it."
    err = _apply_mac(ifname, original)
    if err:
        return f"MAC change failed: {err}"
    return f"{ifname}: restored to {original}"
