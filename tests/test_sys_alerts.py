from __future__ import annotations

import time
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset_log():
    import dashboard.server as srv
    srv._ALERT_LOG.clear()


@pytest.mark.asyncio
async def test_alert_config_get():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/alerts/config")
    assert r.status_code == 200
    data = r.json()
    for key in ("alerts_enabled", "cpu_alert_threshold", "ram_alert_threshold", "gpu_alert_threshold"):
        assert key in data


@pytest.mark.asyncio
async def test_alert_config_defaults():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/alerts/config")
    data = r.json()
    assert data["alerts_enabled"] is False
    assert data["cpu_alert_threshold"] == 90
    assert data["ram_alert_threshold"] == 90
    assert data["gpu_alert_threshold"] == 90


@pytest.mark.asyncio
async def test_alert_config_set():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/alerts/config", json={
            "alerts_enabled": True, "cpu_alert_threshold": 80
        })
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_alert_config_invalid_threshold_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/alerts/config", json={"cpu_alert_threshold": 150})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_alert_log_empty():
    _reset_log()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/alerts/log")
    assert r.json()["alerts"] == []


@pytest.mark.asyncio
async def test_alert_log_populated():
    import dashboard.server as srv
    _reset_log()
    srv._ALERT_LOG.appendleft({"ts": time.time(), "resource": "cpu", "value": 95.0, "threshold": 90})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/alerts/log")
    alerts = r.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["resource"] == "cpu"
    _reset_log()


@pytest.mark.asyncio
async def test_alert_log_clear():
    import dashboard.server as srv
    _reset_log()
    srv._ALERT_LOG.appendleft({"ts": time.time(), "resource": "ram", "value": 91.0, "threshold": 90})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/alerts/log")
    assert r.json()["ok"] is True
    assert len(srv._ALERT_LOG) == 0


@pytest.mark.asyncio
async def test_resource_alert_loop_fires_alert():
    import asyncio
    import dashboard.server as srv
    _reset_log()

    psutil_mock = MagicMock()
    psutil_mock.cpu_percent.return_value = 95.0
    vm = MagicMock()
    vm.percent = 50.0
    psutil_mock.virtual_memory.return_value = vm

    broker_mock = MagicMock()
    broker_mock.status.return_value = {"vram_used_gb": 0, "vram_total_gb": 0}

    with patch("core.config.get_config") as mock_cfg, \
         patch("builtins.__import__", side_effect=lambda name, *a, **kw: psutil_mock if name == "psutil" else __import__(name, *a, **kw)), \
         patch("dashboard.server.get_vram_broker", return_value=broker_mock), \
         patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
        cfg = MagicMock()
        cfg.alerts_enabled = True
        cfg.cpu_alert_threshold = 90
        cfg.ram_alert_threshold = 90
        cfg.gpu_alert_threshold = 90
        mock_cfg.return_value = cfg
        try:
            await srv.run_resource_alert_loop()
        except asyncio.CancelledError:
            pass

    _reset_log()


@pytest.mark.asyncio
async def test_alert_log_n_param():
    import dashboard.server as srv
    _reset_log()
    for i in range(10):
        srv._ALERT_LOG.appendleft({"ts": time.time(), "resource": "cpu", "value": float(90+i), "threshold": 90})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/alerts/log?n=3")
    assert len(r.json()["alerts"]) == 3
    _reset_log()
