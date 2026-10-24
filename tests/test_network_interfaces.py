from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


_SAMPLE_IFACES = [
    {
        "ifname": "lo", "operstate": "UNKNOWN", "link_type": "loopback",
        "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}],
    },
    {
        "ifname": "eth0", "operstate": "UP", "link_type": "ether",
        "addr_info": [{"family": "inet", "local": "192.168.1.10", "prefixlen": 24}],
    },
]
_SAMPLE_JSON = json.dumps(_SAMPLE_IFACES).encode()


@pytest.mark.asyncio
async def test_network_interfaces_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_JSON)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/network/interfaces")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert d["interfaces"][0]["ifname"] == "lo"


@pytest.mark.asyncio
async def test_network_interfaces_503_when_ip_missing():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1, b"", b"ip not found")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/network/interfaces")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_network_interfaces_addr_info():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_JSON)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/network/interfaces")
    eth = next(i for i in r.json()["interfaces"] if i["ifname"] == "eth0")
    assert eth["addr_info"][0]["local"] == "192.168.1.10"


@pytest.mark.asyncio
async def test_network_interfaces_empty_output():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, b"[]")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/network/interfaces")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_network_interfaces_malformed_json_graceful():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, b"not json")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/network/interfaces")
    assert r.status_code == 200
    assert r.json()["interfaces"] == []


@pytest.mark.asyncio
async def test_network_interfaces_total_field():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_JSON)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/network/interfaces")
    assert r.json()["total"] == len(r.json()["interfaces"])
