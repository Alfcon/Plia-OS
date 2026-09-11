from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ═══════════════════════════════════════════════════════════════════
# Network Diagnostics
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ping_ok():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"PING 127.0.0.1: 1 data bytes\n64 bytes from 127.0.0.1: icmp_seq=0 time=0.1 ms\n", b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/netdiag/ping", json={"host": "127.0.0.1"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["host"] == "127.0.0.1"
    assert "rtt_ms" in data
    assert "latency_ms" in data


@pytest.mark.asyncio
async def test_ping_fail():
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"Request timeout\n", b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/netdiag/ping", json={"host": "10.255.255.1"})
    assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_ping_missing_host_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/netdiag/ping", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dns_ok():
    fake_infos = [
        (None, None, None, None, ("1.2.3.4", 0)),
        (None, None, None, None, ("5.6.7.8", 0)),
    ]
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock(return_value=fake_infos)
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/netdiag/dns", json={"host": "example.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "1.2.3.4" in data["ips"]


@pytest.mark.asyncio
async def test_dns_missing_host_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/netdiag/dns", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dns_failure_returns_ok_false():
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock(side_effect=OSError("Name not known"))
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/netdiag/dns", json={"host": "notexist.invalid"})
    data = r.json()
    assert data["ok"] is False
    assert data["ips"] == []


@pytest.mark.asyncio
async def test_port_open():
    mock_reader, mock_writer = MagicMock(), MagicMock()
    mock_writer.wait_closed = AsyncMock()
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/netdiag/port", json={"host": "127.0.0.1", "port": 8000})
    data = r.json()
    assert data["ok"] is True
    assert data["detail"] == "open"


@pytest.mark.asyncio
async def test_port_refused():
    with patch("asyncio.open_connection", side_effect=ConnectionRefusedError("refused")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/netdiag/port", json={"host": "127.0.0.1", "port": 9})
    assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_port_missing_fields_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/netdiag/port", json={"host": "127.0.0.1"})
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Notification Log
# ═══════════════════════════════════════════════════════════════════

def _reset_notif_log():
    import dashboard.server as srv
    srv._NOTIF_LOG.clear()


@pytest.mark.asyncio
async def test_notif_log_empty():
    _reset_notif_log()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/notifications/log")
    assert r.status_code == 200
    assert r.json()["notifications"] == []


@pytest.mark.asyncio
async def test_notif_log_populated():
    import dashboard.server as srv
    _reset_notif_log()
    srv._NOTIF_LOG.appendleft({"ts": time.time(), "source": "reminder", "message": "Take a break", "id": 1})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/notifications/log")
    notifications = r.json()["notifications"]
    assert len(notifications) == 1
    assert notifications[0]["message"] == "Take a break"
    _reset_notif_log()


@pytest.mark.asyncio
async def test_notif_log_n_param():
    import dashboard.server as srv
    _reset_notif_log()
    for i in range(20):
        srv._NOTIF_LOG.appendleft({"ts": time.time(), "source": "reminder", "message": f"msg {i}", "id": i})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/notifications/log?n=5")
    assert len(r.json()["notifications"]) == 5
    _reset_notif_log()


@pytest.mark.asyncio
async def test_notif_log_clear():
    import dashboard.server as srv
    _reset_notif_log()
    srv._NOTIF_LOG.appendleft({"ts": time.time(), "source": "reminder", "message": "hi", "id": 1})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/notifications/log")
    assert r.json()["ok"] is True
    assert len(srv._NOTIF_LOG) == 0


def test_notif_log_handler_appends_reminder():
    import dashboard.server as srv
    _reset_notif_log()
    srv._on_notif_event({"type": "reminder_fired", "id": 99, "message": "Test reminder"})
    assert len(srv._NOTIF_LOG) == 1
    assert srv._NOTIF_LOG[0]["source"] == "reminder"
    assert srv._NOTIF_LOG[0]["message"] == "Test reminder"
    _reset_notif_log()


def test_notif_log_handler_ignores_other_events():
    import dashboard.server as srv
    _reset_notif_log()
    srv._on_notif_event({"type": "status", "state": "armed"})
    assert len(srv._NOTIF_LOG) == 0


# ═══════════════════════════════════════════════════════════════════
# Config Diff
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cfgdiff_defaults_no_diff():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config/diff")
    assert r.status_code == 200
    data = r.json()
    assert "diffs" in data
    assert "total" in data
    assert data["total"] == len(data["diffs"])


@pytest.mark.asyncio
async def test_cfgdiff_detects_changed_field():
    from core.config import update_config
    update_config(ollama_model="my-custom-model")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config/diff")
    diffs = {d["key"]: d for d in r.json()["diffs"]}
    assert "ollama_model" in diffs
    assert diffs["ollama_model"]["default"] == "llama3.2"
    assert diffs["ollama_model"]["current"] == "my-custom-model"
    update_config(ollama_model="llama3.2")


@pytest.mark.asyncio
async def test_cfgdiff_excludes_secrets():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config/diff")
    keys = [d["key"] for d in r.json()["diffs"]]
    assert "hass_token" not in keys
    assert "fallback_api_key" not in keys
    assert "system_prompt_backup" not in keys


@pytest.mark.asyncio
async def test_cfgdiff_total_matches_list():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/config/diff")
    data = r.json()
    assert data["total"] == len(data["diffs"])
