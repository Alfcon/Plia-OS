from __future__ import annotations
import ipaddress
import json
import logging
import random
import re
import subprocess

from core.registry import tool
from agents.memory_store import get_memory_store

logger = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

# Interfaces created by container/VM runtimes (Docker/Podman bridges and their
# veth pairs, libvirt bridges…). They aren't real adapters, so auto-detection
# skips them and the dashboard hides them from the interface dropdowns.
_VIRTUAL_IFACE_RE = re.compile(r"^(?:veth|docker|br-|virbr|vmnet|vnet|dummy)")


def _is_virtual_iface(name: str) -> bool:
    return bool(name) and _VIRTUAL_IFACE_RE.match(name) is not None


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
            if _is_virtual_iface(iface.get("ifname", "")):
                continue
            return iface["ifname"], iface.get("address", "")
    raise ValueError("No active network interface found.")


def _random_mac() -> str:
    octets = [random.randint(0, 255) for _ in range(6)]
    octets[0] = (octets[0] & 0xFE) | 0x02
    return ":".join(f"{o:02x}" for o in octets)


def _has_mac_admin() -> bool:
    import pathlib
    from core.config import get_config
    cfg = get_config()
    sudoers_ok = pathlib.Path("/etc/sudoers.d/plia-mac").exists()
    any_tool_admin = any(
        cfg.tool_permissions.get(t) == "admin"
        for t in ("randomize_mac", "set_mac", "restore_mac")
    )
    return sudoers_ok and any_tool_admin


def _run_ip(*args: str) -> subprocess.CompletedProcess:
    privileged = _has_mac_admin() or _has_ip_admin()
    cmd = ["sudo", "ip", *args] if privileged else ["ip", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=5)


def _apply_mac(ifname: str, mac: str) -> str | None:
    """Run ip link down/address/up. Returns error string on failure, None on success."""
    if not _has_mac_admin():
        return (
            "Permission denied. Enable 'Network Interface Control' and set these tools to Admin "
            "in Settings → Permissions, then run the grant command shown there."
        )
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
        if _is_virtual_iface(name):
            continue
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


def _run_timed(cmd: list[str], timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run that reports a timeout as a failed result instead of raising."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr=f"timed out after {timeout}s")


def _nmcli_devices() -> list[tuple[str, str, str, str]]:
    """Return (device, type, state, connection) per nmcli device. Raises ValueError if nmcli fails."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "--escape", "no", "dev", "status"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("nmcli not available.") from None
    if result.returncode != 0:
        raise ValueError("nmcli not available.")
    rows = []
    for line in result.stdout.splitlines():
        # CONNECTION is last so a connection name containing ':' stays intact.
        parts = line.split(":", 3)
        if len(parts) == 4:
            rows.append((parts[0], parts[1], parts[2], parts[3]))
    return rows


@tool(description="List all WiFi interfaces on this system with their current state and connection.")
def list_wifi_interfaces() -> str:
    try:
        devices = _nmcli_devices()
    except ValueError as exc:
        return str(exc)
    rows = [
        (dev, itype, state, conn or "—")
        for dev, itype, state, conn in devices
        if itype in ("wifi", "wifi-p2p")
    ]
    if not rows:
        return "No WiFi interfaces found."
    w = max(len(r[0]) for r in rows)
    return "\n".join(f"{dev:<{w}}  {itype:<10}  {state:<20}  {conn}" for dev, itype, state, conn in rows)


_WIFI_ROW_RE = re.compile(
    r"^(?P<ssid>.*?):(?P<bssid>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})"
    r":(?P<signal>\d+):(?P<security>[^:]*):(?P<chan>\d+)$"
)


def parse_nmcli_wifi_row(line: str) -> dict | None:
    """Parse one terse ``nmcli dev wifi list`` row: SSID,BSSID,SIGNAL,SECURITY,CHAN.

    An SSID may itself contain colons and nmcli runs with ``--escape no``, so the
    BSSID is located by its MAC shape instead of naive ``:``-splitting. Returns
    None for a line that does not carry a BSSID.
    """
    m = _WIFI_ROW_RE.match((line or "").strip())
    if not m:
        return None
    return {
        "ssid": m.group("ssid") or "<hidden>",
        "bssid": m.group("bssid").upper(),
        "signal": int(m.group("signal")),
        "security": m.group("security") or "open",
        "chan": m.group("chan"),
    }


@tool(description="Scan for nearby WiFi networks and show SSID, MAC address (BSSID), signal strength, security type, and channel.")
def scan_wifi(interface: str = "") -> str:
    result = subprocess.run(
        ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,SECURITY,CHAN", "--escape", "no", "dev", "wifi", "list"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return f"Scan failed: {result.stderr.strip() or 'nmcli not available'}"
    rows = []
    seen: set = set()
    for line in result.stdout.strip().splitlines():
        net = parse_nmcli_wifi_row(line)
        if not net or net["bssid"] in seen:
            continue
        seen.add(net["bssid"])
        rows.append(net)
    if not rows:
        return "No networks found."
    rows.sort(key=lambda n: -n["signal"])
    w = max([len(n["ssid"]) for n in rows] + [4])
    header = f"{'SSID':<{w}}  {'BSSID':<17}  SIG  SECURITY      CH"
    body = [
        f"{n['ssid']:<{w}}  {n['bssid']}  {n['signal']:>3}%  {n['security']:<12}  ch{n['chan']}"
        for n in rows
    ]
    return "\n".join([header] + body)


@tool(description="Show current WiFi connection status including SSID, signal strength, interface, and IP address.")
def wifi_status() -> str:
    dev_result = subprocess.run(
        ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION,DEVICE", "--escape", "no", "dev", "status"],
        capture_output=True, text=True, timeout=5,
    )
    if dev_result.returncode != 0:
        return "nmcli not available."
    connected = None
    for line in dev_result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] == "wifi" and "connected" in parts[1] and parts[2]:
            connected = {"ssid": parts[2], "device": parts[3]}
            break
    if not connected:
        return "Not connected to any WiFi network."
    iface = connected["device"]
    signal_result = subprocess.run(
        ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY,CHAN", "--escape", "no", "dev", "wifi", "list"],
        capture_output=True, text=True, timeout=5,
    )
    signal = "?"
    chan = "?"
    security = "?"
    for line in signal_result.stdout.splitlines():
        parts = line.rsplit(":", 4)
        if len(parts) >= 5 and parts[0] == "yes":
            signal = parts[2]
            security = parts[3]
            chan = parts[4]
            break
    ip_result = subprocess.run(
        ["ip", "-4", "addr", "show", iface],
        capture_output=True, text=True, timeout=5,
    )
    ip = "?"
    for line in ip_result.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            ip = line.split()[1]
            break
    return (
        f"Interface  {iface}\n"
        f"SSID       {connected['ssid']}\n"
        f"Signal     {signal}%\n"
        f"Security   {security}\n"
        f"Channel    {chan}\n"
        f"IP         {ip}"
    )


# ── WiFi connect / saved networks ────────────────────────────────────────────

def _nmcli_wifi_profiles() -> list[str]:
    """Saved NetworkManager WiFi connection names (usually SSIDs). Empty on failure."""
    r = subprocess.run(
        ["nmcli", "-t", "-f", "NAME,TYPE", "--escape", "no", "connection", "show"],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode != 0:
        return []
    names = []
    for line in r.stdout.splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and "wireless" in parts[1].lower():
            names.append(parts[0])
    return names


def _scan_wifi_networks() -> list[tuple[str, int, str]]:
    """Return [(ssid, signal, security)] sorted by signal (best first). Empty on failure."""
    r = subprocess.run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "--escape", "no", "dev", "wifi", "list"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return []
    out: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for line in r.stdout.splitlines():
        if not line:
            continue
        parts = line.rsplit(":", 2)
        if len(parts) < 3:
            continue
        ssid, signal, security = parts
        ssid = (ssid or "").strip() or "<hidden>"
        if ssid == "<hidden>" or ssid in seen:
            continue
        seen.add(ssid)
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        out.append((ssid, sig, security or "open"))
    out.sort(key=lambda x: -x[1])
    return out


def _match_ssid(target: str, available: list[tuple[str, int, str]]) -> str | None:
    """Best available SSID for a user-supplied name: exact → containment → strongest."""
    t = target.strip().lower()
    if not t:
        return None
    for ssid, _, _ in available:
        if ssid.lower() == t:
            return ssid
    best: tuple[int, str] | None = None
    for ssid, sig, _ in available:
        sl = ssid.lower()
        if t in sl or sl in t:
            if best is None or sig > best[0]:
                best = (sig, ssid)
    return best[1] if best else None


def _resolve_target(ssid: str, available: list[tuple[str, int, str]], profiles: list[str]) -> str:
    """Resolve a user-supplied name to an SSID, preferring saved profiles on ambiguity
    (e.g. 'home' → saved 'Home Network' rather than the stronger 'Home Network 5G')."""
    t = ssid.strip().lower()
    # 1. exact saved profile
    for p in profiles:
        if p.lower() == t:
            return p
    # 2. exact available SSID
    for s, _, _ in available:
        if s.lower() == t:
            return s
    # 3. saved profile containment
    for p in profiles:
        pl = p.lower()
        if t in pl or pl in t:
            return p
    # 4. available containment (strongest signal)
    matched = _match_ssid(ssid, available)
    if matched:
        return matched
    # 5. literal fallback (e.g. a hidden network named exactly as typed)
    return ssid.strip()


def _saved_networks_in_range(available: list[tuple[str, int, str]], profiles: list[str]) -> list[str]:
    """Available SSIDs (best signal first) that have a saved profile."""
    pl = {p.lower() for p in profiles}
    return [ssid for ssid, _, _ in available if ssid.lower() in pl]


def _run_connect(cmd: list[str], ssid: str, has_password: bool) -> tuple[str, bool]:
    """Run an nmcli connect command. Returns (message, needs_password)."""
    r = _run_timed(cmd, timeout=45)
    if r.returncode == 0:
        return f"Connected to '{ssid}'.", False
    err = (r.stderr or r.stdout or "unknown error").strip()
    needs_password = not has_password and ("secret" in err.lower() or "password" in err.lower())
    if needs_password:
        return (
            f"Could not connect to '{ssid}': this network needs a password and no saved "
            f"profile was found for it.",
            True,
        )
    return f"Could not connect to '{ssid}': {err}", False


def _try_gain_access(ssid: str, interface: str) -> str:
    """Escalate a missing-password connect to the wireless access-recovery tools."""
    try:
        from modules.wireless_tools import gain_wifi_access
        return gain_wifi_access(ssid, interface)
    except Exception as exc:
        return f"Automatic key recovery is not available here: {exc}. Provide the password to connect."


@tool(description="Connect to a WiFi network, reusing saved credentials so no password is needed for networks you've joined before. Leave ssid empty to connect to the strongest in-range saved network. Pass password only for a brand-new network.")
def connect_wifi(ssid: str = "", interface: str = "", password: str = "") -> str:
    available = _scan_wifi_networks()
    profiles = _nmcli_wifi_profiles()
    has_password = bool(password.strip())

    target: str
    if ssid.strip():
        target = _resolve_target(ssid, available, profiles)
    else:
        in_range = _saved_networks_in_range(available, profiles)
        if in_range:
            target = in_range[0]
        elif len(profiles) == 1:
            # Single saved profile (possibly hidden or an empty scan) — bring it up directly.
            target = profiles[0]
            cmd = ["nmcli", "connection", "up", target]
            if interface.strip():
                cmd += ["ifname", interface.strip()]
            msg, needs_password = _run_connect(cmd, target, has_password=False)
            if needs_password:
                return msg + "\n" + _try_gain_access(target, interface)
            return msg
        else:
            saved = ", ".join(profiles) if profiles else "none"
            return (
                "No saved WiFi network is currently in range, so I don't know which network "
                "to connect to. Saved networks: " + saved + ". "
                "Tell me a network name to connect to it."
            )

    cmd = ["nmcli", "device", "wifi", "connect", target]
    if has_password:
        cmd += ["password", password.strip()]
    if interface.strip():
        cmd += ["ifname", interface.strip()]
    msg, needs_password = _run_connect(cmd, target, has_password)
    if needs_password:
        return msg + "\n" + _try_gain_access(target, interface)
    return msg


@tool(description="List WiFi networks this computer has saved (joined before) and can reconnect to without entering a password.")
def list_saved_wifi() -> str:
    profiles = _nmcli_wifi_profiles()
    if not profiles:
        return "No saved WiFi networks found."
    return "Saved WiFi networks:\n" + "\n".join(f"- {p}" for p in profiles)


# ── USB WiFi dongle enable/disable ───────────────────────────────────────────
def _wifi_device_names() -> list[str]:
    """WiFi device names known to nmcli (including unmanaged ones). Raises ValueError if nmcli fails."""
    return [dev for dev, itype, _, _ in _nmcli_devices() if itype == "wifi"]


def _is_usb_iface(ifname: str) -> bool:
    import os
    try:
        target = os.readlink(f"/sys/class/net/{ifname}")
    except OSError:
        return False
    return "/usb" in target


def _detect_dongle(interface: str = "") -> str:
    """Return the USB WiFi dongle interface name. Raises ValueError if missing, unknown, or ambiguous."""
    wifi = _wifi_device_names()
    if interface:
        if interface not in wifi:
            raise ValueError(f"WiFi interface {interface!r} not found.")
        return interface
    usb = [d for d in wifi if _is_usb_iface(d)]
    if len(usb) == 1:
        return usb[0]
    if len(usb) > 1:
        raise ValueError(f"Multiple USB WiFi interfaces found: {', '.join(usb)}. Pass one explicitly.")
    # Fall back to name-based detection (wlx<mac> is the predictable USB WiFi name).
    wlx = [d for d in wifi if d.startswith("wlx")]
    if len(wlx) == 1:
        return wlx[0]
    if len(wlx) > 1:
        raise ValueError(f"Multiple USB WiFi interfaces found: {', '.join(wlx)}. Pass one explicitly.")
    raise ValueError("No USB WiFi dongle detected. Plug it in, or pass the interface name explicitly.")


@tool(description="Enable the USB WiFi dongle: mark it managed, turn on autoconnect, and bring it up so NetworkManager reconnects it. Leave interface empty to auto-detect the USB WiFi adapter.")
def enable_wifi_dongle(interface: str = "") -> str:
    try:
        dev = _detect_dongle(interface)
    except ValueError as exc:
        return str(exc)
    errors = []
    for args in (
        ["nmcli", "device", "set", dev, "managed", "yes"],
        ["nmcli", "device", "set", dev, "autoconnect", "yes"],
    ):
        r = _run_timed(args, timeout=10)
        if r.returncode != 0:
            errors.append(r.stderr.strip() or "unknown error")
    r = _run_timed(["nmcli", "device", "connect", dev], timeout=45)
    if r.returncode != 0:
        errors.append(r.stderr.strip() or "unknown error")
    if errors:
        return f"Enabled dongle {dev} with warnings: {'; '.join(errors)}"
    return f"Dongle {dev} enabled: managed, autoconnect on, and connected."


@tool(description="Disable the USB WiFi dongle: disconnect it and turn off autoconnect so it stays down until re-enabled. Leave interface empty to auto-detect the USB WiFi adapter.")
def disable_wifi_dongle(interface: str = "") -> str:
    try:
        dev = _detect_dongle(interface)
    except ValueError as exc:
        return str(exc)
    errors = []
    r = _run_timed(["nmcli", "device", "disconnect", dev], timeout=15)
    if r.returncode != 0:
        errors.append(r.stderr.strip() or "unknown error")
    r = _run_timed(["nmcli", "device", "set", dev, "autoconnect", "no"], timeout=10)
    if r.returncode != 0:
        errors.append(r.stderr.strip() or "unknown error")
    if errors:
        return f"Disabled dongle {dev} with warnings: {'; '.join(errors)}"
    return f"Dongle {dev} disabled: disconnected and autoconnect off."


# ── Internal WiFi driver blacklist (full disable) ────────────────────────────
_BLACKLIST_CONF = "/etc/modprobe.d/disable-internal-wifi.conf"
_BLACKLIST_CONTENT = "blacklist iwlmvm\nblacklist iwlwifi\ninstall iwlwifi /bin/false\n"
_INTERNAL_WIFI_DENIED = (
    "Permission denied. Enable 'Internal WiFi Blacklist' and set these tools to Admin "
    "in Settings → Permissions, then run the grant command shown there."
)


def _has_internal_wifi_admin() -> bool:
    import pathlib
    from core.config import get_config
    cfg = get_config()
    sudoers_ok = pathlib.Path("/etc/sudoers.d/plia-iwlwifi").exists()
    any_tool_admin = any(
        cfg.tool_permissions.get(t) == "admin"
        for t in ("disable_internal_wifi", "enable_internal_wifi")
    )
    return sudoers_ok and any_tool_admin


def _iwl_loaded() -> bool:
    r = subprocess.run(["lsmod"], capture_output=True, text=True, timeout=5)
    return "iwlwifi" in r.stdout or "iwlmvm" in r.stdout


@tool(description="Show whether the internal Intel WiFi driver (iwlwifi/iwlmvm) is blacklisted and currently loaded.")
def internal_wifi_status() -> str:
    import pathlib
    blacklisted = pathlib.Path(_BLACKLIST_CONF).exists()
    return (
        f"Blacklist file  {'present' if blacklisted else 'absent'}  ({_BLACKLIST_CONF})\n"
        f"iwlwifi loaded  {'yes' if _iwl_loaded() else 'no'}"
    )


@tool(description="Full-disable the internal Intel WiFi card by blacklisting its driver (iwlwifi/iwlmvm) so it never loads. Writes /etc/modprobe.d and rebuilds the initramfs; a reboot is required to take effect. Use this for freeze testing on the USB dongle. Requires Admin + the Internal WiFi Blacklist grant.")
def disable_internal_wifi() -> str:
    if not _has_internal_wifi_admin():
        return _INTERNAL_WIFI_DENIED
    r = _run_timed(["sudo", "tee", _BLACKLIST_CONF], timeout=15, input=_BLACKLIST_CONTENT)
    if r.returncode != 0:
        return f"Failed to write blacklist file: {r.stderr.strip() or 'unknown error'}"
    r = _run_timed(["sudo", "update-initramfs", "-u"], timeout=180)
    if r.returncode != 0:
        return f"Blacklist written, but update-initramfs failed: {r.stderr.strip() or 'unknown error'}"
    return (
        "Internal WiFi driver blacklisted and initramfs rebuilt. Reboot to apply — after reboot "
        "the internal card (iwlwifi) will not load, so use the USB dongle. Undo with enable_internal_wifi."
    )


@tool(description="Undo the internal WiFi blacklist: remove the blacklist file, rebuild the initramfs, and load the iwlwifi driver so the internal card works again. Requires Admin + the Internal WiFi Blacklist grant.")
def enable_internal_wifi() -> str:
    if not _has_internal_wifi_admin():
        return _INTERNAL_WIFI_DENIED
    import pathlib
    existed = pathlib.Path(_BLACKLIST_CONF).exists()
    if existed:
        r = _run_timed(["sudo", "rm", _BLACKLIST_CONF], timeout=10)
        if r.returncode != 0:
            return f"Failed to remove blacklist file: {r.stderr.strip() or 'unknown error'}"
        r = _run_timed(["sudo", "update-initramfs", "-u"], timeout=180)
        if r.returncode != 0:
            return f"Blacklist removed, but update-initramfs failed: {r.stderr.strip() or 'unknown error'}"
    r = _run_timed(["sudo", "modprobe", "iwlwifi"], timeout=15)
    load_note = (
        "iwlwifi loaded — internal WiFi is back"
        if r.returncode == 0
        else f"could not load iwlwifi now ({r.stderr.strip() or 'unknown error'}); reboot to restore it"
    )
    prefix = "Blacklist removed and initramfs rebuilt. " if existed else "No blacklist file was present. "
    return prefix + load_note + "."


# ── Local IP masking ─────────────────────────────────────────────────────────
def _get_ipv4(ifname: str) -> str | None:
    try:
        r = subprocess.run(
            ["ip", "-j", "-4", "addr", "show", ifname],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(r.stdout or "[]")
    except Exception:
        return None
    for entry in data:
        for ai in entry.get("addr_info", []):
            if ai.get("family") == "inet" and ai.get("local"):
                return f"{ai['local']}/{ai.get('prefixlen', 24)}"
    return None


def _resolve_ip_iface(interface: str) -> str:
    try:
        ifaces = _get_interfaces()
    except Exception:
        ifaces = []
    names = {i.get("ifname") for i in ifaces}
    if interface:
        if interface in names:
            return interface
        raise ValueError(f"Interface {interface!r} not found.")
    try:
        r = subprocess.run(
            ["ip", "-j", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        for rt in json.loads(r.stdout or "[]"):
            if rt.get("dev") and not _is_virtual_iface(rt["dev"]):
                return rt["dev"]
    except Exception:
        pass
    for i in ifaces:
        name = i.get("ifname")
        if name and name != "lo" and not _is_virtual_iface(name) and _get_ipv4(name):
            return name
    raise ValueError("No active network interface with an IPv4 address found.")


def _random_host_in_subnet(cidr: str, avoid: set[str]) -> str:
    net = ipaddress.ip_network(cidr, strict=False)
    if net.num_addresses <= 4:
        raise ValueError("Subnet too small to pick a different host.")
    first = int(net.network_address) + 1
    last = int(net.broadcast_address) - 1
    gateway = str(ipaddress.ip_address(first))  # .1 heuristic
    for _ in range(100):
        cand = str(ipaddress.ip_address(random.randint(first, last)))
        if cand not in avoid and cand != gateway:
            return f"{cand}/{net.prefixlen}"
    raise ValueError("Could not pick a free host in the subnet.")


def _has_ip_admin() -> bool:
    import pathlib
    from core.config import get_config
    cfg = get_config()
    sudoers_ok = pathlib.Path("/etc/sudoers.d/plia-mac").exists()
    any_admin = any(
        cfg.tool_permissions.get(t) == "admin"
        for t in ("randomize_local_ip", "set_local_ip", "restore_ip")
    )
    return sudoers_ok and any_admin


def _apply_ip(ifname: str, new_cidr: str, old_cidr: str | None) -> str | None:
    if not _has_ip_admin():
        return (
            "Permission denied. Enable 'Network Interface Control' and set these tools to Admin "
            "in Settings → Permissions, then run the grant command shown there."
        )
    try:
        r = _run_ip("addr", "add", new_cidr, "dev", ifname)
        if r.returncode != 0 and "exists" not in (r.stderr or "").lower():
            return r.stderr.strip() or "unknown error"
        if old_cidr and old_cidr != new_cidr:
            _run_ip("addr", "del", old_cidr, "dev", ifname)  # best-effort
    except subprocess.TimeoutExpired:
        return f"timed out on {ifname}"
    except Exception as exc:
        return f"ip command failed: {exc}"
    return None


def _save_original_ip_if_new(ifname: str, cidr: str) -> None:
    store = get_memory_store()
    if store.get_fact(f"original_ip_{ifname}") is None:
        store.remember(f"original_ip_{ifname}", cidr)


@tool(description="Show the current local IPv4 address (and subnet) of a network interface. Leave interface empty to auto-detect the active interface.")
def show_ip(interface: str = "") -> str:
    try:
        ifname = _resolve_ip_iface(interface)
    except ValueError as exc:
        return str(exc)
    cidr = _get_ipv4(ifname)
    if cidr is None:
        return f"{ifname}: no IPv4 address."
    return f"{ifname}: {cidr}"


@tool(description="Mask the local IP: change this machine's LAN IPv4 to a random unused address in the same subnet (saves the original for restore). Transient — reverts on network refresh/reboot, and briefly drops connections on that interface. Leave interface empty to auto-detect.")
def randomize_local_ip(interface: str = "") -> str:
    try:
        ifname = _resolve_ip_iface(interface)
    except ValueError as exc:
        return str(exc)
    cur = _get_ipv4(ifname)
    if cur is None:
        return f"{ifname}: no IPv4 address to change."
    _save_original_ip_if_new(ifname, cur)
    try:
        new = _random_host_in_subnet(cur, avoid={cur.split("/")[0]})
    except ValueError as exc:
        return str(exc)
    err = _apply_ip(ifname, new, cur)
    if err:
        return f"IP change failed: {err}"
    return f"{ifname}: {cur} → {new}"


@tool(description="Set the local IPv4 address of an interface to a specific value. Format A.B.C.D/prefix (e.g. 192.168.1.50/24). Saves the original for restore. Transient. Leave interface empty to auto-detect.")
def set_local_ip(interface: str = "", ip_cidr: str = "") -> str:
    try:
        if "/" not in ip_cidr:
            raise ValueError
        obj = ipaddress.ip_interface(ip_cidr)
        if obj.version != 4:
            raise ValueError
    except Exception:
        return "Invalid address. Expected A.B.C.D/prefix, e.g. 192.168.1.50/24."
    try:
        ifname = _resolve_ip_iface(interface)
    except ValueError as exc:
        return str(exc)
    cur = _get_ipv4(ifname)
    if cur:
        _save_original_ip_if_new(ifname, cur)
    err = _apply_ip(ifname, ip_cidr, cur)
    if err:
        return f"IP change failed: {err}"
    return f"{ifname}: set to {ip_cidr}"


@tool(description="Restore the original local IPv4 address of an interface (saved before it was changed via Plia-OS). Leave interface empty to auto-detect.")
def restore_ip(interface: str = "") -> str:
    try:
        ifname = _resolve_ip_iface(interface)
    except ValueError as exc:
        return str(exc)
    original = get_memory_store().get_fact(f"original_ip_{ifname}")
    if original is None:
        return f"No original IP stored for {ifname}. Randomize or set first."
    cur = _get_ipv4(ifname)
    err = _apply_ip(ifname, original, cur)
    if err:
        return f"IP change failed: {err}"
    return f"{ifname}: restored to {original}"
