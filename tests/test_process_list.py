from __future__ import annotations

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


_PS_OUTPUT = (
    b"root         1  0.0  0.1  168280  9876 ?  Ss  00:00  0:01 /sbin/init\n"
    b"alice     1234  2.5  1.2  456000 12345 ?  Sl  01:00  1:23 python app.py\n"
    b"bob       5678 15.0  0.5  123456  5432 ?  R   02:00  0:45 node server.js\n"
)


@pytest.mark.asyncio
async def test_process_list_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _PS_OUTPUT)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/processes")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3
    assert len(d["processes"]) == 3


@pytest.mark.asyncio
async def test_process_sorted_by_cpu():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _PS_OUTPUT)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/processes?sort=cpu")
    procs = r.json()["processes"]
    assert procs[0]["cpu"] >= procs[1]["cpu"]


@pytest.mark.asyncio
async def test_process_sorted_by_mem():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _PS_OUTPUT)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/processes?sort=mem")
    procs = r.json()["processes"]
    assert procs[0]["mem"] >= procs[1]["mem"]


@pytest.mark.asyncio
async def test_process_fields():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _PS_OUTPUT)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/processes")
    p = r.json()["processes"][0]
    for field in ("user", "pid", "cpu", "mem", "stat", "command"):
        assert field in p, f"missing: {field}"


@pytest.mark.asyncio
async def test_process_limit():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _PS_OUTPUT)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/processes?limit=1")
    assert len(r.json()["processes"]) == 1


@pytest.mark.asyncio
async def test_process_503_on_failure():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/processes")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_kill_invalid_signal_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/processes/1234/kill", json={"signal": "rm -rf /"})
    assert r.status_code == 422
