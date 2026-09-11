from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_webhook(slug="test-hook", target_type="tool", target="get_time", secret=""):
    return {
        "slug": slug,
        "name": slug,
        "target_type": target_type,
        "target": target,
        "params": {},
        "description": "",
        "secret": secret,
    }


# ── POST /api/webhooks/{slug}/test ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_test_not_found():
    with patch("agents.webhook_store.get_webhook", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/nonexistent/test", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_test_ok_returns_structure():
    fire_result = {"ok": True, "type": "tool", "result": "12:00 UTC", "error": None}
    with patch("agents.webhook_store.get_webhook", return_value=_mock_webhook()), \
         patch("agents.webhook_store.fire_webhook", new_callable=AsyncMock, return_value=fire_result):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/test-hook/test", json={"payload": {"x": 1}})
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data
    assert "result" in data
    assert "latency_ms" in data
    assert isinstance(data["latency_ms"], int)


@pytest.mark.asyncio
async def test_webhook_test_skips_secret_check():
    """Test endpoint must NOT enforce the secret — that's for external callers."""
    fire_result = {"ok": True, "type": "tool", "result": "done", "error": None}
    hook = _mock_webhook(secret="super-secret")
    with patch("agents.webhook_store.get_webhook", return_value=hook), \
         patch("agents.webhook_store.fire_webhook", new_callable=AsyncMock, return_value=fire_result):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/test-hook/test", json={})
    # No X-Webhook-Secret header provided — must succeed (test endpoint bypasses secret)
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_webhook_test_passes_custom_payload():
    received_payloads = []

    async def capture_fire(slug, payload):
        received_payloads.append(payload)
        return {"ok": True, "type": "tool", "result": "ok", "error": None}

    with patch("agents.webhook_store.get_webhook", return_value=_mock_webhook()), \
         patch("agents.webhook_store.fire_webhook", side_effect=capture_fire):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/webhooks/test-hook/test", json={"payload": {"event": "ping", "value": 42}})

    assert received_payloads[0] == {"event": "ping", "value": 42}


@pytest.mark.asyncio
async def test_webhook_test_empty_payload_defaults_to_dict():
    received_payloads = []

    async def capture_fire(slug, payload):
        received_payloads.append(payload)
        return {"ok": True, "type": "tool", "result": "ok", "error": None}

    with patch("agents.webhook_store.get_webhook", return_value=_mock_webhook()), \
         patch("agents.webhook_store.fire_webhook", side_effect=capture_fire):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/webhooks/test-hook/test", json={})

    assert isinstance(received_payloads[0], dict)


@pytest.mark.asyncio
async def test_webhook_test_fire_error_returns_ok_false():
    with patch("agents.webhook_store.get_webhook", return_value=_mock_webhook()), \
         patch("agents.webhook_store.fire_webhook", new_callable=AsyncMock, side_effect=Exception("workflow failed")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/test-hook/test", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "workflow failed" in data["error"]


@pytest.mark.asyncio
async def test_webhook_test_latency_is_nonnegative():
    fire_result = {"ok": True, "type": "tool", "result": "fast", "error": None}
    with patch("agents.webhook_store.get_webhook", return_value=_mock_webhook()), \
         patch("agents.webhook_store.fire_webhook", new_callable=AsyncMock, return_value=fire_result):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/test-hook/test", json={})
    assert r.json()["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_webhook_test_workflow_result():
    steps = [{"tool": "get_time", "result": "12:00", "error": None}]
    fire_result = {"ok": True, "type": "workflow", "steps": steps, "result": "12:00", "error": None}
    with patch("agents.webhook_store.get_webhook", return_value=_mock_webhook(target_type="workflow", target="my_flow")), \
         patch("agents.webhook_store.fire_webhook", new_callable=AsyncMock, return_value=fire_result):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/test-hook/test", json={"payload": {}})
    data = r.json()
    assert data["ok"] is True
    assert data["result"]["type"] == "workflow"
    assert len(data["result"]["steps"]) == 1
