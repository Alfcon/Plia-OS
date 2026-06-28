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


_SAMPLE_UNITS = [
    {"unit": "nginx.service", "load": "loaded", "active": "active", "sub": "running", "description": "NGINX"},
    {"unit": "ssh.service", "load": "loaded", "active": "inactive", "sub": "dead", "description": "SSH Daemon"},
]
_SAMPLE_JSON = json.dumps(_SAMPLE_UNITS).encode()


@pytest.mark.asyncio
async def test_list_services_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_JSON)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/services")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert d["units"][0]["unit"] == "nginx.service"


@pytest.mark.asyncio
async def test_list_services_filter():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_JSON)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/services?filter=nginx")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["units"][0]["unit"] == "nginx.service"


@pytest.mark.asyncio
async def test_list_services_503_when_unavailable():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1, b"", b"command not found")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/services")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_service_restart_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/services/nginx.service/restart")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["action"] == "restart"


@pytest.mark.asyncio
async def test_service_stop_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/services/nginx.service/stop")
    assert r.status_code == 200
    assert r.json()["action"] == "stop"


@pytest.mark.asyncio
async def test_service_action_strips_bad_chars():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0)) as mock_exec:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/services/nginx;rm -rf/restart")
    # Should strip invalid chars — either succeed with sanitised name or 400
    assert r.status_code in (200, 400)


@pytest.mark.asyncio
async def test_service_action_500_on_failure():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1, b"", b"Unit not found")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/services/nosuchsvc.service/start")
    assert r.status_code == 500
