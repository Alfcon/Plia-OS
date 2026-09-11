from __future__ import annotations

import asyncio
import logging
import re
import socket
import time

from core.registry import tool

logger = logging.getLogger(__name__)

_HOST_RE = re.compile(r"^[A-Za-z0-9.:-]+$")
_CF_DOWN = "https://speed.cloudflare.com/__down?bytes={n}"
_CF_UP = "https://speed.cloudflare.com/__up"


@tool(
    "Show this system's public (internet-facing) IP address, plus ISP and rough location. "
    "Contacts an external lookup service, which will see your IP."
)
async def public_ip() -> str:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get("http://ip-api.com/json")
            data = r.json()
        ip = data.get("query")
        if ip:
            isp = data.get("isp") or "?"
            loc = ", ".join(p for p in (data.get("city"), data.get("country")) if p) or "?"
            return f"Public IP: {ip}\nISP: {isp}\nLocation: {loc}"
    except Exception:
        logger.debug("ip-api lookup failed", exc_info=True)
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get("https://api.ipify.org?format=json")
            ip = r.json().get("ip")
        if ip:
            return f"Public IP: {ip}"
        return "Could not determine public IP."
    except Exception as exc:
        return f"Could not determine public IP: {exc}"


@tool(
    "Ping a host to measure latency and packet loss. Pass a hostname or IP (e.g. 1.1.1.1). "
    "count = number of packets to send (1-10, default 4)."
)
async def ping_host(host: str, count: int = 4) -> str:
    if not host or not _HOST_RE.match(host):
        return "Invalid host."
    try:
        n = min(max(int(count), 1), 10)
    except (TypeError, ValueError):
        n = 4
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", str(n), "-w", "15", host,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return "ping not found on this system."
    except Exception as exc:
        return f"Ping failed: {exc}"
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return "Ping timed out."
    except Exception as exc:
        return f"Ping failed: {exc}"
    out = (out_b or b"").decode(errors="replace")
    err = (err_b or b"").decode(errors="replace")
    rtt = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)", out)
    loss = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", out)
    if rtt:
        loss_s = f"{loss.group(1)}%" if loss else "?"
        return f"{host}: {loss_s} loss, rtt min/avg/max = {rtt.group(1)}/{rtt.group(2)}/{rtt.group(3)} ms"
    tail = [ln for ln in (out + err).splitlines() if ln.strip()]
    return tail[-1] if tail else f"{host}: no reply."


@tool(
    "Resolve a domain name to its IP address(es) using the system resolver. "
    "Pass a hostname (e.g. example.com)."
)
async def dns_lookup(hostname: str) -> str:
    if not hostname or not _HOST_RE.match(hostname):
        return "Invalid hostname."
    try:
        infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, None), timeout=5
        )
        ips = sorted({i[4][0] for i in infos})
        if not ips:
            return f"{hostname}: no addresses."
        return f"{hostname} → {', '.join(ips)}"
    except asyncio.TimeoutError:
        return f"DNS lookup timed out for {hostname}."
    except Exception as exc:
        return f"DNS lookup failed for {hostname}: {exc}"


@tool(
    "Measure internet download and upload speed (approximate). Transfers ~35 MB to/from an "
    "external server (speed.cloudflare.com), which will see your IP."
)
async def network_speedtest() -> str:
    import httpx
    down_bytes = 25_000_000
    up_bytes = 10_000_000
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            t0 = time.perf_counter()
            r = await c.get(_CF_DOWN.format(n=down_bytes))
            recv = len(r.content)
            dt = time.perf_counter() - t0
            down = (recv * 8) / (dt * 1_000_000) if dt > 0 else 0.0
            payload = b"\0" * up_bytes
            t1 = time.perf_counter()
            await c.post(_CF_UP, content=payload)
            ut = time.perf_counter() - t1
            up = (up_bytes * 8) / (ut * 1_000_000) if ut > 0 else 0.0
        return (
            f"Download: {down:.1f} Mbps\n"
            f"Upload: {up:.1f} Mbps\n"
            "(approx, via speed.cloudflare.com)"
        )
    except Exception as exc:
        return f"Speed test failed: {exc}"
