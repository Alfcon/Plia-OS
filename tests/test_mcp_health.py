from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_mcp_health_empty_when_no_servers():
    with patch("core.mcp_client.get_mcp_status", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/mcp/health")
    assert r.status_code == 200
    data = r.json()
    assert data["servers"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_mcp_health_unknown_before_first_ping():
    servers = [{"name": "test-srv", "healthy": True}]
    with patch("core.mcp_client.get_mcp_status", return_value=servers):
        import dashboard.server as srv
        srv._MCP_HEALTH.pop("test-srv", None)
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/mcp/health")
    data = r.json()
    assert data["servers"][0]["status"] == "unknown"
    assert data["servers"][0]["checked_at"] is None


@pytest.mark.asyncio
async def test_mcp_health_reflects_stored_result():
    import time
    import dashboard.server as srv
    srv._MCP_HEALTH["my-srv"] = {"name": "my-srv", "status": "ok", "latency_ms": 42, "last_error": None, "checked_at": time.time()}
    with patch("core.mcp_client.get_mcp_status", return_value=[{"name": "my-srv", "healthy": True}]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/mcp/health")
    srv._MCP_HEALTH.pop("my-srv", None)
    s = r.json()["servers"][0]
    assert s["latency_ms"] == 42
    assert s["status"] == "ok"


@pytest.mark.asyncio
async def test_ping_disabled_server():
    from dashboard.server import _ping_mcp_server
    import core.mcp_client as mc
    orig_dis, orig_srv = mc._disabled_servers, mc._servers
    mc._disabled_servers = {"disabled-srv"}
    mc._servers = {}
    try:
        result = await _ping_mcp_server("disabled-srv")
    finally:
        mc._disabled_servers = orig_dis
        mc._servers = orig_srv
    assert result["status"] == "disabled"


@pytest.mark.asyncio
async def test_ping_not_connected_server():
    from dashboard.server import _ping_mcp_server
    import core.mcp_client as mc
    orig_dis, orig_srv = mc._disabled_servers, mc._servers
    mc._disabled_servers = set()
    mc._servers = {}
    try:
        result = await _ping_mcp_server("unknown-srv")
    finally:
        mc._disabled_servers = orig_dis
        mc._servers = orig_srv
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_ping_all_endpoint():
    with patch("core.mcp_client.get_mcp_status", return_value=[{"name": "s1", "healthy": True}]), \
         patch("dashboard.server._ping_mcp_server", new=AsyncMock(return_value={"name": "s1", "status": "ok", "latency_ms": 5, "last_error": None, "checked_at": 1.0})):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/mcp/health/ping")
    assert r.status_code == 200
    assert r.json()["servers"][0]["status"] == "ok"
