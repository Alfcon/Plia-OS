from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── Unit: interpolation ───────────────────────────────────────────────────────

def test_interpolate_payload():
    from agents.workflow_store import _interpolate
    assert _interpolate("{{payload}}", [], {"x": 1}) == '{"x": 1}'


def test_interpolate_payload_key():
    from agents.workflow_store import _interpolate
    assert _interpolate("{{payload.name}}", [], {"name": "Alice"}) == "Alice"


def test_interpolate_payload_missing_key():
    from agents.workflow_store import _interpolate
    result = _interpolate("{{payload.missing}}", [], {"x": 1})
    assert result == "{{payload.missing}}"


def test_interpolate_no_payload():
    from agents.workflow_store import _interpolate
    result = _interpolate("{{payload}}", [], None)
    assert result == "{{payload}}"


# ── Unit: webhook_store CRUD ──────────────────────────────────────────────────

def test_save_and_get(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        from agents.webhook_store import save_webhook, get_webhook
        save_webhook("ping", target="get_time", target_type="tool")
        wh = get_webhook("ping")
    assert wh["slug"] == "ping"
    assert wh["target"] == "get_time"
    assert wh["target_type"] == "tool"


def test_list_empty(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        from agents.webhook_store import list_webhooks
        assert list_webhooks() == []


def test_list_populated(tmp_path):
    p = tmp_path / "wh.json"
    with patch("agents.webhook_store._webhooks_path", return_value=p):
        from agents.webhook_store import save_webhook, list_webhooks
        save_webhook("a", target="wf1", target_type="workflow")
        save_webhook("b", target="tool1", target_type="tool")
        result = list_webhooks()
    assert {w["slug"] for w in result} == {"a", "b"}


def test_delete(tmp_path):
    p = tmp_path / "wh.json"
    with patch("agents.webhook_store._webhooks_path", return_value=p):
        from agents.webhook_store import save_webhook, delete_webhook, get_webhook
        save_webhook("todel", target="x", target_type="tool")
        assert delete_webhook("todel") is True
        assert get_webhook("todel") is None


def test_delete_nonexistent(tmp_path):
    p = tmp_path / "wh.json"
    with patch("agents.webhook_store._webhooks_path", return_value=p):
        from agents.webhook_store import delete_webhook
        assert delete_webhook("ghost") is False


# ── Unit: fire_webhook ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fire_tool_webhook(tmp_path):
    p = tmp_path / "wh.json"
    with patch("agents.webhook_store._webhooks_path", return_value=p):
        from agents.webhook_store import save_webhook, fire_webhook
        save_webhook("greet", target="get_time", target_type="tool")
        with patch("agents.webhook_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "12:00"
            result = await fire_webhook("greet", {})
    assert result["ok"] is True
    assert result["result"] == "12:00"
    assert result["type"] == "tool"


@pytest.mark.asyncio
async def test_fire_workflow_webhook(tmp_path):
    pwh = tmp_path / "wh.json"
    pwf = tmp_path / "wf.json"
    with patch("agents.webhook_store._webhooks_path", return_value=pwh), \
         patch("agents.workflow_store._workflows_path", return_value=pwf):
        from agents.webhook_store import save_webhook, fire_webhook
        from agents.workflow_store import save_workflow
        save_workflow("myflow", [{"tool": "get_time", "params": {}, "note": ""}], "")
        save_webhook("run-flow", target="myflow", target_type="workflow")
        with patch("agents.workflow_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "done"
            result = await fire_webhook("run-flow", {"key": "val"})
    assert result["ok"] is True
    assert result["type"] == "workflow"
    assert len(result["steps"]) == 1


@pytest.mark.asyncio
async def test_fire_missing_webhook(tmp_path):
    p = tmp_path / "wh.json"
    with patch("agents.webhook_store._webhooks_path", return_value=p):
        from agents.webhook_store import fire_webhook
        with pytest.raises(KeyError):
            await fire_webhook("ghost", {})


@pytest.mark.asyncio
async def test_fire_tool_error(tmp_path):
    p = tmp_path / "wh.json"
    with patch("agents.webhook_store._webhooks_path", return_value=p):
        from agents.webhook_store import save_webhook, fire_webhook
        save_webhook("boom", target="bad_tool", target_type="tool")
        with patch("agents.webhook_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("failed")
            result = await fire_webhook("boom", {})
    assert result["ok"] is False
    assert result["error"] == "failed"


# ── API endpoint tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_list_empty(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/webhooks")
    assert r.status_code == 200
    assert r.json()["webhooks"] == []


@pytest.mark.asyncio
async def test_api_save_and_list(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks", json={"slug": "test", "target": "get_time", "target_type": "tool"})
            assert r.status_code == 200
            r2 = await c.get("/api/webhooks")
    assert any(w["slug"] == "test" for w in r2.json()["webhooks"])


@pytest.mark.asyncio
async def test_api_save_missing_slug():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/webhooks", json={"target": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_save_missing_target():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/webhooks", json={"slug": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_delete(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/webhooks", json={"slug": "todel", "target": "x", "target_type": "tool"})
            r = await c.delete("/api/webhooks/todel")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_api_delete_not_found(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/webhooks/ghost")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_trigger(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        with patch("agents.webhook_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "pong"
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                await c.post("/api/webhooks", json={"slug": "ping", "target": "get_time", "target_type": "tool"})
                r = await c.post("/api/webhooks/trigger/ping", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_api_trigger_secret_required(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/webhooks", json={"slug": "secure", "target": "x", "target_type": "tool", "secret": "abc123"})
            r = await c.post("/api/webhooks/trigger/secure", json={})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_trigger_secret_correct(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        with patch("agents.webhook_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "ok"
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                await c.post("/api/webhooks", json={"slug": "secure2", "target": "x", "target_type": "tool", "secret": "abc123"})
                r = await c.post("/api/webhooks/trigger/secure2", json={},
                                 headers={"X-Webhook-Secret": "abc123"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_api_trigger_not_found(tmp_path):
    with patch("agents.webhook_store._webhooks_path", return_value=tmp_path / "wh.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/webhooks/trigger/ghost", json={})
    assert r.status_code == 404
