from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset_timeline():
    import dashboard.server as srv
    srv._VRAM_TIMELINE.clear()


def _push_samples(n: int, used: float = 1.5, total: float = 8.0):
    import dashboard.server as srv
    import time
    for i in range(n):
        srv._VRAM_TIMELINE.append({
            "ts": time.time() + i * 5,
            "used_gb": used,
            "total_gb": total,
            "models": {"kokoro": 0.5} if i % 2 == 0 else {},
        })


# ── GET /api/vram/timeline ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeline_empty():
    _reset_timeline()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/vram/timeline")
    assert r.status_code == 200
    data = r.json()
    assert "samples" in data
    assert data["samples"] == []


@pytest.mark.asyncio
async def test_timeline_returns_samples():
    _reset_timeline()
    _push_samples(10)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/vram/timeline")
    data = r.json()
    assert len(data["samples"]) == 10


@pytest.mark.asyncio
async def test_timeline_n_param_limits():
    _reset_timeline()
    _push_samples(50)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/vram/timeline?n=10")
    assert len(r.json()["samples"]) == 10


@pytest.mark.asyncio
async def test_timeline_n_capped_at_120():
    _reset_timeline()
    _push_samples(120)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/vram/timeline?n=9999")
    assert len(r.json()["samples"]) <= 120


@pytest.mark.asyncio
async def test_timeline_sample_shape():
    _reset_timeline()
    _push_samples(3, used=2.0, total=8.0)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/vram/timeline")
    s = r.json()["samples"][0]
    assert "ts" in s
    assert "used_gb" in s
    assert "total_gb" in s
    assert "models" in s


@pytest.mark.asyncio
async def test_timeline_interval_field():
    _reset_timeline()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/vram/timeline")
    assert r.json()["interval_s"] == 5


@pytest.mark.asyncio
async def test_timeline_ring_buffer_maxlen():
    import dashboard.server as srv
    _reset_timeline()
    _push_samples(130)
    assert len(srv._VRAM_TIMELINE) == 120
    _reset_timeline()


# ── run_vram_sampler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sampler_appends_to_timeline():
    import dashboard.server as srv
    _reset_timeline()

    mock_status = {
        "vram_used_gb": 1.5,
        "vram_total_gb": 8.0,
        "models": {"kokoro": {"vram_gb": 0.5}},
    }
    with patch("dashboard.server.get_vram_broker") as mock_broker:
        mock_broker.return_value.status.return_value = mock_status
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
            try:
                await srv.run_vram_sampler()
            except asyncio.CancelledError:
                pass

    assert len(srv._VRAM_TIMELINE) == 1
    s = srv._VRAM_TIMELINE[0]
    assert s["used_gb"] == 1.5
    assert s["total_gb"] == 8.0
    assert s["models"] == {"kokoro": 0.5}
    _reset_timeline()


@pytest.mark.asyncio
async def test_sampler_skips_zero_vram_models():
    import dashboard.server as srv
    _reset_timeline()

    mock_status = {
        "vram_used_gb": 0.0,
        "vram_total_gb": 8.0,
        "models": {"kokoro": {"vram_gb": 0.0}, "whisper": {"vram_gb": 0.3}},
    }
    with patch("dashboard.server.get_vram_broker") as mock_broker:
        mock_broker.return_value.status.return_value = mock_status
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
            try:
                await srv.run_vram_sampler()
            except asyncio.CancelledError:
                pass

    s = srv._VRAM_TIMELINE[0]
    assert "kokoro" not in s["models"]
    assert "whisper" in s["models"]
    _reset_timeline()
