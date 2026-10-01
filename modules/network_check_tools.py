"""Network Check — defensive LAN auditing, ported from the standalone netpass tool.

Read-only, advisory checks you run on networks you own or are authorized to
test: password strength, a local device scan that flags risky exposed services,
and what your network exposes to the public internet. Nothing here changes the
system or any device — it only reports and advises.

A network scan cannot read a device's Wi-Fi password: it never crosses the
network. The password checks only evaluate a password you supply, or the saved
password of the Wi-Fi this machine is connected to (read locally).
"""
from __future__ import annotations

import logging
import re
import socket
import subprocess

from core.registry import tool

logger = logging.getLogger(__name__)


# ── Password strength ─────────────────────────────────────────────────────────
_COMMON_WEAK_PASSWORDS = {
    "password", "passw0rd", "password1", "admin", "administrator", "default",
    "guest", "root", "user", "changeme", "letmein", "welcome", "qwerty",
    "12345678", "123456789", "1234567890", "0123456789", "00000000",
    "11111111", "87654321", "abc12345", "iloveyou", "monkey", "dragon",
    "football", "sunshine", "princess", "netcomm", "wireless", "internet",
    "router", "modem", "cloudmesh",
}
_SEQUENCES = [
    "0123456789", "abcdefghijklmnopqrstuvwxyz",
    "qwertyuiop", "asdfghjkl", "zxcvbnm",
]
_FIX = (
    "Fix: use a 15+ character passphrase (e.g. 3-4 random words plus a "
    "number/symbol), keep authentication on WPA2-PSK, and save."
)


def _assess_password(pw: str | None, ssid: str | None = None) -> tuple[str, list[str]]:
    """Evaluate a password. Returns (severity, [reasons]). Never echoes the password."""
    if not pw:
        return ("HIGH", ["No password set — this is an open network."])

    low = pw.lower()
    reasons: list[str] = []
    serious = False

    if low in _COMMON_WEAK_PASSWORDS:
        reasons.append("It is a well-known default or common password.")
        serious = True
    if len(set(pw)) == 1:
        reasons.append("It is a single character repeated.")
        serious = True
    if any(low in s or low in s[::-1] for s in _SEQUENCES):
        reasons.append("It is a sequential keyboard/number pattern.")
        serious = True
    if pw.isdigit():
        reasons.append("It is all digits — a tiny keyspace that cracks quickly.")
        serious = True
    if ssid and low == ssid.lower():
        reasons.append("It is the same as the network name (SSID).")
        serious = True
    if len(pw) < 8:
        reasons.append(f"It is only {len(pw)} characters (WPA2 minimum is 8).")
        serious = True
    elif len(pw) < 12:
        reasons.append(f"It is short ({len(pw)} characters); 12+ is safer.")

    if not reasons:
        return ("OK", [])
    return ("HIGH" if serious else "MEDIUM", reasons)


def _format_password_verdict(severity: str, reasons: list[str], ssid: str | None = None) -> str:
    where = f' for "{ssid}"' if ssid else ""
    if severity == "OK":
        return f"Wi-Fi password{where}: looks strong — no obvious weaknesses."
    lines = [f"Wi-Fi password{where}: {severity} RISK — weak / guessable."]
    lines += [f"  - {r}" for r in reasons]
    lines.append(f"  {_FIX}")
    return "\n".join(lines)


@tool(
    "Check how strong a Wi-Fi password (or any password) is. Pass the password string; "
    "it is evaluated locally and never stored or sent anywhere. Reports the weaknesses "
    "found and how to fix them."
)
def check_password(password: str) -> str:
    severity, reasons = _assess_password(password)
    return _format_password_verdict(severity, reasons)


def _current_wifi() -> tuple[str | None, str | None]:
    """Return (ssid, psk) for the Wi-Fi this machine is on, via nmcli.

    psk is None if it could not be read (needs elevated access, or not stored
    here). Returns (None, None) if nmcli is unavailable or not on Wi-Fi.
    """
    try:
        active = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            capture_output=True, text=True, timeout=5,
        )
        ssid = None
        for line in active.stdout.splitlines():
            if line.startswith("yes:"):
                ssid = line.split(":", 1)[1]
                break
        if not ssid:
            return (None, None)
        secret = subprocess.run(
            ["nmcli", "-s", "-g", "802-11-wireless-security.psk",
             "connection", "show", "id", ssid],
            capture_output=True, text=True, timeout=5,
        )
        return (ssid, secret.stdout.strip() or None)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return (None, None)


@tool(
    "Check the strength of the Wi-Fi password this machine is currently connected to. "
    "Reads the saved key locally via nmcli (may need elevated access) and never sends it "
    "anywhere. Reports weaknesses and how to fix them."
)
def check_wifi_password() -> str:
    ssid, psk = _current_wifi()
    if ssid is None:
        return (
            "Could not detect a connected Wi-Fi network (nmcli unavailable, or not on "
            "Wi-Fi). Tip: check a specific password with check_password instead."
        )
    if psk is None:
        return (
            f'Connected to "{ssid}", but the saved password could not be read (it needs '
            "elevated access). Run Plia with elevated privileges, or use check_password "
            "with the key."
        )
    severity, reasons = _assess_password(psk, ssid=ssid)
    return _format_password_verdict(severity, reasons, ssid=ssid)


# ── Local device scan + service-exposure report ──────────────────────────────
# Heuristic rules keyed by port. Each flags the risk of finding that service
# exposed on the network, and how to remediate it. This is not a CVE scan —
# it flags risky configurations and exposures based on open services.
_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}

_PORT_RULES: dict[int, tuple[str, str, str, str]] = {
    21: ("MEDIUM", "FTP exposed",
         "FTP sends usernames, passwords, and files in clear text.",
         "Use SFTP (over SSH) or FTPS instead, and disable FTP if unused."),
    23: ("HIGH", "Telnet enabled",
         "Telnet transmits credentials and all data unencrypted; anyone on the path can read them.",
         "Disable telnet (in the device/router admin page) and use SSH."),
    25: ("LOW", "SMTP exposed",
         "A mail service is reachable; open relays and plaintext auth are common misconfigurations.",
         "Require TLS and authentication; do not allow open relaying."),
    111: ("MEDIUM", "RPC portmapper exposed",
          "rpcbind/NFS services are often exploitable and leak information.",
          "Firewall port 111 and NFS ports to trusted hosts, or disable NFS."),
    135: ("MEDIUM", "Windows RPC exposed",
          "MS RPC is a frequent target for remote exploits.",
          "Restrict to trusted networks with the firewall; keep Windows patched."),
    139: ("MEDIUM", "NetBIOS/SMB exposed",
          "Legacy SMB (SMBv1) and NetBIOS have serious known exploits (e.g. EternalBlue).",
          "Disable SMBv1, restrict SMB to trusted hosts, and never expose it to the internet."),
    445: ("MEDIUM", "SMB file sharing exposed",
          "SMB is a major ransomware/worm vector when reachable and unpatched.",
          "Keep it patched, disable SMBv1, and firewall it to trusted hosts."),
    1080: ("HIGH", "SOCKS proxy exposed",
           "An open SOCKS proxy can relay traffic for anyone who reaches it.",
           "Require authentication or firewall it to trusted hosts; disable it if unexpected."),
    3128: ("HIGH", "HTTP proxy exposed",
           "An open HTTP proxy (e.g. Squid) can be abused as a relay.",
           "Require authentication and restrict access; disable if unexpected."),
    3306: ("HIGH", "MySQL/MariaDB exposed",
           "A database reachable over the network is a direct data-theft risk.",
           "Bind it to localhost, require strong auth, and firewall the port."),
    3389: ("HIGH", "Remote Desktop (RDP) exposed",
           "RDP is heavily targeted by brute-force and exploit attacks.",
           "Restrict to VPN/trusted IPs, enforce NLA and strong passwords/MFA."),
    5432: ("HIGH", "PostgreSQL exposed",
           "A database reachable over the network is a direct data-theft risk.",
           "Bind it to localhost, require strong auth, and firewall the port."),
    5900: ("HIGH", "VNC exposed",
           "VNC often has weak or no authentication and sends screens in clear.",
           "Use a strong password, tunnel over SSH/VPN, and do not expose it."),
    6379: ("HIGH", "Redis exposed",
           "Redis defaults to no authentication and allows remote code paths.",
           "Bind to localhost, set a password (requirepass), and firewall it."),
    9200: ("HIGH", "Elasticsearch exposed",
           "Open Elasticsearch instances routinely leak entire datasets.",
           "Enable authentication and bind it to localhost/trusted hosts."),
    27017: ("HIGH", "MongoDB exposed",
            "Unauthenticated MongoDB has caused many mass data breaches.",
            "Enable authentication and bind it to localhost/trusted hosts."),
    161: ("MEDIUM", "SNMP exposed",
          'SNMP often uses default community strings ("public") that leak device details.',
          "Disable SNMP or use SNMPv3 with authentication; change defaults."),
    554: ("MEDIUM", "RTSP camera stream exposed",
          "Camera streams are frequently unauthenticated and world-viewable.",
          "Enable authentication, keep firmware updated, and restrict to LAN/VPN."),
    8080: ("LOW", "HTTP service on 8080",
           "Alternate web ports often host admin panels over plaintext HTTP.",
           "Use HTTPS and ensure default credentials have been changed."),
}

# A CVE id optionally followed by a CVSS score, as printed by nmap's `vulners`.
_CVE_RE = re.compile(r"(CVE-\d{4}-\d{3,7})(?:\s+(\d+\.\d+))?")


def _local_subnet() -> str:
    """Best-effort guess of the local /24 subnet (e.g. '192.168.1.0/24')."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # sets dest without sending; reads chosen local IP
        ip = s.getsockname()[0]
        s.close()
        o = ip.split(".")
        return f"{o[0]}.{o[1]}.{o[2]}.0/24"
    except OSError:
        return "192.168.1.0/24"


def _assess_host(tcp: dict) -> list[dict]:
    """Security findings for one host's TCP services (exposure heuristics)."""
    findings: list[dict] = []
    for port_str, info in tcp.items():
        if info.get("state") != "open":
            continue
        port = int(port_str)
        name = (info.get("name") or "").lower()
        product = info.get("product") or ""
        version = info.get("version") or ""
        extra = (info.get("extrainfo") or "").lower()

        rule = _PORT_RULES.get(port)
        if rule:
            sev, title, detail, fix = rule
            findings.append({"severity": sev, "port": port, "title": title,
                             "detail": detail, "fix": fix})
        if "socks" in name and "no authentication" in extra and port != 1080:
            findings.append({
                "severity": "HIGH", "port": port, "title": "Unauthenticated SOCKS proxy",
                "detail": "This proxy accepts connections with no authentication.",
                "fix": "Require authentication or firewall it; disable if unexpected."})
        if port == 80 and name in ("http", "tcpwrapped"):
            findings.append({
                "severity": "LOW", "port": port, "title": "Unencrypted HTTP service",
                "detail": "A web interface is served over plain HTTP.",
                "fix": "Serve it over HTTPS and change any default credentials."})
        if "dropbear" in product.lower() and version.startswith("0."):
            findings.append({
                "severity": "MEDIUM", "port": port,
                "title": f"Outdated SSH server (Dropbear {version})",
                "detail": "This SSH version is very old and may have known flaws.",
                "fix": "Update the device firmware to get a current SSH server."})

    findings.sort(key=lambda f: (_SEVERITY_ORDER[f["severity"]], f["port"]))
    return findings


def _script_findings(tcp: dict) -> list[dict]:
    """Turn nmap vuln-script output (deep scan) into security findings."""
    findings: list[dict] = []
    for port_str, info in tcp.items():
        if info.get("state") != "open":
            continue
        port = int(port_str)
        for sid, output in (info.get("script") or {}).items():
            text = output or ""
            confirmed = "VULNERABLE" in text.upper()
            cves: dict[str, float | None] = {}
            for cve, score in _CVE_RE.findall(text):
                val = float(score) if score else None
                if val is not None and (cves.get(cve) is None or val > cves[cve]):
                    cves[cve] = val
                else:
                    cves.setdefault(cve, None)
            if not confirmed and not cves:
                continue
            scores = [s for s in cves.values() if s is not None]
            top = max(scores) if scores else None
            if confirmed:
                sev = "HIGH"
            elif top is not None:
                sev = "HIGH" if top >= 7 else "MEDIUM" if top >= 4 else "LOW"
            else:
                sev = "MEDIUM"
            ordered = sorted(cves.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0)))
            shown = ", ".join(f"{c} ({s})" if s is not None else c for c, s in ordered[:8])
            more = len(ordered) - 8
            if more > 0:
                shown += f", +{more} more"
            if confirmed:
                detail = f'nmap script "{sid}" reports this host as VULNERABLE.'
                fix = "Confirm and patch the affected service/firmware; see the referenced CVEs."
            else:
                detail = f'nmap "{sid}" flagged CVEs matching this service version: {shown or "see output"}.'
                fix = ("Update the service/firmware to a patched version. Version-based matches "
                       "may include false positives — verify each CVE applies.")
            findings.append({"severity": sev, "port": port,
                             "title": f"CVEs reported by {sid}", "detail": detail, "fix": fix})
    return findings


def _scan_network(ip_range: str, deep: bool):
    """Run an unprivileged nmap service scan. Returns list of host dicts.

    Raises RuntimeError with a user-facing message if nmap cannot be used.
    """
    try:
        import nmap  # python-nmap
    except ImportError as exc:
        raise RuntimeError(
            "The local network scan needs python-nmap. Install it with "
            "`pip install python-nmap` (the nmap binary is also required)."
        ) from exc

    arguments = ["-sV"]  # service/version detection — no root needed
    if deep:
        # vulners maps service versions to CVEs; vuln actively checks known flaws.
        arguments += ["--script vuln,vulners", "--host-timeout 180s"]

    scanner = nmap.PortScanner()
    try:
        scanner.scan(hosts=ip_range, arguments=" ".join(arguments))
    except nmap.PortScannerError as exc:
        raise RuntimeError(f"nmap could not run: {exc}") from exc

    results = []
    for host in scanner.all_hosts():
        results.append({
            "host": host,
            "hostname": scanner[host].hostname(),
            "tcp": scanner[host].get("tcp", {}),
        })
    return results


def _format_scan(results: list[dict], deep: bool) -> str:
    if not results:
        return "No hosts responded. Nothing is up on that range, or the scan was blocked."

    lines = ["Hosts found:"]
    for r in results:
        open_ports = sorted(int(p) for p, i in r["tcp"].items() if i.get("state") == "open")
        ports_str = ",".join(str(p) for p in open_ports) or "-"
        name = r["hostname"] or "-"
        lines.append(f"  {r['host']:<15}  {name:<24}  ports: {ports_str}")

    lines.append("")
    lines.append("=" * 56)
    lines.append("SECURITY REPORT")
    lines.append("=" * 56)
    totals = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in results:
        findings = _assess_host(r["tcp"]) + _script_findings(r["tcp"])
        findings.sort(key=lambda f: (_SEVERITY_ORDER[f["severity"]], f["port"]))
        header = r["host"] + (f"  ({r['hostname']})" if r["hostname"] else "")
        lines.append(header)
        if not findings:
            lines.append("  No obvious issues from exposed services.")
            continue
        for f in findings:
            if f["severity"] in totals:
                totals[f["severity"]] += 1
            lines.append(f"  [{f['severity']:<6}] {f['title']} (port {f['port']})")
            lines.append(f"           {f['detail']}")
            lines.append(f"           Fix: {f['fix']}")
    lines.append("-" * 56)
    lines.append(f"Totals: {totals['HIGH']} high, {totals['MEDIUM']} medium, {totals['LOW']} low.")
    lines.append("Review high-severity items first. Advice is general hardening guidance; "
                 "verify against your own setup.")
    return "\n".join(lines)


@tool(
    "Scan your local network for devices and flag risky exposed services (telnet, SMB, "
    "exposed databases, open proxies, outdated services, etc.) with plain-language fixes. "
    "target: a host, hostname, or CIDR range; leave blank to auto-detect your /24 subnet. "
    "deep=True also runs nmap's CVE scripts (much slower). Use only on networks you own or "
    "are authorized to scan."
)
def scan_local_network(target: str = "", deep: bool = False) -> str:
    ip_range = (target or "").strip() or _local_subnet()
    try:
        results = _scan_network(ip_range, deep)
    except RuntimeError as exc:
        return str(exc)
    except Exception as exc:  # defensive: nmap/library surprises
        logger.debug("scan_local_network failed", exc_info=True)
        return f"Scan failed: {exc}"
    return f"Scanned {ip_range}.\n\n" + _format_scan(results, deep)


# ── External exposure (Shodan InternetDB) ────────────────────────────────────
async def _public_ip() -> str | None:
    import httpx
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "plia-netcheck"}) as c:
                ip = (await c.get(url)).text.strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                return ip
        except Exception:
            continue
    return None


@tool(
    "Check what your network exposes to the public internet, using Shodan's free "
    "InternetDB. Shows your public IP, any internet-reachable ports with hardening advice, "
    "and known CVEs seen on that IP. Contacts external services, which will see your IP."
)
async def external_exposure_check() -> str:
    import httpx
    ip = await _public_ip()
    if not ip:
        return "Could not determine your public IP address (no internet?)."

    lines = [f"Public IP: {ip}", ""]
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "plia-netcheck"}) as c:
            resp = await c.get(f"https://internetdb.shodan.io/{ip}")
        data = {} if resp.status_code == 404 else resp.json()
    except Exception as exc:
        return f"Public IP: {ip}\n\nCould not query the external exposure database ({exc})."

    hostnames = data.get("hostnames") or []
    ports = sorted(data.get("ports") or [])
    vulns = sorted(data.get("vulns") or [])
    tags = data.get("tags") or []
    if hostnames:
        lines.append("Hostnames: " + ", ".join(hostnames))
        lines.append("")

    if not ports:
        lines.append("No open ports are visible from the internet — this is the result you want.")
        lines.append("Your router is not exposing services to the outside.")
    else:
        lines.append(f"{len(ports)} port(s) reachable from the internet:")
        for port in ports:
            rule = _PORT_RULES.get(port)
            if rule:
                sev, title, detail, fix = rule
            else:
                sev, title = "MEDIUM", "Service exposed to the internet"
                detail = "This port is reachable from the public internet."
                fix = ("Remove any port-forwarding rule for it and disable UPnP on your "
                       "router, unless you truly need it open.")
            if sev == "LOW":  # internet-facing is never merely low
                sev = "MEDIUM"
            lines.append(f"  [{sev:<6}] Port {port} — {title}")
            lines.append(f"           {detail}")
            lines.append(f"           Fix: {fix}")

    if vulns:
        shown = ", ".join(vulns[:15]) + (" ..." if len(vulns) > 15 else "")
        lines.append("")
        lines.append(f"Known CVEs seen on this IP ({len(vulns)}): {shown}")
        lines.append("  Fix: these are internet-reachable — update the exposed device/firmware "
                     "as a priority.")
    if tags:
        lines.append("Tags: " + ", ".join(tags))

    lines.append("-" * 56)
    lines.append("Source: Shodan InternetDB — its most recent internet-wide scan, so results "
                 "can be days or weeks old.")
    if ports:
        lines.append("To close exposure: on your router, remove unwanted Port Forwarding rules "
                     "and turn off UPnP, then re-check.")
    return "\n".join(lines)
