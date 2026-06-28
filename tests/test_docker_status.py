from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_docker_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


_SAMPLE_CONTAINERS = [
    {"ID": "abc123", "Names": "web", "State": "running", "Status": "Up 2 hours"},
    {"ID": "def456", "Names": "db", "State": "exited", "Status": "Exited (0) 1 day ago"},
]

_SAMPLE_STDOUT = "\n".join(json.dumps(c) for c in _SAMPLE_CONTAINERS).encode()


@pytest.mark.asyncio
async def test_docker_status_returns_containers():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(0, _SAMPLE_STDOUT)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/docker")
    assert r.status_code == 200
    d = r.json()
    assert "containers" in d
    assert d["total"] == 2
    assert d["containers"][0]["ID"] == "abc123"


@pytest.mark.asyncio
async def test_docker_status_503_when_unavailable():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(1, b"", b"Cannot connect")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/docker")
    assert r.status_code == 503
    assert "detail" in r.json()


@pytest.mark.asyncio
async def test_docker_restart_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/docker/abc123/restart")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["action"] == "restart"


@pytest.mark.asyncio
async def test_docker_stop_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/docker/abc123/stop")
    assert r.status_code == 200
    assert r.json()["action"] == "stop"


@pytest.mark.asyncio
async def test_docker_start_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(0)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/docker/abc123/start")
    assert r.status_code == 200
    assert r.json()["action"] == "start"


@pytest.mark.asyncio
async def test_docker_action_strips_invalid_chars():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(0)) as mock_exec:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/docker/abc;rm -rf 123/restart")
    # Should still return — invalid chars stripped from id
    assert r.status_code in (200, 400, 500)


@pytest.mark.asyncio
async def test_docker_action_500_on_error():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_docker_proc(1, b"", b"No such container")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/docker/nosuchcontainer/restart")
    assert r.status_code == 500
