import asyncio
import socket
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── fake httpx async client ──────────────────────────────────────────────────
class _Resp:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data
        self.content = content
    def json(self):
        return self._json


class _Len:
    """A stand-in for response.content with a controllable len() (no big alloc)."""
    def __init__(self, n):
        self.n = n
    def __len__(self):
        return self.n


class _Client:
    def __init__(self, get_resp=None, post_resp=None, get_exc=None):
        self._get_resp = get_resp
        self._post_resp = post_resp
        self._get_exc = get_exc
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, **k):
        if self._get_exc:
            raise self._get_exc
        return self._get_resp
    async def post(self, url, **k):
        return self._post_resp


@pytest.mark.asyncio
async def test_public_ip_primary():
    import modules.diagnostics_tools as d
    client = _Client(get_resp=_Resp(json_data={
        "query": "203.0.113.7", "isp": "Acme ISP", "city": "Perth", "country": "Australia"}))
    with patch("httpx.AsyncClient", return_value=client):
        out = await d.public_ip()
    assert "203.0.113.7" in out and "Acme ISP" in out and "Perth" in out


@pytest.mark.asyncio
async def test_public_ip_fallback_to_ipify():
    import modules.diagnostics_tools as d
    primary = _Client(get_exc=RuntimeError("ip-api down"))
    fallback = _Client(get_resp=_Resp(json_data={"ip": "198.51.100.9"}))
    with patch("httpx.AsyncClient", side_effect=[primary, fallback]):
        out = await d.public_ip()
    assert "198.51.100.9" in out


@pytest.mark.asyncio
async def test_public_ip_both_fail():
    import modules.diagnostics_tools as d
    with patch("httpx.AsyncClient", side_effect=[_Client(get_exc=RuntimeError("a")),
                                                 _Client(get_exc=RuntimeError("b"))]):
        out = await d.public_ip()
    assert "could not determine" in out.lower()


PING_OUT = (
    b"PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.\n"
    b"64 bytes from 1.1.1.1: icmp_seq=1 ttl=59 time=3.4 ms\n"
    b"--- 1.1.1.1 ping statistics ---\n"
    b"4 packets transmitted, 4 received, 0% packet loss, time 3005ms\n"
    b"rtt min/avg/max/mdev = 1.234/3.400/5.600/0.100 ms\n"
)


@pytest.mark.asyncio
async def test_ping_host_parses():
    import modules.diagnostics_tools as d
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(PING_OUT, b""))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        out = await d.ping_host("1.1.1.1", 4)
    assert "3.400" in out and "0%" in out and "1.1.1.1" in out


@pytest.mark.asyncio
async def test_ping_host_invalid():
    import modules.diagnostics_tools as d
    with patch("asyncio.create_subprocess_exec", AsyncMock()) as m:
        out = await d.ping_host("a; rm -rf /")
    assert "invalid host" in out.lower()
    m.assert_not_called()


@pytest.mark.asyncio
async def test_ping_host_missing_binary():
    import modules.diagnostics_tools as d
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError())):
        out = await d.ping_host("1.1.1.1")
    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_dns_lookup_resolves():
    import modules.diagnostics_tools as d
    infos = [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("93.184.216.34", 0))]
    with patch("socket.getaddrinfo", return_value=infos):
        out = await d.dns_lookup("example.com")
    assert "93.184.216.34" in out and "example.com" in out


@pytest.mark.asyncio
async def test_dns_lookup_failure():
    import modules.diagnostics_tools as d
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")):
        out = await d.dns_lookup("nx.invalid")
    assert "failed" in out.lower()


@pytest.mark.asyncio
async def test_dns_lookup_invalid():
    import modules.diagnostics_tools as d
    out = await d.dns_lookup("bad name!")
    assert "invalid hostname" in out.lower()


@pytest.mark.asyncio
async def test_dns_lookup_timeout():
    import modules.diagnostics_tools as d
    async def _hang(*a, **k):
        raise asyncio.TimeoutError
    # patch wait_for to simulate the resolve exceeding the deadline
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        out = await d.dns_lookup("slow.example.com")
    assert "timed out" in out.lower()


@pytest.mark.asyncio
async def test_ping_host_communicate_error_never_raises():
    import modules.diagnostics_tools as d
    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=OSError("read error"))
    proc.kill = MagicMock()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        out = await d.ping_host("1.1.1.1")   # must NOT raise
    assert "failed" in out.lower()


@pytest.mark.asyncio
async def test_speedtest_math():
    import modules.diagnostics_tools as d
    client = _Client(get_resp=_Resp(content=_Len(25_000_000)), post_resp=_Resp())
    # perf_counter: t0=0 (before get), 1 (after get -> dt=1s), t1=10 (before post), 11 (after -> ut=1s)
    with patch("httpx.AsyncClient", return_value=client), \
         patch("time.perf_counter", side_effect=[0.0, 1.0, 10.0, 11.0]):
        out = await d.network_speedtest()
    assert "200.0 Mbps" in out   # 25 MB * 8 / 1e6 in 1s
    assert "80.0 Mbps" in out    # 10 MB * 8 / 1e6 in 1s


@pytest.mark.asyncio
async def test_speedtest_failure():
    import modules.diagnostics_tools as d
    with patch("httpx.AsyncClient", return_value=_Client(get_exc=RuntimeError("boom"))):
        out = await d.network_speedtest()
    assert "failed" in out.lower()


def test_diagnostics_tools_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.diagnostics_tools" in sys.modules:
        del sys.modules["modules.diagnostics_tools"]
    set_loading_module("diagnostics_tools")
    try:
        import modules.diagnostics_tools  # noqa: F401
    finally:
        set_loading_module("")
    tools = list_tools()
    for name in ("public_ip", "ping_host", "dns_lookup", "network_speedtest"):
        assert name in tools
