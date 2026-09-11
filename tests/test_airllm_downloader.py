from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset_dl_state():
    import dashboard.server as srv
    srv._DL_STATE.update({"state": "idle", "model": "", "file": "", "bytes": 0, "total": 0, "error": ""})


# ── POST /api/airllm/download ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_download_starts_ok():
    _reset_dl_state()
    with patch("dashboard.server._run_download", new_callable=lambda: lambda *a: AsyncMock()):
        with patch("asyncio.create_task"):
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                r = await c.post("/api/airllm/download", json={"model": "meta-llama/Llama-3.2-1B-Instruct"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["model"] == "meta-llama/Llama-3.2-1B-Instruct"


@pytest.mark.asyncio
async def test_download_missing_model_422():
    _reset_dl_state()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/airllm/download", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_download_empty_model_422():
    _reset_dl_state()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/airllm/download", json={"model": "  "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_download_already_in_progress_409():
    import dashboard.server as srv
    _reset_dl_state()
    srv._DL_STATE["state"] = "downloading"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/airllm/download", json={"model": "some/model"})
    assert r.status_code == 409
    _reset_dl_state()


# ── GET /api/airllm/download/status ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_idle():
    _reset_dl_state()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/airllm/download/status")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "idle"
    assert data["pct"] == 0


@pytest.mark.asyncio
async def test_status_progress():
    import dashboard.server as srv
    _reset_dl_state()
    srv._DL_STATE.update({"state": "downloading", "model": "x/y", "bytes": 500_000_000, "total": 1_000_000_000, "file": "model.safetensors"})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/airllm/download/status")
    data = r.json()
    assert data["state"] == "downloading"
    assert data["pct"] == 50.0
    assert data["file"] == "model.safetensors"
    _reset_dl_state()


@pytest.mark.asyncio
async def test_status_done():
    import dashboard.server as srv
    _reset_dl_state()
    srv._DL_STATE.update({"state": "done", "model": "x/y", "bytes": 1000, "total": 1000})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/airllm/download/status")
    assert r.json()["state"] == "done"
    assert r.json()["pct"] == 100.0
    _reset_dl_state()


@pytest.mark.asyncio
async def test_status_error():
    import dashboard.server as srv
    _reset_dl_state()
    srv._DL_STATE.update({"state": "error", "error": "auth required"})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/airllm/download/status")
    data = r.json()
    assert data["state"] == "error"
    assert "auth required" in data["error"]
    _reset_dl_state()


# ── _download_sync (unit) ─────────────────────────────────────────────────────

def test_download_sync_calls_snapshot_download():
    import dashboard.server as srv
    _reset_dl_state()
    with patch("huggingface_hub.snapshot_download") as mock_snap:
        srv._download_sync("some/model")
    mock_snap.assert_called_once()
    args, kwargs = mock_snap.call_args
    assert args[0] == "some/model"
    assert "tqdm_class" in kwargs


def test_download_sync_updates_state_on_progress():
    import dashboard.server as srv
    _reset_dl_state()

    def fake_snapshot(repo_id, tqdm_class=None):
        t = tqdm_class(total=1000, desc="weights.safetensors")
        t.update(400)

    with patch("huggingface_hub.snapshot_download", side_effect=fake_snapshot):
        srv._download_sync("x/y")

    assert srv._DL_STATE["bytes"] == 400
    assert srv._DL_STATE["total"] == 1000
    _reset_dl_state()
